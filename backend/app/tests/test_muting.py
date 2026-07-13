from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.limits import _limits_query, criticality, dashboard, limit_to_out
from app.core.config import Settings
from app.core.database import Base
from app.models import Alert, LimitItem, LimitSnapshot
from app.services.alerts import AlertService
from app.services.muting import mute_limit, unmute_limit


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _limit() -> LimitItem:
    now = datetime.now(UTC)
    return LimitItem(
        region="us-ashburn-1",
        compartment_ocid="tenancy",
        service_name="filesystem",
        limit_name="mount-target-count",
        resource_name="mount-target-count",
        scope_type="REGION",
        availability_domain=None,
        subscription_id="",
        last_allowed_limit=2,
        last_used=2,
        last_available=0,
        last_percent_used=100,
        last_collection_status="ok",
        last_collected_at=now,
    )


def test_muted_limit_is_persistent_and_excluded_from_operational_risk():
    db = _database()
    settings = Settings()
    item = _limit()
    db.add(item)
    db.flush()
    alert = Alert(
        fingerprint="mount-target-alert",
        alert_type="threshold_exceeded",
        severity="critical",
        title="Filesystem limit near capacity",
        message="mount-target-count is 100% used",
        status="open",
        region=item.region,
        service_name=item.service_name,
        limit_name=item.limit_name,
        metadata_json={"limit_item_id": item.id},
    )
    db.add(alert)
    db.commit()

    mute_limit(db, item, "Service is intentionally unused")
    db.commit()
    db.expire_all()

    persisted = db.get(LimitItem, item.id)
    assert persisted is not None
    assert persisted.is_muted is True
    assert persisted.muted_at is not None
    assert persisted.mute_reason == "Service is intentionally unused"
    assert db.get(Alert, alert.id).status == "muted"
    assert criticality(persisted, settings) == "muted"
    assert limit_to_out(persisted, settings).is_muted is True

    summary = dashboard(db, settings)
    assert summary.overall_status == "green"
    assert summary.limits_at_capacity == 0
    assert summary.warning_limits == 0
    assert summary.critical_limits == 0
    assert summary.muted_limits == 1
    assert summary.top_usage == []

    near_limit_query = _limits_query(
        db, settings, None, None, None, None, None, True, "all"
    )
    assert list(db.scalars(near_limit_query)) == []


def test_unmuting_restores_latest_current_threshold_alert():
    db = _database()
    settings = Settings()
    item = _limit()
    item.is_muted = True
    item.muted_at = datetime.now(UTC)
    db.add(item)
    db.flush()
    older = Alert(
        fingerprint="older",
        alert_type="threshold_exceeded",
        severity="warning",
        title="Old warning",
        message="Old warning",
        status="muted",
        region=item.region,
        service_name=item.service_name,
        limit_name=item.limit_name,
        metadata_json={"limit_item_id": item.id},
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    latest = Alert(
        fingerprint="latest",
        alert_type="threshold_exceeded",
        severity="critical",
        title="Current critical",
        message="Current critical",
        status="muted",
        region=item.region,
        service_name=item.service_name,
        limit_name=item.limit_name,
        metadata_json={"limit_item_id": item.id},
        last_seen_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    db.add_all([older, latest])
    db.commit()

    unmute_limit(db, item, settings)
    db.commit()

    assert item.is_muted is False
    assert item.muted_at is None
    assert latest.status == "open"
    assert older.status == "closed"
    assert dashboard(db, settings).overall_status == "red"


def test_muted_limit_does_not_generate_new_limit_alerts():
    db = _database()
    item = _limit()
    item.is_muted = True
    db.add(item)
    db.flush()
    snapshot = LimitSnapshot(
        limit_item_id=item.id,
        scan_run_id="scan-not-flushed",
        allowed_limit=2,
        used=2,
        available=0,
        percent_used=100,
        collection_status="ok",
    )

    AlertService(db, Settings(), sdk=object()).evaluate_snapshot(item, snapshot)

    assert db.query(Alert).count() == 0
