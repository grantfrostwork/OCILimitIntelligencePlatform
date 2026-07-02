from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import ScanRun
from app.services.schedule import (
    advance_schedule,
    get_or_create_schedule,
    schedule_is_due,
    update_schedule,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_schedule_is_persistent_and_anchors_to_latest_scan():
    db = _db()
    started_at = datetime.now(UTC) - timedelta(hours=1)
    db.add(ScanRun(region="us-ashburn-1", started_at=started_at))
    db.commit()

    schedule = get_or_create_schedule(db, Settings(lip_scan_interval_minutes=240))
    db.commit()

    assert schedule.is_enabled is True
    assert schedule.interval_minutes == 240
    assert schedule.next_scan_at.replace(tzinfo=UTC) == started_at + timedelta(hours=4)
    assert db.get(type(schedule), "default") is not None


def test_schedule_update_validation_due_check_and_advance():
    db = _db()
    settings = Settings()
    now = datetime.now(UTC)

    schedule = update_schedule(
        db,
        settings,
        is_enabled=True,
        interval_minutes=30,
    )
    schedule.next_scan_at = now - timedelta(seconds=1)
    assert schedule_is_due(schedule, now)

    advance_schedule(schedule, now)
    assert schedule.last_enqueued_at == now
    assert schedule.next_scan_at == now + timedelta(minutes=30)

    with pytest.raises(ValueError, match="must be one of"):
        update_schedule(db, settings, is_enabled=True, interval_minutes=60)
