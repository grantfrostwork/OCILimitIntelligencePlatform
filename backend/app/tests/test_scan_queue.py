from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import MonitoredRegion, ScanRequest, ScanRun, utcnow
from app.services.scan_queue import enqueue_scan_requests, recover_interrupted_requests


def test_queue_staggers_regions_and_deduplicates_active_requests():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add_all(
        [
            MonitoredRegion(
                region_name="us-ashburn-1",
                region_key="IAD",
                subscription_status="READY",
                is_home_region=True,
                is_enabled=True,
                stagger_order=0,
            ),
            MonitoredRegion(
                region_name="us-phoenix-1",
                region_key="PHX",
                subscription_status="READY",
                is_enabled=True,
                stagger_order=1,
            ),
        ]
    )
    db.commit()
    settings = Settings(oci_region_stagger_seconds=20)

    batch_id, requests, skipped = enqueue_scan_requests(
        db,
        settings,
        trigger="manual",
    )

    assert batch_id
    assert skipped == []
    assert [item.region for item in requests] == ["us-ashburn-1", "us-phoenix-1"]
    assert requests[1].not_before - requests[0].not_before == timedelta(seconds=20)

    second_batch, second_requests, second_skipped = enqueue_scan_requests(
        db,
        settings,
        trigger="manual",
    )
    assert second_batch is None
    assert second_requests == []
    assert second_skipped == ["us-ashburn-1", "us-phoenix-1"]


def test_recovery_counts_interrupted_attempt_and_links_failed_scan():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    now = utcnow()
    request = ScanRequest(
        batch_id="batch-1",
        region="us-ashburn-1",
        trigger="manual",
        status="running",
        requested_at=now,
        not_before=now,
        attempts_completed=0,
        max_attempts=3,
    )
    scan = ScanRun(
        region="us-ashburn-1",
        status="running",
        trigger="manual",
        batch_id="batch-1",
        attempt=1,
        max_attempts=3,
    )
    db.add_all([request, scan])
    db.commit()

    assert recover_interrupted_requests(db) == 1
    db.commit()

    assert request.status == "queued"
    assert request.attempts_completed == 1
    assert request.last_scan_run_id == scan.id
    assert request.error_summary == "Recovered after worker restart."
    assert scan.status == "failed"
    assert scan.error_summary == "Worker restarted during scan."


def test_recovery_stops_after_maximum_attempts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    now = utcnow()
    request = ScanRequest(
        batch_id="batch-2",
        region="us-phoenix-1",
        trigger="manual",
        status="running",
        requested_at=now,
        not_before=now,
        attempts_completed=2,
        max_attempts=3,
    )
    db.add(request)
    db.commit()

    assert recover_interrupted_requests(db) == 1
    db.commit()

    assert request.status == "failed"
    assert request.attempts_completed == 3
    assert request.ended_at is not None
    assert request.error_summary == "Maximum attempts reached after worker restart."
