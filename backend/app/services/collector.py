from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import LimitItem, LimitSnapshot, OciService, ScanRun, utcnow
from app.services.alerts import AlertService
from app.services.oci_cli import OciCli, OciCliError
from app.services.trends import TrendService


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


def _is_dynamic_compute_limit_value(service_name: str, value: dict) -> bool:
    raw_value = value.get("value")
    return (
        service_name == "compute"
        and isinstance(raw_value, str)
        and raw_value.strip().lower() == "dynamic"
    )


class LimitsCollector:
    def __init__(self, db: Session, settings: Settings, cli: OciCli | None = None) -> None:
        self.db = db
        self.settings = settings
        self.cli = cli or OciCli(settings)
        self.alerts = AlertService(db, settings, self.cli)

    def discover_regions(self) -> list[str]:
        if not self.settings.oci_scan_all_regions:
            return [self.settings.oci_default_region]
        response = self.cli.run(
            [
                "iam",
                "region-subscription",
                "list",
                "--tenancy-id",
                self.settings.oci_tenancy_ocid,
                "--all",
            ],
            region=self.settings.oci_default_region,
        )
        regions = [
            item["region-name"]
            for item in response.get("data", [])
            if item.get("status") == "READY" and item.get("region-name")
        ]
        return regions or [self.settings.oci_default_region]

    def run_scan(self, region: str | None = None) -> ScanRun:
        target_region = region or self.settings.oci_default_region
        scan = ScanRun(region=target_region, status="running", current_stage="discovering_services")
        self.db.add(scan)
        self.db.commit()
        self.db.refresh(scan)

        try:
            services = self._list_services(target_region)
            scan.services_discovered = len(services)
            self._upsert_services(target_region, services)
            self.db.commit()

            scan.current_stage = "discovering_limits"
            service_limit_values: list[tuple[str, list[dict]]] = []
            for service in services:
                service_name = service.get("name")
                if not service_name:
                    continue
                scan.current_service = service_name
                try:
                    values = self._list_limit_values(target_region, service_name)
                    values = [
                        value
                        for value in values
                        if not _is_dynamic_compute_limit_value(service_name, value)
                    ]
                    service_limit_values.append((service_name, values))
                    scan.total_limits_discovered += len(values)
                except OciCliError as exc:
                    scan.availability_errors += 1
                    self.alerts.upsert_alert(
                        alert_type="service_scan_failed",
                        severity="warning",
                        title=f"OCI service scan failed: {service_name}",
                        message=str(exc),
                        region=target_region,
                        service_name=service_name,
                    )
                finally:
                    scan.services_scanned += 1
                    self.db.commit()

            scan.current_stage = "collecting_availability"
            scan.current_service = None
            scan.services_scanned = 0
            self.db.commit()

            for service_name, values in service_limit_values:
                scan.current_service = service_name
                self.db.commit()
                for value in values:
                    self._collect_limit_value(scan, target_region, service_name, value)
                    scan.limits_scanned += 1
                    self.db.commit()
                scan.services_scanned += 1
                self.db.commit()

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
            scan.ended_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(scan)

        return scan

    def run_all_configured_regions(self) -> list[ScanRun]:
        return [self.run_scan(region) for region in self.discover_regions()]

    def _list_services(self, region: str) -> list[dict]:
        response = self.cli.run(
            [
                "limits",
                "service",
                "list",
                "--compartment-id",
                self.settings.oci_tenancy_ocid,
                "--all",
            ],
            region=region,
        )
        return response.get("data", [])

    def _list_limit_values(self, region: str, service_name: str) -> list[dict]:
        response = self.cli.run(
            [
                "limits",
                "value",
                "list",
                "--compartment-id",
                self.settings.oci_tenancy_ocid,
                "--service-name",
                service_name,
                "--all",
            ],
            region=region,
        )
        return response.get("data", [])

    def _upsert_services(self, region: str, services: list[dict]) -> None:
        for service in services:
            service_name = service.get("name")
            if not service_name:
                continue
            existing = self.db.scalar(
                select(OciService).where(
                    OciService.region == region, OciService.service_name == service_name
                )
            )
            if existing:
                existing.description = service.get("description")
                existing.discovered_at = utcnow()
            else:
                self.db.add(
                    OciService(
                        region=region,
                        service_name=service_name,
                        description=service.get("description"),
                    )
                )

    def _collect_limit_value(self, scan: ScanRun, region: str, service_name: str, value: dict) -> None:
        if _is_dynamic_compute_limit_value(service_name, value):
            return

        limit_name = value.get("name")
        if not limit_name:
            return

        scope_type = value.get("scope-type") or "UNKNOWN"
        availability_domain = value.get("availability-domain")
        allowed_limit = _num(value.get("value"))
        limit_item = self._upsert_limit_item(
            region=region,
            service_name=service_name,
            limit_name=limit_name,
            scope_type=scope_type,
            availability_domain=availability_domain,
            allowed_limit=allowed_limit,
        )
        previous_allowed = limit_item.last_allowed_limit

        availability = self._get_availability(region, service_name, limit_name, scope_type, availability_domain)
        status = availability["status"]
        data = availability["data"]
        error_message = availability.get("error")
        effective_quota = _num(data.get("effective-quota-value")) if data else None
        used = _num(data.get("used")) if data else None
        available = _num(data.get("available")) if data else None
        fractional_usage = _num(data.get("fractional-usage")) if data else None
        fractional_availability = _num(data.get("fractional-availability")) if data else None
        normalized_allowed = effective_quota if effective_quota is not None else allowed_limit

        if status == "ok" and used is None and available is None:
            status = "unsupported"

        percent_used = _percent_used(normalized_allowed, used)
        collected_at = utcnow()
        snapshot = LimitSnapshot(
            limit_item_id=limit_item.id,
            scan_run_id=scan.id,
            collected_at=collected_at,
            allowed_limit=normalized_allowed,
            effective_quota_value=effective_quota,
            used=used,
            available=available,
            fractional_usage=fractional_usage,
            fractional_availability=fractional_availability,
            percent_used=percent_used,
            collection_status=status,
            raw_json=data or value,
            error_message=error_message,
        )
        self.db.add(snapshot)

        limit_item.last_allowed_limit = normalized_allowed
        limit_item.last_used = used
        limit_item.last_available = available
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
        existing = self.db.scalar(
            select(LimitItem).where(
                LimitItem.region == region,
                LimitItem.compartment_ocid == self.settings.oci_tenancy_ocid,
                LimitItem.service_name == service_name,
                LimitItem.limit_name == limit_name,
                LimitItem.scope_type == scope_type,
                LimitItem.availability_domain.is_(availability_domain)
                if availability_domain is None
                else LimitItem.availability_domain == availability_domain,
                LimitItem.subscription_id == "",
            )
        )
        if existing:
            return existing
        item = LimitItem(
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
        self.db.flush()
        return item

    def _get_availability(
        self,
        region: str,
        service_name: str,
        limit_name: str,
        scope_type: str,
        availability_domain: str | None,
    ) -> dict:
        args = [
            "limits",
            "resource-availability",
            "get",
            "--compartment-id",
            self.settings.oci_tenancy_ocid,
            "--service-name",
            service_name,
            "--limit-name",
            limit_name,
        ]
        if scope_type == "AD" and availability_domain:
            args.extend(["--availability-domain", availability_domain])

        try:
            response = self.cli.run(args, region=region)
            return {"status": "ok", "data": response.get("data", {})}
        except OciCliError as exc:
            if self.cli.is_not_found_or_unsupported(exc):
                return {"status": "unsupported", "data": {}, "error": str(exc)}
            return {"status": "failed", "data": {}, "error": str(exc)}
