from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import MonitoredRegion
from app.services.scan_queue import enqueue_scan_requests


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
