from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    region: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_stage: Mapped[str] = mapped_column(String(64), default="queued", index=True)
    current_service: Mapped[str | None] = mapped_column(String(128))
    services_discovered: Mapped[int] = mapped_column(Integer, default=0)
    services_scanned: Mapped[int] = mapped_column(Integer, default=0)
    total_limits_discovered: Mapped[int] = mapped_column(Integer, default=0)
    limits_scanned: Mapped[int] = mapped_column(Integer, default=0)
    availability_errors: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled", index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    api_request_count: Mapped[int] = mapped_column(Integer, default=0)
    api_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    api_throttle_count: Mapped[int] = mapped_column(Integer, default=0)
    api_concurrency_wait_seconds: Mapped[float] = mapped_column(Float, default=0)
    api_retry_sleep_seconds: Mapped[float] = mapped_column(Float, default=0)
    global_limits_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)

    snapshots: Mapped[list["LimitSnapshot"]] = relationship(back_populates="scan_run")

    @property
    def progress_percent(self) -> float:
        if self.status == "succeeded":
            return 100.0
        if self.status == "failed":
            return 100.0
        if self.current_stage == "discovering_services":
            return 2.0
        if self.current_stage == "discovering_limits":
            if self.services_discovered:
                return min(20.0, max(3.0, (self.services_scanned / self.services_discovered) * 20.0))
            return 3.0
        if self.total_limits_discovered:
            return min(99.0, max(20.0, (self.limits_scanned / self.total_limits_discovered) * 100.0))
        if self.current_stage == "calculating_trends":
            return 98.0
        return 0.0


class MonitoredRegion(Base):
    __tablename__ = "monitored_regions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    region_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    region_key: Mapped[str | None] = mapped_column(String(16))
    subscription_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    is_home_region: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    stagger_order: Mapped[int] = mapped_column(Integer, default=0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanRequest(Base):
    __tablename__ = "scan_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    region: Mapped[str] = mapped_column(String(64), index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts_completed: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_scan_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    error_summary: Mapped[str | None] = mapped_column(Text)


class OciService(Base):
    __tablename__ = "oci_services"
    __table_args__ = (UniqueConstraint("region", "service_name", name="uq_oci_service_region_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    region: Mapped[str] = mapped_column(String(64), index=True)
    service_name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LimitItem(Base):
    __tablename__ = "limit_items"
    __table_args__ = (
        UniqueConstraint(
            "region",
            "compartment_ocid",
            "service_name",
            "limit_name",
            "scope_type",
            "availability_domain",
            "subscription_id",
            name="uq_limit_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    region: Mapped[str] = mapped_column(String(64), index=True)
    compartment_ocid: Mapped[str] = mapped_column(String(255), index=True)
    service_name: Mapped[str] = mapped_column(String(128), index=True)
    limit_name: Mapped[str] = mapped_column(String(255), index=True)
    resource_name: Mapped[str | None] = mapped_column(String(255))
    scope_type: Mapped[str] = mapped_column(String(32), index=True)
    availability_domain: Mapped[str | None] = mapped_column(String(128), index=True)
    subscription_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    last_allowed_limit: Mapped[float | None] = mapped_column(Float)
    last_used: Mapped[float | None] = mapped_column(Float)
    last_available: Mapped[float | None] = mapped_column(Float)
    last_percent_used: Mapped[float | None] = mapped_column(Float, index=True)
    last_collection_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshots: Mapped[list["LimitSnapshot"]] = relationship(back_populates="limit_item")
    predictions: Mapped[list["TrendPrediction"]] = relationship(back_populates="limit_item")


class LimitSnapshot(Base):
    __tablename__ = "limit_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    limit_item_id: Mapped[str] = mapped_column(ForeignKey("limit_items.id"), index=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    allowed_limit: Mapped[float | None] = mapped_column(Float)
    effective_quota_value: Mapped[float | None] = mapped_column(Float)
    used: Mapped[float | None] = mapped_column(Float)
    available: Mapped[float | None] = mapped_column(Float)
    fractional_usage: Mapped[float | None] = mapped_column(Float)
    fractional_availability: Mapped[float | None] = mapped_column(Float)
    percent_used: Mapped[float | None] = mapped_column(Float, index=True)
    collection_status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    limit_item: Mapped[LimitItem] = relationship(back_populates="snapshots")
    scan_run: Mapped[ScanRun] = relationship(back_populates="snapshots")


class TrendPrediction(Base):
    __tablename__ = "trend_predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    limit_item_id: Mapped[str] = mapped_column(ForeignKey("limit_items.id"), index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lookback_hours: Mapped[int] = mapped_column(Integer)
    slope_used_per_day: Mapped[float | None] = mapped_column(Float)
    projected_breach_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    eta_days_to_warning: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    summary: Mapped[str | None] = mapped_column(Text)

    limit_item: Mapped[LimitItem] = relationship(back_populates="predictions")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_alert_fingerprint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    service_name: Mapped[str | None] = mapped_column(String(128), index=True)
    limit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dedupe_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    events: Mapped[list["AlertEvent"]] = relationship(back_populates="alert")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending")
    message: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[dict | None] = mapped_column(JSON)

    alert: Mapped[Alert] = relationship(back_populates="events")


class NotificationConfig(Base):
    __tablename__ = "notification_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_name: Mapped[str] = mapped_column(String(255), unique=True)
    topic_id: Mapped[str | None] = mapped_column(String(255))
    compartment_ocid: Mapped[str] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(64))
    emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    subscription_status: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BomDocument(Base):
    __tablename__ = "bom_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_text_preview: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["BomItem"]] = relationship(back_populates="document")
    recommendations: Mapped[list["BomRecommendation"]] = relationship(back_populates="document")


class BomItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("bom_documents.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64), default="count")
    region: Mapped[str | None] = mapped_column(String(64))
    service_name: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[list[str] | None] = mapped_column(JSON)

    document: Mapped[BomDocument] = relationship(back_populates="items")


class BomRecommendation(Base):
    __tablename__ = "bom_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("bom_documents.id"), index=True)
    bom_item_id: Mapped[str | None] = mapped_column(ForeignKey("bom_items.id"), index=True)
    limit_item_id: Mapped[str | None] = mapped_column(ForeignKey("limit_items.id"), index=True)
    matching_service: Mapped[str | None] = mapped_column(String(128))
    matching_limit_name: Mapped[str | None] = mapped_column(String(255))
    current_usage: Mapped[float | None] = mapped_column(Float)
    allowed_limit: Mapped[float | None] = mapped_column(Float)
    available_capacity: Mapped[float | None] = mapped_column(Float)
    required_quantity: Mapped[float] = mapped_column(Float)
    limit_increase_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    recommended_new_limit: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    explanation: Mapped[str] = mapped_column(Text)
    assumptions: Mapped[list[str] | None] = mapped_column(JSON)

    document: Mapped[BomDocument] = relationship(back_populates="recommendations")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="system")
    action: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict | None] = mapped_column(JSON)
