from string import Formatter

FIELDS = {
    "service",
    "limit",
    "region",
    "percent_used",
    "used",
    "allowed_limit",
    "severity",
    "threshold",
    "message",
    "app_url",
}


def validate_template(template: str) -> str:
    try:
        for _, field, spec, conversion in Formatter().parse(template):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise ValueError(
                    "Use only the listed placeholders, without formatting or attribute access."
                )
    except ValueError as exc:
        raise ValueError(f"Invalid message template: {exc}") from exc
    return template


def render_message(config, alert, settings):
    metadata = alert.metadata_json or {}
    values = {
        "service": alert.service_name or "unknown",
        "limit": alert.limit_name or "unknown",
        "region": alert.region or "unknown",
        "severity": alert.severity.upper(),
        "percent_used": f"{metadata.get('percent_used', 0):.1f}",
        "used": f"{metadata.get('used', 0):g}",
        "allowed_limit": f"{metadata.get('allowed_limit', 0):g}",
        "threshold": f"{(config.critical_threshold_percent if alert.severity == 'critical' else config.warning_threshold_percent):g}",
        "message": alert.message,
        "app_url": settings.auth_public_url,
    }
    title = (
        validate_template(config.subject_template)
        .format_map(values)
        .replace("\r", " ")
        .replace("\n", " ")[:255]
    )
    body = validate_template(config.message_template).format_map(values)
    return title, body
