from __future__ import annotations

import math
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import Gauge, Metric, NumberDataPoint
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ScanRequest, ScanRun, utcnow
from app.services.metrics import render_metrics


TERMINAL_REQUEST_STATUSES = ("succeeded", "failed")


def publish_batch_metrics_if_complete(
    db: Session,
    settings: Settings,
    *,
    batch_id: str,
    completed_scan: ScanRun,
) -> bool:
    requests = list(
        db.scalars(select(ScanRequest).where(ScanRequest.batch_id == batch_id))
    )
    if any(item.status not in TERMINAL_REQUEST_STATUSES for item in requests):
        completed_scan.metrics_publish_status = "deferred"
        db.commit()
        return False

    scans = list(
        db.scalars(
            select(ScanRun)
            .where(ScanRun.batch_id == batch_id)
            .with_for_update()
        )
    )
    if any(item.metrics_publish_status in {"publishing", "published"} for item in scans):
        return True

    for item in scans:
        item.metrics_publish_status = "publishing"
        item.metrics_publish_error = None
    db.commit()

    published = publish_metrics_snapshot(db, settings, completed_scan)
    final_status = completed_scan.metrics_publish_status
    final_timestamp = completed_scan.metrics_published_at
    final_error = completed_scan.metrics_publish_error
    for item in db.scalars(select(ScanRun).where(ScanRun.batch_id == batch_id)):
        item.metrics_publish_status = final_status
        item.metrics_published_at = final_timestamp
        item.metrics_publish_error = final_error
    db.commit()
    return published


def publish_metrics_snapshot(
    db: Session,
    settings: Settings,
    scan: ScanRun,
) -> bool:
    endpoint = settings.lip_prometheus_otlp_endpoint
    if not endpoint:
        scan.metrics_publish_status = "disabled"
        scan.metrics_publish_error = None
        db.commit()
        return True

    scan.metrics_publish_status = "publishing"
    scan.metrics_publish_error = None
    db.commit()

    try:
        timestamp = scan.ended_at or utcnow()
        payload = _build_otlp_payload(
            render_metrics(db, settings).decode(),
            timestamp,
            settings.environment,
        )
        _post_with_retry(endpoint, payload, settings)
        scan.metrics_publish_status = "published"
        scan.metrics_published_at = utcnow()
        scan.metrics_publish_error = None
        db.commit()
        return True
    except Exception as exc:
        scan.metrics_publish_status = "failed"
        scan.metrics_publish_error = str(exc)
        db.commit()
        return False


def _build_otlp_payload(
    metrics_text: str,
    timestamp: datetime,
    environment: str,
) -> bytes:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp_ns = int(timestamp.timestamp() * 1_000_000_000)
    request = ExportMetricsServiceRequest()
    resource_metrics = request.resource_metrics.add()
    resource_metrics.resource.CopyFrom(
        Resource(
            attributes=[
                KeyValue(key="service.name", value=AnyValue(string_value="oci-lip")),
                KeyValue(
                    key="service.instance.id",
                    value=AnyValue(string_value="oci-lip-worker"),
                ),
            ]
        )
    )
    scope_metrics = resource_metrics.scope_metrics.add()
    scope_metrics.scope.name = "oci-lip-scan-exporter"

    metrics: dict[str, Metric] = {}
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            value = float(sample.value)
            if not math.isfinite(value):
                continue
            metric = metrics.get(sample.name)
            if metric is None:
                metric = Metric(
                    name=sample.name,
                    description=family.documentation or "",
                    gauge=Gauge(),
                )
                metrics[sample.name] = metric
            labels = {
                **sample.labels,
                "environment": environment,
                "instance": "api:8000",
                "job": "oci-lip-api",
            }
            point = NumberDataPoint(
                attributes=[
                    KeyValue(key=key, value=AnyValue(string_value=str(label_value)))
                    for key, label_value in sorted(labels.items())
                ],
                time_unix_nano=timestamp_ns,
                as_double=value,
            )
            metric.gauge.data_points.append(point)

    scope_metrics.metrics.extend(metrics.values())
    return request.SerializeToString()


def _post_with_retry(endpoint: str, payload: bytes, settings: Settings) -> None:
    attempts = max(1, settings.lip_metrics_publish_max_attempts)
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/x-protobuf"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.lip_metrics_publish_timeout_seconds,
            ) as response:
                if 200 <= response.status < 300:
                    return
                raise RuntimeError(f"Prometheus OTLP publish returned HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            if attempt >= attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 8))
