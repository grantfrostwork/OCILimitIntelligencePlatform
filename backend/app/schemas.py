from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScanRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    region: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    current_stage: str
    current_service: str | None
    services_discovered: int
    services_scanned: int
    total_limits_discovered: int
    limits_scanned: int
    availability_errors: int
    trigger: str
    batch_id: str | None
    attempt: int
    max_attempts: int
    api_request_count: int
    api_retry_count: int
    api_throttle_count: int
    api_concurrency_wait_seconds: float
    api_retry_sleep_seconds: float
    global_limits_skipped: int
    progress_percent: float
    error_summary: str | None


class RegionAllowlistUpdate(BaseModel):
    regions: list[str] = Field(min_length=1)


class RegionOut(BaseModel):
    region_name: str
    region_key: str | None
    subscription_status: str
    is_home_region: bool
    is_enabled: bool
    stagger_order: int
    latest_scan: ScanRunOut | None
    request_status: str | None
    request_id: str | None
    next_attempt_at: datetime | None


class ScanRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str
    region: str
    trigger: str
    status: str
    requested_at: datetime
    not_before: datetime
    started_at: datetime | None
    ended_at: datetime | None
    attempts_completed: int
    max_attempts: int
    last_scan_run_id: str | None
    error_summary: str | None


class ScanEnqueueOut(BaseModel):
    status: str
    batch_id: str | None
    regions: list[str]
    queued_regions: list[str]
    skipped_regions: list[str]


class LimitItemOut(BaseModel):
    id: str
    region: str
    service_name: str
    limit_name: str
    resource_name: str | None
    scope_type: str
    availability_domain: str | None
    compartment_ocid: str
    last_allowed_limit: float | None
    last_used: float | None
    last_available: float | None
    last_percent_used: float | None
    last_collection_status: str
    last_collected_at: datetime | None
    criticality: str


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_type: str
    severity: str
    title: str
    message: str
    status: str
    service_name: str | None
    limit_name: str | None
    region: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int


class DashboardOut(BaseModel):
    overall_status: str
    status_reason: str
    limits_at_capacity: int
    limits_near_capacity: int
    total_limits_scanned: int
    warning_limits: int
    critical_limits: int
    services_near_capacity: list[dict]
    top_usage: list[dict]
    recent_trends: list[dict]
    last_scan: ScanRunOut | None


class BomItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource_type: str
    display_name: str
    quantity: float
    unit: str
    region: str | None
    service_name: str | None
    confidence: str
    assumptions: list[str] | None


class BomRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matching_service: str | None
    matching_limit_name: str | None
    current_usage: float | None
    allowed_limit: float | None
    available_capacity: float | None
    required_quantity: float
    limit_increase_needed: bool
    recommended_new_limit: float | None
    confidence: str
    explanation: str
    assumptions: list[str] | None


class BomDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str | None
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    items: list[BomItemOut] = []
    recommendations: list[BomRecommendationOut] = []
