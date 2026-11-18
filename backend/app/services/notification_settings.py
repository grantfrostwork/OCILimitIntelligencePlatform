from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import NotificationConfig


def effective_settings(db: Session, settings: Settings) -> Settings:
    config = db.scalar(
        select(NotificationConfig).where(
            NotificationConfig.topic_name == settings.lip_notification_topic_name
        )
    )
    if config is None:
        return settings
    return settings.model_copy(
        update={
            "warning_threshold_percent": config.warning_threshold_percent,
            "critical_threshold_percent": config.critical_threshold_percent,
            "lip_enable_notifications": config.enabled,
            "lip_notification_emails": config.emails,
        }
    )


def get_runtime_settings(
    db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]
) -> Settings:
    return effective_settings(db, settings)
