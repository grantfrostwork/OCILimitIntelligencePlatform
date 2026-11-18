import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, require_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import AuditLog, NotificationConfig, utcnow
from app.services.alerts import AlertService
from app.services.message_templates import validate_template
from app.services.oci_sdk import OciSdkError

router = APIRouter(
    prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(require_admin)]
)


class NotificationUpdate(BaseModel):
    enabled: bool
    warning_threshold_percent: float = Field(gt=0, le=100, allow_inf_nan=False)
    critical_threshold_percent: float = Field(gt=0, le=100, allow_inf_nan=False)
    emails: list[str] = Field(max_length=50)
    subject_template: str = Field(min_length=1, max_length=255)
    message_template: str = Field(min_length=1, max_length=10000)

    @field_validator("emails")
    @classmethod
    def valid_emails(cls, emails):
        result = []
        for email in emails:
            email = email.strip().lower()
            if len(email) > 254 or not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", email):
                raise ValueError(f"Invalid email address: {email}")
            if email not in result:
                result.append(email)
        return result

    @field_validator("subject_template", "message_template")
    @classmethod
    def valid_templates(cls, template):
        if not template.strip():
            raise ValueError("Template cannot be blank.")
        return validate_template(template)

    @model_validator(mode="after")
    def valid_settings(self):
        if self.critical_threshold_percent < self.warning_threshold_percent:
            raise ValueError("Critical threshold must be at least the warning threshold.")
        if self.enabled and not self.emails:
            raise ValueError("Add at least one recipient before enabling email alerts.")
        if "\n" in self.subject_template or "\r" in self.subject_template:
            raise ValueError("Email subject must be a single line.")
        return self


class NotificationOut(NotificationUpdate):
    model_config = ConfigDict(from_attributes=True)
    topic_name: str
    topic_id: str | None
    region: str
    subscription_status: dict | None
    last_error: str | None


def config_for(db, settings):
    config = db.scalar(
        select(NotificationConfig).where(
            NotificationConfig.topic_name == settings.lip_notification_topic_name
        )
    )
    if config is None:
        config = NotificationConfig(
            topic_name=settings.lip_notification_topic_name,
            compartment_ocid=settings.lip_notification_compartment_ocid
            or settings.oci_tenancy_ocid,
            region=settings.oci_default_region,
            emails=settings.lip_notification_emails,
            enabled=settings.lip_enable_notifications,
            warning_threshold_percent=settings.warning_threshold_percent,
            critical_threshold_percent=settings.critical_threshold_percent,
        )
        db.add(config)
        db.commit()
    return config


def reconcile(db, settings, config):
    try:
        # Reconcile deletions even when delivery is disabled, then enable additions only when enabled.
        service = AlertService(db, settings)
        if config.topic_id:
            config.subscription_status = service._ensure_subscriptions(
                config.topic_id, config.compartment_ocid, config.region, config.emails
            )
        if config.enabled:
            service.ensure_notification_config()
        config.last_error = None
    except (OciSdkError, ValueError) as exc:
        config.last_error = str(exc)
    config.updated_at = utcnow()
    db.commit()
    db.refresh(config)
    return config


@router.get("", response_model=NotificationOut)
def get_notifications(
    db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]
):
    return config_for(db, settings)


@router.put("", response_model=NotificationOut)
def save_notifications(
    payload: NotificationUpdate,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthUser, Depends(require_admin)],
):
    config = config_for(db, settings)
    thresholds_changed = (config.warning_threshold_percent != payload.warning_threshold_percent or
                          config.critical_threshold_percent != payload.critical_threshold_percent)
    for key, value in payload.model_dump().items():
        setattr(config, key, value)
    config.updated_at = utcnow()
    db.add(
        AuditLog(
            actor=user.email,
            action="notifications.updated",
            target=config.id,
            detail=payload.model_dump(),
        )
    )
    if thresholds_changed:
        from app.services.notification_settings import effective_settings
        from app.services.threshold_updates import refresh_threshold_dependents
        db.flush()
        refresh_threshold_dependents(db, effective_settings(db, settings))
        from app.services.metrics_publish import publish_settings_metrics
        background.add_task(publish_settings_metrics, settings)
    db.commit()
    return reconcile(db, settings, config)


@router.post("/ensure", response_model=NotificationOut)
def ensure_notifications(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthUser, Depends(require_admin)],
):
    config = config_for(db, settings)
    db.add(AuditLog(actor=user.email, action="notifications.synced", target=config.id))
    return reconcile(db, settings, config)
