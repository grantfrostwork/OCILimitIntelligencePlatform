from __future__ import annotations

from datetime import UTC, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Alert, AlertEvent, LimitItem, LimitSnapshot, NotificationConfig, utcnow
from app.services.oci_sdk import OciSdk, OciSdkError
from app.services.thresholds import thresholds_for


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()


class AlertService:
    def __init__(self, db: Session, settings: Settings, sdk: OciSdk | None = None) -> None:
        self.db = db
        from app.services.notification_settings import effective_settings

        self.settings = effective_settings(db, settings)
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
        identity = (metadata or {}).get("limit_item_id") or (metadata or {})
        fp = _fingerprint([alert_type, severity, region, service_name, limit_name, identity])
        now = utcnow()
        alert = self.db.scalar(select(Alert).where(Alert.fingerprint == fp))
        if alert:
            alert.last_seen_at = now
            alert.occurrences += 1
            alert.message = message
            alert.metadata_json = metadata
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
                dedupe_until=None,
            )
            self.db.add(alert)
            self.db.flush()

        if (
            self.settings.lip_enable_notifications
            and alert_type == "threshold_exceeded"
            and self._should_notify(alert, now)
        ):
            try:
                if self._publish(alert):
                    alert.dedupe_until = now + timedelta(
                        minutes=self.settings.lip_alert_dedupe_minutes
                    )
            except (OciSdkError, ValueError) as exc:
                # Notification failures must never abort collection of limits.
                config = self.db.scalar(
                    select(NotificationConfig).where(
                        NotificationConfig.topic_name == self.settings.lip_notification_topic_name
                    )
                )
                if config:
                    config.last_error = str(exc)
                self.db.add(
                    AlertEvent(
                        alert_id=alert.id,
                        message=alert.message,
                        delivery_status="failed",
                        raw_response={"error": str(exc)},
                    )
                )

        return alert

    def evaluate_snapshot(self, limit_item: LimitItem, snapshot: LimitSnapshot) -> None:
        # A scan caches LimitItem objects; read the persisted flag independently so a
        # mute saved by the API takes effect during an already-running scan.
        if limit_item.is_muted or self.db.scalar(
            select(LimitItem.is_muted).where(LimitItem.id == limit_item.id)
        ):
            return

        if snapshot.collection_status not in {"ok", "unsupported"}:
            self.upsert_alert(
                alert_type="collection_failed",
                severity="warning",
                title=f"OCI limit collection failed for {limit_item.service_name}",
                message=snapshot.error_message or "OCI SDK collection failed.",
                region=limit_item.region,
                service_name=limit_item.service_name,
                limit_name=limit_item.limit_name,
                metadata={"snapshot_id": snapshot.id, "limit_item_id": limit_item.id},
            )
            return

        if snapshot.percent_used is None:
            return

        thresholds = thresholds_for(self.settings, limit_item.service_name)
        if snapshot.percent_used >= thresholds.critical:
            severity = "critical"
        elif snapshot.percent_used >= thresholds.warning:
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
                "warning_threshold_percent": thresholds.warning,
                "critical_threshold_percent": thresholds.critical,
                "threshold_source": thresholds.source,
                "used": snapshot.used,
                "allowed_limit": snapshot.allowed_limit,
                "scope_type": limit_item.scope_type,
                "availability_domain": limit_item.availability_domain,
            },
        )

    def alert_limit_change(
        self, limit_item: LimitItem, previous_allowed: float | None, current_allowed: float | None
    ) -> None:
        # A scan caches LimitItem objects; read the persisted flag independently so a
        # mute saved by the API takes effect during an already-running scan.
        if limit_item.is_muted or self.db.scalar(
            select(LimitItem.is_muted).where(LimitItem.id == limit_item.id)
        ):
            return
        if (
            previous_allowed is None
            or current_allowed is None
            or previous_allowed == current_allowed
        ):
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
        until = alert.dedupe_until
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return until is None or until <= now

    def _delivery_is_muted(self, alert: Alert) -> bool:
        item_id = (alert.metadata_json or {}).get("limit_item_id")
        muted = alert.status == "muted" or bool(
            item_id and self.db.scalar(select(LimitItem.is_muted).where(LimitItem.id == item_id))
        )
        if muted:
            alert.status = "muted"
        return muted

    def _publish(self, alert: Alert) -> bool:
        if self._delivery_is_muted(alert):
            return False
        config = self.ensure_notification_config()
        if not config.topic_id:
            return False
        # Do not publish until the topic's subscriptions match the saved recipient list.
        from app.services.message_templates import render_message

        title, body = render_message(config, alert, self.settings)
        # Subscription reconciliation makes network calls; a mute may have arrived
        # while those calls were in progress. Check again at the delivery boundary.
        if self._delivery_is_muted(alert):
            return False
        event = AlertEvent(alert_id=alert.id, message=body, delivery_status="pending")
        self.db.add(event)
        try:
            response = self.sdk.publish_message(
                config.topic_id,
                title,
                body[:60_000],
                region=config.region,
            )
            event.delivery_status = "sent"
            event.raw_response = self.sdk.to_dict(response)
            return True
        except OciSdkError as exc:
            event.delivery_status = "failed"
            event.raw_response = {"error": str(exc)}
            config.last_error = str(exc)
            return False

    def ensure_notification_config(self) -> NotificationConfig:
        topic_name = self.settings.lip_notification_topic_name
        compartment_id = (
            self.settings.lip_notification_compartment_ocid or self.settings.oci_tenancy_ocid
        )
        region = self.settings.oci_default_region
        config = self.db.scalar(
            select(NotificationConfig).where(NotificationConfig.topic_name == topic_name)
        )
        if not config:
            config = NotificationConfig(
                topic_name=topic_name,
                compartment_ocid=compartment_id,
                region=region,
                emails=self.settings.lip_notification_emails,
                enabled=self.settings.lip_enable_notifications,
                warning_threshold_percent=self.settings.warning_threshold_percent,
                critical_threshold_percent=self.settings.critical_threshold_percent,
            )
            self.db.add(config)
            self.db.flush()

        if not config.enabled:
            return config
        if not config.emails:
            raise ValueError("Add at least one email recipient before enabling notifications.")

        compartment_id, region = config.compartment_ocid, config.region
        topic = self._find_or_create_topic(topic_name, compartment_id, region)
        config.topic_id = topic.topic_id
        config.updated_at = utcnow()
        config.subscription_status = self._ensure_subscriptions(
            config.topic_id, compartment_id, region, config.emails
        )
        config.last_error = None
        self.db.flush()
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
        # This topic is dedicated to LIP. Removing a saved email must revoke its subscription.
        for item in existing:
            if (
                getattr(item, "protocol", "EMAIL") == "EMAIL"
                and (item.endpoint or "").lower() not in emails
                and item.lifecycle_state != "DELETED"
            ):
                self.sdk.delete_subscription(item.id, region=region)
        endpoints = {
            (item.endpoint or "").lower(): item.lifecycle_state or "UNKNOWN"
            for item in existing
            if item.lifecycle_state != "DELETED"
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
