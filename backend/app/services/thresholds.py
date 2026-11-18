"""One threshold policy shared by alerting, API classification, SQL and metrics."""
from typing import NamedTuple

from sqlalchemy import case

from app.core.config import Settings
from app.models import LimitItem


class Thresholds(NamedTuple):
    warning: float
    critical: float
    source: str


def thresholds_for(settings: Settings, service_name: str | None) -> Thresholds:
    override = settings.service_alert_thresholds.get(service_name or "")
    if override is not None:
        return Thresholds(override["warning"], override["critical"], "service")
    return Thresholds(settings.warning_threshold_percent, settings.critical_threshold_percent, "default")


def threshold_columns(settings: Settings):
    """SQL equivalents keep counts, pagination and exports consistent with row badges."""
    defaults = thresholds_for(settings, None)
    if not settings.service_alert_thresholds:
        return defaults.warning, defaults.critical
    return tuple(
        case({service: values[level] for service, values in settings.service_alert_thresholds.items()},
             value=LimitItem.service_name, else_=default)
        for level, default in (("warning", defaults.warning), ("critical", defaults.critical))
    )
