from __future__ import annotations

import signal
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select

from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.models import ScanRun
from app.services.collector import LimitsCollector


shutdown = False


def _stop(*_args) -> None:
    global shutdown
    shutdown = True


def _seconds_until_next_scan(db, interval_minutes: int) -> int:
    last_scan = db.scalar(select(ScanRun).order_by(desc(ScanRun.started_at)).limit(1))
    if not last_scan:
        return 0
    started_at = last_scan.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    next_scan_at = started_at + timedelta(minutes=interval_minutes)
    return max(0, int((next_scan_at - datetime.now(UTC)).total_seconds()))


def _sleep_interruptibly(seconds: int) -> None:
    for _ in range(seconds):
        if shutdown:
            break
        time.sleep(1)


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    settings = get_settings()
    init_db()
    while not shutdown:
        with SessionLocal() as db:
            wait_seconds = _seconds_until_next_scan(db, settings.lip_scan_interval_minutes)
        if wait_seconds:
            _sleep_interruptibly(wait_seconds)
            continue
        with SessionLocal() as db:
            LimitsCollector(db, settings).run_all_configured_regions()
        _sleep_interruptibly(settings.lip_scan_interval_minutes * 60)


if __name__ == "__main__":
    main()
