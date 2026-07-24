from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuditLog, ScanRequest, ScanRun, ScanSchedule, utcnow


ALLOWED_SCAN_INTERVALS = (10, 30, 240, 1_440, 2_880)
DEFAULT_SCHEDULE_ID = "default"


def get_or_create_schedule(db: Session, settings: Settings) -> ScanSchedule:
    schedule = db.get(ScanSchedule, DEFAULT_SCHEDULE_ID)
    if schedule is not None:
        return schedule

    interval = (
        settings.lip_scan_interval_minutes
        if settings.lip_scan_interval_minutes in ALLOWED_SCAN_INTERVALS
        else 240
    )
    schedule = ScanSchedule(
        id=DEFAULT_SCHEDULE_ID,
        is_enabled=True,
        interval_minutes=interval,
        next_scan_at=_initial_next_scan_at(db, interval),
    )
    db.add(schedule)
    db.flush()
    return schedule


def update_schedule(
    db: Session,
    settings: Settings,
    *,
    is_enabled: bool,
    interval_minutes: int,
    actor: str = "system",
) -> ScanSchedule:
    if interval_minutes not in ALLOWED_SCAN_INTERVALS:
        allowed = ", ".join(str(value) for value in ALLOWED_SCAN_INTERVALS)
        raise ValueError(f"Scan interval must be one of: {allowed} minutes")

    schedule = get_or_create_schedule(db, settings)
    schedule.is_enabled = is_enabled
    schedule.interval_minutes = interval_minutes
    schedule.next_scan_at = (
        utcnow() + timedelta(minutes=interval_minutes) if is_enabled else None
    )
    schedule.updated_at = utcnow()
    db.add(
        AuditLog(
            actor=actor,
            action="scan.schedule_updated",
            target=DEFAULT_SCHEDULE_ID,
            detail={
                "is_enabled": is_enabled,
                "interval_minutes": interval_minutes,
                "next_scan_at": (
                    schedule.next_scan_at.isoformat() if schedule.next_scan_at else None
                ),
            },
        )
    )
    db.flush()
    return schedule


def schedule_is_due(schedule: ScanSchedule, now: datetime | None = None) -> bool:
    if not schedule.is_enabled or schedule.next_scan_at is None:
        return False
    current = now or datetime.now(UTC)
    next_scan = schedule.next_scan_at
    if next_scan.tzinfo is None:
        next_scan = next_scan.replace(tzinfo=UTC)
    return current >= next_scan


def advance_schedule(schedule: ScanSchedule, now: datetime | None = None) -> None:
    current = now or utcnow()
    schedule.last_enqueued_at = current
    schedule.next_scan_at = current + timedelta(minutes=schedule.interval_minutes)
    schedule.updated_at = current


def _initial_next_scan_at(db: Session, interval_minutes: int) -> datetime:
    latest_request = db.scalar(
        select(ScanRequest)
        .where(ScanRequest.trigger == "scheduled")
        .order_by(desc(ScanRequest.requested_at))
        .limit(1)
    )
    if latest_request is not None:
        anchor = latest_request.requested_at
    else:
        latest_scan = db.scalar(
            select(ScanRun).order_by(desc(ScanRun.started_at)).limit(1)
        )
        if latest_scan is None:
            return datetime.now(UTC)
        anchor = latest_scan.started_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return anchor + timedelta(minutes=interval_minutes)
