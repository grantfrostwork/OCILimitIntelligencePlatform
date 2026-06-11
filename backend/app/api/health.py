from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Alert, LimitItem, ScanRun

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_db)) -> str:
    total_limits = db.scalar(select(func.count(LimitItem.id))) or 0
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.status == "open")) or 0
    failed_scans = db.scalar(select(func.count(ScanRun.id)).where(ScanRun.status == "failed")) or 0
    running_scans = db.scalar(select(func.count(ScanRun.id)).where(ScanRun.status == "running")) or 0
    return "\n".join(
        [
            "# HELP lip_limits_total Number of OCI limit rows known to LIP.",
            "# TYPE lip_limits_total gauge",
            f"lip_limits_total {total_limits}",
            "# HELP lip_alerts_open Number of open LIP alerts.",
            "# TYPE lip_alerts_open gauge",
            f"lip_alerts_open {open_alerts}",
            "# HELP lip_scans_failed Number of failed scan runs.",
            "# TYPE lip_scans_failed counter",
            f"lip_scans_failed {failed_scans}",
            "# HELP lip_scans_running Number of currently running scan runs.",
            "# TYPE lip_scans_running gauge",
            f"lip_scans_running {running_scans}",
            "",
        ]
    )
