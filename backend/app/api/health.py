from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.metrics import render_health_metrics, render_metrics

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    return {"status": "ready"}


@router.get("/metrics")
def metrics(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    return Response(
        content=render_metrics(db, settings),
        media_type=CONTENT_TYPE_LATEST,
    )


@router.get("/metrics/health")
def metrics_health(db: Session = Depends(get_db)) -> Response:
    return Response(content=render_health_metrics(db), media_type=CONTENT_TYPE_LATEST)
