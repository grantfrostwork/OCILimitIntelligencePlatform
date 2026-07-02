from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import Alert, LimitItem, ScanRun
from app.services.metrics import render_metrics


def test_prometheus_metrics_export_limit_and_scan_state():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(UTC)
    db.add(
        LimitItem(
            region="us-ashburn-1",
            compartment_ocid="tenancy",
            service_name="compute",
            limit_name="standard-core-count",
            resource_name="standard-core-count",
            scope_type="AD",
            availability_domain="AD-1",
            subscription_id="",
            last_allowed_limit=100,
            last_used=91,
            last_available=9,
            last_percent_used=91,
            last_collection_status="ok",
            last_collected_at=now,
        )
    )
    db.add(
        LimitItem(
            region="us-ashburn-1",
            compartment_ocid="tenancy",
            service_name="compute",
            limit_name="dynamic-core-count",
            resource_name="dynamic-core-count",
            scope_type="REGION",
            availability_domain=None,
            subscription_id="",
            last_allowed_limit=None,
            last_used=17,
            last_available=None,
            last_percent_used=None,
            last_collection_status="ok",
            last_collected_at=now,
        )
    )
    db.add(
        ScanRun(
            region="us-ashburn-1",
            status="succeeded",
            started_at=now - timedelta(seconds=30),
            ended_at=now,
            limits_scanned=1,
            total_limits_discovered=1,
            current_stage="succeeded",
        )
    )
    db.add(
        Alert(
            fingerprint="warning-compute",
            alert_type="threshold_exceeded",
            severity="warning",
            title="Compute limit near capacity",
            message="91 percent used",
            status="open",
        )
    )
    db.commit()

    output = render_metrics(db, Settings()).decode()

    assert "oci_lip_limit_allowed" in output
    assert 'service="compute"' in output
    assert 'limit_name="standard-core-count"' in output
    assert "oci_lip_limit_usage_percent" in output
    assert " 91.0" in output
    dynamic_used = next(
        line
        for line in output.splitlines()
        if line.startswith("oci_lip_limit_used{") and 'limit_name="dynamic-core-count"' in line
    )
    assert dynamic_used.endswith(" 17.0")
    assert not any(
        line.startswith(("oci_lip_limit_allowed{", "oci_lip_limit_usage_percent{"))
        and 'limit_name="dynamic-core-count"' in line
        for line in output.splitlines()
    )
    assert 'oci_lip_limit_collection_status{' in output
    assert 'status="ok"' in output
    assert 'oci_lip_alerts_open{severity="warning"} 1.0' in output
    assert 'oci_lip_scan_last_success_timestamp_seconds{region="us-ashburn-1"}' in output
