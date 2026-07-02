from datetime import UTC, datetime

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import ScanRequest, ScanRun
from app.services.metrics_publish import (
    _build_otlp_payload,
    publish_batch_metrics_if_complete,
    publish_metrics_snapshot,
)


def test_prometheus_text_is_converted_to_timestamped_otlp_gauges():
    timestamp = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    payload = _build_otlp_payload(
        '# HELP oci_lip_limit_used Current usage\n'
        '# TYPE oci_lip_limit_used gauge\n'
        'oci_lip_limit_used{region="us-ashburn-1",service="compute"} 17\n',
        timestamp,
        "production",
    )
    request = ExportMetricsServiceRequest.FromString(payload)
    metric = request.resource_metrics[0].scope_metrics[0].metrics[0]
    point = metric.gauge.data_points[0]
    labels = {item.key: item.value.string_value for item in point.attributes}

    assert metric.name == "oci_lip_limit_used"
    assert point.as_double == 17
    assert point.time_unix_nano == int(timestamp.timestamp() * 1_000_000_000)
    assert labels["region"] == "us-ashburn-1"
    assert labels["service"] == "compute"
    assert labels["environment"] == "production"
    assert labels["job"] == "oci-lip-api"


def test_metrics_publication_can_be_explicitly_disabled():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    scan = ScanRun(region="us-ashburn-1", status="succeeded")
    db.add(scan)
    db.commit()

    assert publish_metrics_snapshot(db, Settings(lip_prometheus_otlp_endpoint=None), scan)
    assert scan.metrics_publish_status == "disabled"
    assert scan.metrics_publish_error is None


def test_metrics_publish_once_after_entire_regional_batch_completes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    first_scan = ScanRun(
        region="us-ashburn-1",
        status="succeeded",
        batch_id="batch-1",
    )
    second_scan = ScanRun(
        region="us-phoenix-1",
        status="succeeded",
        batch_id="batch-1",
    )
    first_request = ScanRequest(
        batch_id="batch-1",
        region="us-ashburn-1",
        status="succeeded",
    )
    second_request = ScanRequest(
        batch_id="batch-1",
        region="us-phoenix-1",
        status="running",
    )
    db.add_all([first_scan, second_scan, first_request, second_request])
    db.commit()
    settings = Settings(lip_prometheus_otlp_endpoint=None)

    assert not publish_batch_metrics_if_complete(
        db,
        settings,
        batch_id="batch-1",
        completed_scan=first_scan,
    )
    assert first_scan.metrics_publish_status == "deferred"

    second_request.status = "succeeded"
    db.commit()
    assert publish_batch_metrics_if_complete(
        db,
        settings,
        batch_id="batch-1",
        completed_scan=second_scan,
    )
    db.refresh(first_scan)
    db.refresh(second_scan)
    assert first_scan.metrics_publish_status == "disabled"
    assert second_scan.metrics_publish_status == "disabled"
