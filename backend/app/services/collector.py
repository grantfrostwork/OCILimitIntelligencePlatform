from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import LimitItem, LimitSnapshot, OciService, ScanRun, new_id, utcnow
from app.services.alerts import AlertService
from app.services.oci_sdk import OciSdk, OciSdkError
from app.services.trends import TrendService


JobT = TypeVar("JobT")
ResultT = TypeVar("ResultT")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, value.get(name.replace("_", "-"), default))
    return getattr(value, name, default)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percent_used(allowed: float | None, used: float | None) -> float | None:
    if used is None or allowed is None:
        return None
    if allowed == 0:
        return 100.0 if used > 0 else 0.0
    return max(0.0, min(10_000.0, (used / allowed) * 100.0))


def _is_dynamic_compute_limit_value(service_name: str, value: Any) -> bool:
    raw_value = _field(value, "value")
    return (
        service_name == "compute"
        and isinstance(raw_value, str)
        and raw_value.strip().lower() == "dynamic"
    )


def _is_global_limit_value(value: Any) -> bool:
    return str(_field(value, "scope_type") or "").upper() in {"GLOBAL", "TENANCY"}


def _bounded_futures(
    executor: ThreadPoolExecutor,
    jobs: Iterable[JobT],
    submit: Callable[[ThreadPoolExecutor, JobT], Future[ResultT]],
    *,
    max_pending: int,
) -> Iterator[tuple[JobT, Future[ResultT]]]:
    iterator = iter(jobs)
    pending: dict[Future[ResultT], JobT] = {}

    def fill() -> None:
        while len(pending) < max(1, max_pending):
            try:
                job = next(iterator)
            except StopIteration:
                break
            pending[submit(executor, job)] = job

    fill()
    while pending:
        completed, _ = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            yield pending.pop(future), future
        fill()


class LimitsCollector:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        sdk: OciSdk | None = None,
        *,
        canonical_region: str | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.sdk = sdk or OciSdk(settings)
        self.canonical_region = canonical_region or settings.oci_default_region
        self.alerts = AlertService(db, settings, self.sdk)
        self._limit_item_cache: dict[tuple[str, str, str, str, str | None, str], LimitItem] = {}

    def discover_regions(self) -> list[str]:
        if not self.settings.oci_scan_all_regions:
            return [self.settings.oci_default_region]
        subscriptions = self.sdk.list_region_subscriptions(
            self.settings.oci_tenancy_ocid,
            region=self.settings.oci_default_region,
        )
        regions = [
            _field(item, "region_name")
            for item in subscriptions
            if _field(item, "status") == "READY" and _field(item, "region_name")
        ]
        return regions or [self.settings.oci_default_region]

    def run_scan(
        self,
        region: str | None = None,
        *,
        trigger: str = "manual",
        batch_id: str | None = None,
        attempt: int = 1,
        max_attempts: int = 1,
    ) -> ScanRun:
        target_region = region or self.settings.oci_default_region
        scan = ScanRun(
            region=target_region,
            status="running",
            current_stage="discovering_services",
            trigger=trigger,
            batch_id=batch_id,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        self.db.add(scan)
        self.db.commit()
        self.db.refresh(scan)

        try:
            services = self._list_services(target_region)
            scan.services_discovered = len(services)
            self._upsert_services(target_region, services)
            self.db.commit()

            scan.current_stage = "discovering_limits"
            self._sync_scan_telemetry(scan)
            self.db.commit()
            service_limit_values = self._discover_limit_values(scan, target_region, services)

            scan.current_stage = "collecting_availability"
            scan.current_service = None
            scan.services_scanned = sum(not values for _, values in service_limit_values)
            self._load_limit_item_cache(target_region)
            self.db.commit()

            self._collect_availability(scan, target_region, service_limit_values)

            scan.current_stage = "calculating_trends"
            scan.current_service = None
            self.db.commit()
            TrendService(self.db, self.settings).calculate_recent()
            self.db.commit()
            scan.status = "succeeded"
            scan.current_stage = "succeeded"
        except Exception as exc:
            scan.status = "failed"
            scan.current_stage = "failed"
            scan.error_summary = str(exc)
            self.alerts.upsert_alert(
                alert_type="scan_failed",
                severity="critical",
                title=f"OCI limit scan failed in {target_region}",
                message=str(exc),
                region=target_region,
            )
        finally:
            self._sync_scan_telemetry(scan)
            scan.ended_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(scan)

        return scan

    def run_all_configured_regions(self) -> list[ScanRun]:
        return [self.run_scan(region) for region in self.discover_regions()]

    def _discover_limit_values(
        self, scan: ScanRun, region: str, services: list[Any]
    ) -> list[tuple[str, list[Any]]]:
        service_names = [name for service in services if (name := _field(service, "name"))]
        discovered: list[tuple[str, list[Any]]] = []
        workers = max(1, self.settings.oci_max_service_workers)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="oci-services") as executor:
            futures = _bounded_futures(
                executor,
                service_names,
                lambda pool, name: pool.submit(self._list_limit_values, region, name),
                max_pending=workers * 2,
            )
            for service_name, future in futures:
                scan.current_service = service_name
                try:
                    raw_values = list(future.result())
                    if region == self.canonical_region:
                        values = raw_values
                    else:
                        values = [
                            value for value in raw_values if not _is_global_limit_value(value)
                        ]
                        scan.global_limits_skipped += len(raw_values) - len(values)
                    discovered.append((service_name, values))
                    scan.total_limits_discovered += len(values)
                except OciSdkError as exc:
                    scan.availability_errors += 1
                    self.alerts.upsert_alert(
                        alert_type="service_scan_failed",
                        severity="warning",
                        title=f"OCI service scan failed: {service_name}",
                        message=str(exc),
                        region=region,
                        service_name=service_name,
                    )
                finally:
                    scan.services_scanned += 1
                    if scan.services_scanned % self.settings.oci_db_commit_batch_size == 0:
                        self._sync_scan_telemetry(scan)
                        self.db.commit()
        self._sync_scan_telemetry(scan)
        self.db.commit()
        return discovered

    def _collect_availability(
        self,
        scan: ScanRun,
        region: str,
        service_limit_values: list[tuple[str, list[Any]]],
    ) -> None:
        jobs = (
            (service_name, value)
            for service_name, values in service_limit_values
            for value in values
        )
        expected = {service_name: len(values) for service_name, values in service_limit_values}
        completed: Counter[str] = Counter()
        workers = max(1, self.settings.oci_max_limit_workers)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="oci-limits") as executor:
            futures = _bounded_futures(
                executor,
                jobs,
                lambda pool, job: pool.submit(
                    self._get_availability_for_value,
                    region,
                    job[0],
                    job[1],
                ),
                max_pending=workers * 2,
            )
            for (service_name, value), future in futures:
                scan.current_service = service_name
                availability = future.result()
                self._persist_limit_value(
                    scan,
                    region,
                    service_name,
                    value,
                    availability,
                )
                scan.limits_scanned += 1
                completed[service_name] += 1
                if completed[service_name] == expected[service_name]:
                    scan.services_scanned += 1
                if scan.limits_scanned % self.settings.oci_db_commit_batch_size == 0:
                    self._sync_scan_telemetry(scan)
                    self.db.commit()
        self._sync_scan_telemetry(scan)
        self.db.commit()

    def _sync_scan_telemetry(self, scan: ScanRun) -> None:
        snapshot_method = getattr(self.sdk, "telemetry_snapshot", None)
        if snapshot_method is None:
            return
        telemetry = snapshot_method()
        scan.api_request_count = int(telemetry.get("api_request_count", 0))
        scan.api_retry_count = int(telemetry.get("api_retry_count", 0))
        scan.api_throttle_count = int(telemetry.get("api_throttle_count", 0))
        scan.api_concurrency_wait_seconds = float(
            telemetry.get("api_concurrency_wait_seconds", 0)
        )
        scan.api_retry_sleep_seconds = float(telemetry.get("api_retry_sleep_seconds", 0))

    def _list_services(self, region: str) -> list[Any]:
        return self.sdk.list_services(self.settings.oci_tenancy_ocid, region=region)

    def _list_limit_values(self, region: str, service_name: str) -> list[Any]:
        return self.sdk.list_limit_values(
            self.settings.oci_tenancy_ocid,
            service_name,
            region=region,
        )

    def _upsert_services(self, region: str, services: list[Any]) -> None:
        existing = {
            item.service_name: item
            for item in self.db.scalars(select(OciService).where(OciService.region == region))
        }
        for service in services:
            service_name = _field(service, "name")
            if not service_name:
                continue
            if service_name in existing:
                existing[service_name].description = _field(service, "description")
                existing[service_name].discovered_at = utcnow()
            else:
                self.db.add(
                    OciService(
                        region=region,
                        service_name=service_name,
                        description=_field(service, "description"),
                    )
                )

    def _load_limit_item_cache(self, region: str) -> None:
        items = self.db.scalars(
            select(LimitItem).where(
                LimitItem.region == region,
                LimitItem.compartment_ocid == self.settings.oci_tenancy_ocid,
            )
        )
        self._limit_item_cache = {
            self._limit_identity(
                item.region,
                item.service_name,
                item.limit_name,
                item.scope_type,
                item.availability_domain,
                item.subscription_id,
            ): item
            for item in items
        }

    def _persist_limit_value(
        self,
        scan: ScanRun,
        region: str,
        service_name: str,
        value: Any,
        availability: dict[str, Any],
    ) -> None:
        limit_name = _field(value, "name")
        if not limit_name:
            return

        is_dynamic_compute = _is_dynamic_compute_limit_value(service_name, value)
        scope_type = _field(value, "scope_type") or "UNKNOWN"
        availability_domain = _field(value, "availability_domain")
        allowed_limit = _num(_field(value, "value"))
        limit_item = self._upsert_limit_item(
            region=region,
            service_name=service_name,
            limit_name=limit_name,
            scope_type=scope_type,
            availability_domain=availability_domain,
            allowed_limit=allowed_limit,
        )
        previous_allowed = limit_item.last_allowed_limit

        status = availability["status"]
        data = availability.get("data")
        error_message = availability.get("error")
        effective_quota = _num(_field(data, "effective_quota_value"))
        used = _num(_field(data, "used"))
        available = _num(_field(data, "available"))
        fractional_usage = _num(_field(data, "fractional_usage"))
        fractional_availability = _num(_field(data, "fractional_availability"))
        if is_dynamic_compute:
            normalized_allowed = None
            normalized_effective_quota = None
            normalized_available = None
            normalized_fractional_usage = None
            normalized_fractional_availability = None
        else:
            normalized_allowed = effective_quota if effective_quota is not None else allowed_limit
            normalized_effective_quota = effective_quota
            normalized_available = available
            normalized_fractional_usage = fractional_usage
            normalized_fractional_availability = fractional_availability

        if status == "ok" and used is None and normalized_available is None:
            status = "unsupported"

        percent_used = _percent_used(normalized_allowed, used)
        collected_at = utcnow()
        snapshot = LimitSnapshot(
            id=new_id(),
            limit_item_id=limit_item.id,
            scan_run_id=scan.id,
            collected_at=collected_at,
            allowed_limit=normalized_allowed,
            effective_quota_value=normalized_effective_quota,
            used=used,
            available=normalized_available,
            fractional_usage=normalized_fractional_usage,
            fractional_availability=normalized_fractional_availability,
            percent_used=percent_used,
            collection_status=status,
            raw_json=self.sdk.to_dict(data) or self.sdk.to_dict(value),
            error_message=error_message,
        )
        self.db.add(snapshot)

        limit_item.last_allowed_limit = normalized_allowed
        limit_item.last_used = used
        limit_item.last_available = normalized_available
        limit_item.last_percent_used = percent_used
        limit_item.last_collection_status = status
        limit_item.last_collected_at = collected_at
        limit_item.updated_at = utcnow()

        if status not in {"ok", "unsupported"}:
            scan.availability_errors += 1

        self.alerts.alert_limit_change(limit_item, previous_allowed, normalized_allowed)
        self.alerts.evaluate_snapshot(limit_item, snapshot)

    def _upsert_limit_item(
        self,
        *,
        region: str,
        service_name: str,
        limit_name: str,
        scope_type: str,
        availability_domain: str | None,
        allowed_limit: float | None,
    ) -> LimitItem:
        identity = self._limit_identity(
            region,
            service_name,
            limit_name,
            scope_type,
            availability_domain,
            "",
        )
        existing = self._limit_item_cache.get(identity)
        if existing:
            return existing
        item = LimitItem(
            id=new_id(),
            region=region,
            compartment_ocid=self.settings.oci_tenancy_ocid,
            service_name=service_name,
            limit_name=limit_name,
            resource_name=limit_name,
            scope_type=scope_type,
            availability_domain=availability_domain,
            subscription_id="",
            last_allowed_limit=allowed_limit,
        )
        self.db.add(item)
        self._limit_item_cache[identity] = item
        return item

    @staticmethod
    def _limit_identity(
        region: str,
        service_name: str,
        limit_name: str,
        scope_type: str,
        availability_domain: str | None,
        subscription_id: str,
    ) -> tuple[str, str, str, str, str | None, str]:
        return (
            region,
            service_name,
            limit_name,
            scope_type,
            availability_domain,
            subscription_id,
        )

    def _get_availability_for_value(
        self,
        region: str,
        service_name: str,
        value: Any,
    ) -> dict[str, Any]:
        limit_name = _field(value, "name")
        scope_type = _field(value, "scope_type") or "UNKNOWN"
        availability_domain = _field(value, "availability_domain")
        if not limit_name:
            return {"status": "unsupported", "data": None, "error": "Missing limit name"}
        return self._get_availability(
            region,
            service_name,
            limit_name,
            scope_type,
            availability_domain,
        )

    def _get_availability(
        self,
        region: str,
        service_name: str,
        limit_name: str,
        scope_type: str,
        availability_domain: str | None,
    ) -> dict[str, Any]:
        ad = availability_domain if scope_type == "AD" else None
        try:
            data = self.sdk.get_resource_availability(
                self.settings.oci_tenancy_ocid,
                service_name,
                limit_name,
                region=region,
                availability_domain=ad,
            )
            return {"status": "ok", "data": data}
        except OciSdkError as exc:
            if self.sdk.is_not_found_or_unsupported(exc):
                return {"status": "unsupported", "data": None, "error": str(exc)}
            return {"status": "failed", "data": None, "error": str(exc)}
