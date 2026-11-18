"""Refresh derived state after a threshold edit, without sending notifications."""
from sqlalchemy import select

from app.models import Alert, LimitItem
from app.services.thresholds import thresholds_for
from app.services.trends import TrendService


def refresh_threshold_dependents(db, settings, service_name=None):
    query = select(LimitItem)
    if service_name is not None:
        query = query.where(LimitItem.service_name == service_name)
    items = {item.id: item for item in db.scalars(query)}
    alerts = select(Alert).where(Alert.alert_type == "threshold_exceeded", Alert.status == "open")
    if service_name is not None:
        alerts = alerts.where(Alert.service_name == service_name)
    for alert in db.scalars(alerts):
        item = items.get((alert.metadata_json or {}).get("limit_item_id"))
        if item is None:
            continue
        thresholds = thresholds_for(settings, item.service_name)
        percent = item.last_percent_used
        severity = ("critical" if percent is not None and percent >= thresholds.critical else
                    "warning" if percent is not None and percent >= thresholds.warning else None)
        if item.is_muted or severity != alert.severity:
            alert.status = "muted" if item.is_muted else "closed"
    # Forecasts use the new warning point immediately. No email is sent on settings save.
    trends = TrendService(db, settings)
    for item in items.values():
        trends.calculate_for_limit(item)
