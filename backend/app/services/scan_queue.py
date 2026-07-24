from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import AuditLog, ScanRequest, ScanRun, new_id, utcnow
from app.services.collector import LimitsCollector
from app.services.metrics_publish import publish_batch_metrics_if_complete
from app.services.regions import RegionService


ACTIVE_REQUEST_STATUSES = ("queued", "running")


def _retry_delay_seconds(settings: Settings, attempt: int) -> float:
    backoff = min(
        settings.oci_region_retry_max_seconds,
        settings.oci_region_retry_base_seconds * (2 ** (attempt - 1)),
    )
    return (backoff / 2) + random.uniform(0, backoff / 2)


def _record_attempt_result(
    request: ScanRequest,
    settings: Settings,
    *,
    attempt: int,
    succeeded: bool,
    error_summary: str | None,
) -> str:
    now = utcnow()
    request.attempts_completed = attempt
    request.error_summary = error_summary
    if succeeded:
        request.status = "succeeded"
        request.ended_at = now
    elif attempt < request.max_attempts:
        request.status = "queued"
        request.not_before = now + timedelta(
            seconds=_retry_delay_seconds(settings, attempt)
        )
        request.started_at = None
        request.ended_at = None
    else:
        request.status = "failed"
        request.ended_at = now
    return request.status


def enqueue_scan_requests(
    db: Session,
    settings: Settings,
    *,
    trigger: str,
    region_names: list[str] | None = None,
    actor: str = "system",
) -> tuple[str | None, list[ScanRequest], list[str]]:
    region_service = RegionService(db, settings)
    if not region_service.all_regions():
        region_service.sync_subscriptions()
    ready = {item.region_name: item for item in region_service.ready_regions()}
    selected = (
        region_names
        if region_names is not None
        else [item.region_name for item in region_service.enabled_regions()]
    )
    selected = list(dict.fromkeys(selected))
    invalid = [name for name in selected if name not in ready]
    if invalid:
        raise ValueError(f"Regions are not READY subscriptions: {', '.join(invalid)}")

    active_regions = set(
        db.scalars(
            select(ScanRequest.region).where(
                ScanRequest.region.in_(selected),
                ScanRequest.status.in_(ACTIVE_REQUEST_STATUSES),
            )
        )
    )
    queued_names = [name for name in selected if name not in active_regions]
    if not queued_names:
        return None, [], selected

    batch_id = new_id()
    now = utcnow()
    requests: list[ScanRequest] = []
    for index, region_name in enumerate(queued_names):
        item = ScanRequest(
            id=new_id(),
            batch_id=batch_id,
            region=region_name,
            trigger=trigger,
            status="queued",
            requested_at=now,
            not_before=now + timedelta(seconds=index * settings.oci_region_stagger_seconds),
            max_attempts=settings.oci_region_scan_max_attempts,
        )
        db.add(item)
        requests.append(item)

    db.add(
        AuditLog(
            actor=actor,
            action="scan.batch_queued",
            target=batch_id,
            detail={
                "trigger": trigger,
                "regions": queued_names,
                "skipped_regions": sorted(active_regions),
            },
        )
    )
    db.flush()
    return batch_id, requests, sorted(active_regions)


def recover_interrupted_requests(db: Session) -> int:
    interrupted = list(
        db.scalars(select(ScanRequest).where(ScanRequest.status == "running"))
    )
    running_scans = list(db.scalars(select(ScanRun).where(ScanRun.status == "running")))
    scans_by_request = {
        (scan.batch_id, scan.region): scan
        for scan in sorted(running_scans, key=lambda item: item.started_at)
    }
    now = utcnow()
    for request in interrupted:
        interrupted_scan = scans_by_request.get((request.batch_id, request.region))
        request.attempts_completed += 1
        request.last_scan_run_id = interrupted_scan.id if interrupted_scan else None
        request.started_at = None
        if request.attempts_completed < request.max_attempts:
            request.status = "queued"
            request.not_before = now
            request.ended_at = None
            request.error_summary = "Recovered after worker restart."
        else:
            request.status = "failed"
            request.ended_at = now
            request.error_summary = "Maximum attempts reached after worker restart."
    for scan in running_scans:
        scan.status = "failed"
        scan.current_stage = "failed"
        scan.ended_at = now
        scan.error_summary = "Worker restarted during scan."
    db.flush()
    return len(interrupted)


def claim_due_requests(db: Session, limit: int) -> list[ScanRequest]:
    if limit <= 0:
        return []
    now = utcnow()
    query = (
        select(ScanRequest)
        .where(
            ScanRequest.status == "queued",
            ScanRequest.not_before <= now,
        )
        .order_by(ScanRequest.not_before, ScanRequest.requested_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    requests = list(db.scalars(query))
    for request in requests:
        request.status = "running"
        request.started_at = now
        request.ended_at = None
    db.flush()
    return requests


def process_scan_request(request_id: str, settings: Settings) -> str:
    try:
        with SessionLocal() as db:
            request = db.get(ScanRequest, request_id)
            if request is None:
                return "missing"
            region_service = RegionService(db, settings)
            canonical_region = region_service.canonical_region()
            attempt = request.attempts_completed + 1
            scan = LimitsCollector(
                db,
                settings,
                canonical_region=canonical_region,
            ).run_scan(
                request.region,
                trigger=request.trigger,
                batch_id=request.batch_id,
                attempt=attempt,
                max_attempts=request.max_attempts,
            )
            request.last_scan_run_id = scan.id
            status = _record_attempt_result(
                request,
                settings,
                attempt=attempt,
                succeeded=scan.status == "succeeded",
                error_summary=scan.error_summary,
            )
            db.commit()
            publish_batch_metrics_if_complete(
                db,
                settings,
                batch_id=request.batch_id,
                completed_scan=scan,
            )
            return status
    except Exception as exc:
        # A failure outside LimitsCollector must not leave a durable queue row running.
        with SessionLocal() as recovery_db:
            request = recovery_db.get(ScanRequest, request_id)
            if request is None:
                return "missing"
            attempt = request.attempts_completed + 1
            status = _record_attempt_result(
                request,
                settings,
                attempt=attempt,
                succeeded=False,
                error_summary=str(exc),
            )
            recovery_db.commit()
            return status
