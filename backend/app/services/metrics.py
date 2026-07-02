from __future__ import annotations

from datetime import UTC, datetime

import oci
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Alert, LimitItem, MonitoredRegion, ScanRequest, ScanRun, ScanSchedule


LIMIT_LABELS = ["region", "service", "limit_name", "scope", "availability_domain"]


def render_metrics(db: Session, settings: Settings) -> bytes:
    registry = CollectorRegistry()
    info = Gauge(
        "oci_lip_exporter_info",
        "Static information about the OCI Limit Intelligence Platform exporter.",
        ["oci_sdk_version"],
        registry=registry,
    )
    info.labels(oci.__version__).set(1)

    total_limits = Gauge(
        "oci_lip_limits_total",
        "Number of OCI limit rows currently known to LIP.",
        registry=registry,
    )
    total_limits.set(db.scalar(select(func.count(LimitItem.id))) or 0)

    warning_threshold = Gauge(
        "oci_lip_warning_threshold_percent",
        "Configured warning threshold percentage.",
        registry=registry,
    )
    warning_threshold.set(settings.warning_threshold_percent)
    critical_threshold = Gauge(
        "oci_lip_critical_threshold_percent",
        "Configured critical threshold percentage.",
        registry=registry,
    )
    critical_threshold.set(settings.critical_threshold_percent)

    allowed = Gauge(
        "oci_lip_limit_allowed",
        "Current allowed value for an OCI service limit.",
        LIMIT_LABELS,
        registry=registry,
    )
    used = Gauge(
        "oci_lip_limit_used",
        "Current OCI-reported usage for a service limit, including usage-only dynamic limits.",
        LIMIT_LABELS,
        registry=registry,
    )
    available = Gauge(
        "oci_lip_limit_available",
        "Current remaining availability for an OCI service limit.",
        LIMIT_LABELS,
        registry=registry,
    )
    percent = Gauge(
        "oci_lip_limit_usage_percent",
        "Current OCI service limit usage as a percentage of the allowed value.",
        LIMIT_LABELS,
        registry=registry,
    )
    ratio = Gauge(
        "oci_lip_limit_usage_ratio",
        "Current OCI service limit usage as a ratio of the allowed value.",
        LIMIT_LABELS,
        registry=registry,
    )
    collected_at = Gauge(
        "oci_lip_limit_last_collected_timestamp_seconds",
        "Unix timestamp of the latest collection for an OCI service limit.",
        LIMIT_LABELS,
        registry=registry,
    )
    collection_status = Gauge(
        "oci_lip_limit_collection_status",
        "Collection status for an OCI service limit; the active status has value 1.",
        [*LIMIT_LABELS, "status"],
        registry=registry,
    )

    for item in db.scalars(select(LimitItem)):
        labels = _limit_labels(item)
        if item.last_allowed_limit is not None:
            allowed.labels(*labels).set(item.last_allowed_limit)
        if item.last_used is not None:
            used.labels(*labels).set(item.last_used)
        if item.last_available is not None:
            available.labels(*labels).set(item.last_available)
        if item.last_percent_used is not None:
            percent.labels(*labels).set(item.last_percent_used)
            ratio.labels(*labels).set(item.last_percent_used / 100.0)
        if item.last_collected_at is not None:
            collected_at.labels(*labels).set(_timestamp(item.last_collected_at))
        collection_status.labels(*labels, item.last_collection_status or "unknown").set(1)

    _render_alert_metrics(db, registry)
    _render_scan_metrics(db, registry)
    return generate_latest(registry)


def render_health_metrics(db: Session) -> bytes:
    registry = CollectorRegistry()
    info = Gauge(
        "oci_lip_exporter_info",
        "Static information about the OCI Limit Intelligence Platform exporter.",
        ["oci_sdk_version"],
        registry=registry,
    )
    info.labels(oci.__version__).set(1)
    _render_schedule_metrics(db, registry)
    return generate_latest(registry)


def _render_alert_metrics(db: Session, registry: CollectorRegistry) -> None:
    open_alerts = Gauge(
        "oci_lip_alerts_open",
        "Number of open LIP alerts by severity.",
        ["severity"],
        registry=registry,
    )
    for severity in ("info", "warning", "critical"):
        open_alerts.labels(severity).set(0)
    for severity, count in db.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.status == "open")
        .group_by(Alert.severity)
    ):
        open_alerts.labels(severity).set(count)


def _render_scan_metrics(db: Session, registry: CollectorRegistry) -> None:
    scans_total = Gauge(
        "oci_lip_scans_total",
        "Number of persisted OCI limit scans by region and status.",
        ["region", "status"],
        registry=registry,
    )
    for region, status, count in db.execute(
        select(ScanRun.region, ScanRun.status, func.count(ScanRun.id)).group_by(
            ScanRun.region, ScanRun.status
        )
    ):
        scans_total.labels(region, status).set(count)

    progress = Gauge(
        "oci_lip_scan_progress_percent",
        "Progress percentage for the latest OCI limit scan in each region.",
        ["region"],
        registry=registry,
    )
    last_started = Gauge(
        "oci_lip_scan_last_started_timestamp_seconds",
        "Unix timestamp when the latest OCI limit scan started.",
        ["region"],
        registry=registry,
    )
    last_success = Gauge(
        "oci_lip_scan_last_success_timestamp_seconds",
        "Unix timestamp when the latest successful OCI limit scan completed.",
        ["region"],
        registry=registry,
    )
    last_duration = Gauge(
        "oci_lip_scan_last_duration_seconds",
        "Duration of the latest completed OCI limit scan.",
        ["region", "status"],
        registry=registry,
    )
    availability_errors = Gauge(
        "oci_lip_scan_last_availability_errors",
        "Availability errors recorded by the latest OCI limit scan.",
        ["region"],
        registry=registry,
    )
    api_requests = Gauge(
        "oci_lip_scan_last_api_requests",
        "OCI SDK requests made by the latest scan in each region.",
        ["region"],
        registry=registry,
    )
    api_retries = Gauge(
        "oci_lip_scan_last_api_retries",
        "OCI SDK retry sleeps observed during the latest scan in each region.",
        ["region"],
        registry=registry,
    )
    api_throttles = Gauge(
        "oci_lip_scan_last_api_throttles",
        "OCI HTTP 429 throttle responses observed during the latest scan in each region.",
        ["region"],
        registry=registry,
    )
    concurrency_wait = Gauge(
        "oci_lip_scan_last_concurrency_wait_seconds",
        "Time spent waiting for the global OCI request concurrency limit in the latest scan.",
        ["region"],
        registry=registry,
    )
    retry_sleep = Gauge(
        "oci_lip_scan_last_retry_sleep_seconds",
        "Time spent in OCI SDK exponential backoff during the latest scan.",
        ["region"],
        registry=registry,
    )
    global_limits_skipped = Gauge(
        "oci_lip_scan_last_global_limits_skipped",
        "Global or tenancy-scoped limits skipped outside the canonical home region.",
        ["region"],
        registry=registry,
    )

    scans = list(db.scalars(select(ScanRun).order_by(ScanRun.started_at.desc())))
    latest_by_region: dict[str, ScanRun] = {}
    latest_success_by_region: dict[str, ScanRun] = {}
    for scan in scans:
        latest_by_region.setdefault(scan.region, scan)
        if scan.status == "succeeded":
            latest_success_by_region.setdefault(scan.region, scan)

    for region, scan in latest_by_region.items():
        progress.labels(region).set(scan.progress_percent)
        last_started.labels(region).set(_timestamp(scan.started_at))
        availability_errors.labels(region).set(scan.availability_errors)
        api_requests.labels(region).set(scan.api_request_count)
        api_retries.labels(region).set(scan.api_retry_count)
        api_throttles.labels(region).set(scan.api_throttle_count)
        concurrency_wait.labels(region).set(scan.api_concurrency_wait_seconds)
        retry_sleep.labels(region).set(scan.api_retry_sleep_seconds)
        global_limits_skipped.labels(region).set(scan.global_limits_skipped)
        if scan.ended_at is not None:
            duration = _timestamp(scan.ended_at) - _timestamp(scan.started_at)
            last_duration.labels(region, scan.status).set(max(0.0, duration))
    for region, scan in latest_success_by_region.items():
        completed_at = scan.ended_at or scan.started_at
        last_success.labels(region).set(_timestamp(completed_at))

    _render_region_metrics(db, registry)


def _render_region_metrics(db: Session, registry: CollectorRegistry) -> None:
    enabled = Gauge(
        "oci_lip_region_enabled",
        "Whether a subscribed OCI region is enabled in the persistent scan allowlist.",
        ["region", "region_key", "home_region", "subscription_status"],
        registry=registry,
    )
    for item in db.scalars(select(MonitoredRegion)):
        enabled.labels(
            item.region_name,
            item.region_key or "",
            str(item.is_home_region).lower(),
            item.subscription_status,
        ).set(1 if item.is_enabled else 0)

    requests = Gauge(
        "oci_lip_scan_requests",
        "Persisted regional scan requests by region, trigger, and queue status.",
        ["region", "trigger", "status"],
        registry=registry,
    )
    for region, trigger, status, count in db.execute(
        select(
            ScanRequest.region,
            ScanRequest.trigger,
            ScanRequest.status,
            func.count(ScanRequest.id),
        ).group_by(ScanRequest.region, ScanRequest.trigger, ScanRequest.status)
    ):
        requests.labels(region, trigger, status).set(count)


def _render_schedule_metrics(db: Session, registry: CollectorRegistry) -> None:
    enabled = Gauge(
        "oci_lip_scan_schedule_enabled",
        "Whether automatic OCI limit scanning is enabled.",
        registry=registry,
    )
    interval = Gauge(
        "oci_lip_scan_schedule_interval_seconds",
        "Configured interval between automatic OCI limit scan batches.",
        registry=registry,
    )
    next_scan = Gauge(
        "oci_lip_scan_schedule_next_timestamp_seconds",
        "Unix timestamp for the next automatic OCI limit scan batch.",
        registry=registry,
    )
    schedule = db.get(ScanSchedule, "default")
    if schedule is None:
        enabled.set(0)
        interval.set(0)
        return
    enabled.set(1 if schedule.is_enabled else 0)
    interval.set(schedule.interval_minutes * 60)
    if schedule.next_scan_at is not None:
        next_scan.set(_timestamp(schedule.next_scan_at))


def _limit_labels(item: LimitItem) -> tuple[str, str, str, str, str]:
    return (
        item.region,
        item.service_name,
        item.limit_name,
        item.scope_type,
        item.availability_domain or "",
    )


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
