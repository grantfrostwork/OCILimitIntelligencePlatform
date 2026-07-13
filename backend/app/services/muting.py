from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Alert, LimitItem, utcnow


def mute_limit(db: Session, limit_item: LimitItem, reason: str | None = None) -> None:
    limit_item.is_muted = True
    limit_item.muted_at = utcnow()
    limit_item.mute_reason = reason.strip() if reason and reason.strip() else None
    for alert in _alerts_for_limit(db, limit_item):
        alert.status = "muted"


def unmute_limit(db: Session, limit_item: LimitItem, settings: Settings) -> None:
    limit_item.is_muted = False
    limit_item.muted_at = None
    limit_item.mute_reason = None

    threshold_alert_restored = False
    is_near_limit = (
        limit_item.last_percent_used is not None
        and limit_item.last_percent_used >= settings.warning_threshold_percent
    )
    for alert in _alerts_for_limit(db, limit_item):
        if alert.alert_type == "threshold_exceeded" and is_near_limit and not threshold_alert_restored:
            alert.status = "open"
            threshold_alert_restored = True
        else:
            alert.status = "closed"


def _alerts_for_limit(db: Session, limit_item: LimitItem) -> list[Alert]:
    candidates = db.scalars(
        select(Alert)
        .where(
            Alert.region == limit_item.region,
            Alert.service_name == limit_item.service_name,
            Alert.limit_name == limit_item.limit_name,
        )
        .order_by(desc(Alert.last_seen_at))
    )
    return [
        alert
        for alert in candidates
        if (alert.metadata_json or {}).get("limit_item_id") == limit_item.id
    ]
