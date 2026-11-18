from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, require_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import AuditLog, LimitItem, ServiceAlertThreshold, utcnow
from app.services.metrics_publish import publish_settings_metrics
from app.services.notification_settings import effective_settings
from app.services.threshold_updates import refresh_threshold_dependents

router = APIRouter(prefix="/api/service-thresholds", tags=["service thresholds"], dependencies=[Depends(require_admin)])


class ThresholdUpdate(BaseModel):
    warning_threshold_percent: float = Field(gt=0, le=100, allow_inf_nan=False)
    critical_threshold_percent: float = Field(gt=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.critical_threshold_percent < self.warning_threshold_percent:
            raise ValueError("Critical threshold must be at least the warning threshold.")
        return self


class ThresholdOut(ThresholdUpdate):
    model_config = ConfigDict(from_attributes=True)
    service_name: str


class ThresholdSettings(BaseModel):
    warning_threshold_percent: float
    critical_threshold_percent: float
    available_services: list[str]
    overrides: list[ThresholdOut]


def settings_out(db, settings):
    settings = effective_settings(db, settings)
    overrides = list(db.scalars(select(ServiceAlertThreshold).order_by(ServiceAlertThreshold.service_name)))
    services = set(db.scalars(select(LimitItem.service_name).distinct()))
    return ThresholdSettings(
        warning_threshold_percent=settings.warning_threshold_percent,
        critical_threshold_percent=settings.critical_threshold_percent,
        available_services=sorted(services | {row.service_name for row in overrides}),
        overrides=[ThresholdOut.model_validate(row) for row in overrides],
    )


@router.get("", response_model=ThresholdSettings)
def get_thresholds(db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]):
    return settings_out(db, settings)


@router.put("/{service_name}", response_model=ThresholdSettings)
def save_thresholds(service_name: str, payload: ThresholdUpdate, background: BackgroundTasks,
                    db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)],
                    user: Annotated[AuthUser, Depends(require_admin)]):
    if not db.scalar(select(LimitItem.id).where(LimitItem.service_name == service_name).limit(1)):
        raise HTTPException(status_code=404, detail="Choose a service from the scanned service list.")
    row = db.get(ServiceAlertThreshold, service_name)
    if row is None:
        row = ServiceAlertThreshold(service_name=service_name)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    db.add(AuditLog(actor=user.email, action="service_thresholds.updated", target=service_name, detail=payload.model_dump()))
    db.flush()
    refresh_threshold_dependents(db, effective_settings(db, settings), service_name)
    db.commit()
    background.add_task(publish_settings_metrics, settings)
    return settings_out(db, settings)


@router.delete("/{service_name}", response_model=ThresholdSettings)
def reset_thresholds(service_name: str, background: BackgroundTasks,
                     db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)],
                     user: Annotated[AuthUser, Depends(require_admin)]):
    row = db.get(ServiceAlertThreshold, service_name)
    if row is None:
        raise HTTPException(status_code=404, detail="No override exists for this service.")
    db.delete(row)
    db.add(AuditLog(actor=user.email, action="service_thresholds.reset", target=service_name))
    db.flush()
    refresh_threshold_dependents(db, effective_settings(db, settings), service_name)
    db.commit()
    background.add_task(publish_settings_metrics, settings)
    return settings_out(db, settings)
