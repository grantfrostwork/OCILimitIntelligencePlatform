from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Alert, AlertEvent, LimitItem, LimitSnapshot, NotificationConfig, utcnow
from app.services.oci_sdk import OciSdk, OciSdkError


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()


class AlertService:
    def __init__(self, db: Session, settings: Settings, sdk: OciSdk | None = None) -> None:
        self.db = db
        self.settings = settings
        self.sdk = sdk or OciSdk(settings)

    def upsert_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        region: str | None = None,
        service_name: str | None = None,
        limit_name: str | None = None,
        metadata: dict | None = None,
    ) -> Alert:
        fp = _fingerprint([alert_type, severity, region, service_name, limit_name, metadata or {}])
        now = utcnow()
        alert = self.db.scalar(select(Alert).where(Alert.fingerprint == fp))
        if alert:
            alert.last_seen_at = now
            alert.occurrences += 1
            alert.message = message
            alert.status = "open"
        else:
            alert = Alert(
                fingerprint=fp,
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                region=region,
                service_name=service_name,
                limit_name=limit_name,
                metadata_json=metadata,
                dedupe_until=now + timedelta(minutes=self.settings.lip_alert_dedupe_minutes),
            )
            self.db.add(alert)
            self.db.flush()

        if self.settings.lip_enable_notifications and self._should_notify(alert, now):
            self._publish(alert)
            alert.dedupe_until = now + timedelta(minutes=self.settings.lip_alert_dedupe_minutes)

        return alert

    def evaluate_snapshot(self, limit_item: LimitItem, snapshot: LimitSnapshot) -> None:
        if snapshot.collection_status not in {"ok", "unsupported"}:
            self.upsert_alert(
                alert_type="collection_failed",
                severity="warning",
                title=f"OCI limit collection failed for {limit_item.service_name}",
                message=snapshot.error_message or "OCI SDK collection failed.",
                region=limit_item.region,
                service_name=limit_item.service_name,
                limit_name=limit_item.limit_name,
                metadata={"snapshot_id": snapshot.id},
            )
            return

        if snapshot.percent_used is None:
            return

        if snapshot.percent_used >= self.settings.critical_threshold_percent:
            severity = "critical"
        elif snapshot.percent_used >= self.settings.warning_threshold_percent:
            severity = "warning"
        else:
            return

        self.upsert_alert(
            alert_type="threshold_exceeded",
            severity=severity,
            title=f"{limit_item.service_name} limit near capacity",
            message=(
                f"{limit_item.limit_name} in {limit_item.region} is "
                f"{snapshot.percent_used:.1f}% used "
                f"({snapshot.used:g} of {snapshot.allowed_limit:g})."
            ),
            region=limit_item.region,
            service_name=limit_item.service_name,
            limit_name=limit_item.limit_name,
            metadata={
                "limit_item_id": limit_item.id,
                "percent_used": snapshot.percent_used,
                "scope_type": limit_item.scope_type,
                "availability_domain": limit_item.availability_domain,
            },
        )

    def alert_limit_change(
        self, limit_item: LimitItem, previous_allowed: float | None, current_allowed: float | None
    ) -> None:
        if previous_allowed is None or current_allowed is None or previous_allowed == current_allowed:
            return
        self.upsert_alert(
            alert_type="limit_value_changed",
            severity="info",
            title=f"OCI limit changed: {limit_item.limit_name}",
            message=(
                f"{limit_item.service_name}/{limit_item.limit_name} changed from "
                f"{previous_allowed:g} to {current_allowed:g} in {limit_item.region}."
            ),
            region=limit_item.region,
            service_name=limit_item.service_name,
            limit_name=limit_item.limit_name,
            metadata={
                "previous_allowed_limit": previous_allowed,
                "current_allowed_limit": current_allowed,
                "limit_item_id": limit_item.id,
            },
        )

    def _should_notify(self, alert: Alert, now) -> bool:
        return alert.dedupe_until is None or alert.dedupe_until <= now or alert.occurrences == 1

    def _publish(self, alert: Alert) -> None:
        config = self.ensure_notification_config()
        if not config.topic_id:
            return
        body = f"{alert.severity.upper()}: {alert.message}"
        event = AlertEvent(alert_id=alert.id, message=body, delivery_status="pending")
        self.db.add(event)
        try:
            response = self.sdk.publish_message(
                config.topic_id,
                alert.title[:255],
                body[:60_000],
                region=config.region,
            )
            event.delivery_status = "sent"
            event.raw_response = self.sdk.to_dict(response)
        except OciSdkError as exc:
            event.delivery_status = "failed"
            event.raw_response = {"error": str(exc)}

    def ensure_notification_config(self) -> NotificationConfig:
        topic_name = self.settings.lip_notification_topic_name
        compartment_id = self.settings.lip_notification_compartment_ocid or self.settings.oci_tenancy_ocid
        region = self.settings.oci_default_region
        config = self.db.scalar(select(NotificationConfig).where(NotificationConfig.topic_name == topic_name))
        if not config:
            config = NotificationConfig(
                topic_name=topic_name,
                compartment_ocid=compartment_id,
                region=region,
                emails=self.settings.lip_notification_emails,
            )
            self.db.add(config)
            self.db.flush()

        if not self.settings.lip_enable_notifications:
            return config

        topic = self._find_or_create_topic(topic_name, compartment_id, region)
        config.topic_id = topic.topic_id
        config.updated_at = utcnow()
        config.subscription_status = self._ensure_subscriptions(
            config.topic_id, compartment_id, region, self.settings.lip_notification_emails
        )
        return config

    def _find_or_create_topic(self, name: str, compartment_id: str, region: str) -> Any:
        topics = self.sdk.list_topics(compartment_id, region=region, name=name)
        for topic in topics:
            if topic.name == name and topic.lifecycle_state != "DELETED":
                return topic
        return self.sdk.create_topic(
            compartment_id,
            name,
            "OCI Limit Intelligence Platform alerts",
            region=region,
        )

    def _ensure_subscriptions(
        self, topic_id: str | None, compartment_id: str, region: str, emails: list[str]
    ) -> dict:
        if not topic_id:
            return {"error": "missing topic id"}
        result: dict[str, str] = {}
        existing = self.sdk.list_subscriptions(compartment_id, topic_id, region=region)
        endpoints = {
            (item.endpoint or "").lower(): item.lifecycle_state or "UNKNOWN"
            for item in existing
        }
        for email in emails:
            if endpoints.get(email.lower()):
                result[email] = endpoints[email.lower()]
                continue
            subscription = self.sdk.create_subscription(
                compartment_id,
                topic_id,
                email,
                region=region,
            )
            result[email] = subscription.lifecycle_state or "PENDING"
        return result
