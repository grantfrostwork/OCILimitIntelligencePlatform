from __future__ import annotations

import csv
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import Alert, LimitItem, MonitoredRegion, ScanRequest, ScanRun, TrendPrediction
from app.schemas import (
    AlertOut,
    DashboardOut,
    LimitItemOut,
    RegionAllowlistUpdate,
    RegionOut,
    ScanEnqueueOut,
    ScanRequestOut,
    ScanRunOut,
    ScanScheduleOut,
    ScanScheduleUpdate,
)
from app.services.alerts import AlertService
from app.services.oci_sdk import OciSdkError
from app.services.regions import RegionService
from app.services.scan_queue import enqueue_scan_requests
from app.services.schedule import ALLOWED_SCAN_INTERVALS, get_or_create_schedule, update_schedule

router = APIRouter(prefix="/api", tags=["limits"])


def _schedule_out(schedule) -> ScanScheduleOut:
    return ScanScheduleOut(
        is_enabled=schedule.is_enabled,
        interval_minutes=schedule.interval_minutes,
        next_scan_at=schedule.next_scan_at,
        last_enqueued_at=schedule.last_enqueued_at,
        allowed_intervals=list(ALLOWED_SCAN_INTERVALS),
        updated_at=schedule.updated_at,
    )


def _region_outputs(db: Session) -> list[RegionOut]:
    regions = list(
        db.scalars(
            select(MonitoredRegion).order_by(
                MonitoredRegion.is_enabled.desc(),
                MonitoredRegion.stagger_order,
                MonitoredRegion.region_name,
            )
        )
    )
    output: list[RegionOut] = []
    for item in regions:
        latest_scan = db.scalar(
            select(ScanRun)
            .where(ScanRun.region == item.region_name)
            .order_by(desc(ScanRun.started_at))
            .limit(1)
        )
        latest_request = db.scalar(
            select(ScanRequest)
            .where(ScanRequest.region == item.region_name)
            .order_by(desc(ScanRequest.requested_at))
            .limit(1)
        )
        output.append(
            RegionOut(
                region_name=item.region_name,
                region_key=item.region_key,
                subscription_status=item.subscription_status,
                is_home_region=item.is_home_region,
                is_enabled=item.is_enabled,
                stagger_order=item.stagger_order,
                latest_scan=(
                    ScanRunOut.model_validate(latest_scan) if latest_scan else None
                ),
                request_status=latest_request.status if latest_request else None,
                request_id=latest_request.id if latest_request else None,
                next_attempt_at=(
                    latest_request.not_before
                    if latest_request and latest_request.status == "queued"
                    else None
                ),
            )
        )
    return output


def _enqueue_scan_response(
    db: Session,
    settings: Settings,
    region_names: list[str] | None,
) -> ScanEnqueueOut:
    try:
        batch_id, requests, skipped = enqueue_scan_requests(
            db,
            settings,
            trigger="manual",
            region_names=region_names,
        )
    except (OciSdkError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    queued = [item.region for item in requests]
    requested = list(dict.fromkeys([*queued, *skipped]))
    return ScanEnqueueOut(
        status="queued" if queued else "already_queued",
        batch_id=batch_id,
        regions=requested,
        queued_regions=queued,
        skipped_regions=skipped,
    )


def criticality(item: LimitItem, settings: Settings) -> str:
    if item.last_collection_status not in {"ok", "unsupported"}:
        return "error"
    if item.last_percent_used is None:
        return "unknown"
    if item.last_percent_used >= settings.critical_threshold_percent:
        return "critical"
    if item.last_percent_used >= settings.warning_threshold_percent:
        return "warning"
    return "normal"


def limit_to_out(item: LimitItem, settings: Settings) -> LimitItemOut:
    return LimitItemOut(
        id=item.id,
        region=item.region,
        service_name=item.service_name,
        limit_name=item.limit_name,
        resource_name=item.resource_name,
        scope_type=item.scope_type,
        availability_domain=item.availability_domain,
        compartment_ocid=item.compartment_ocid,
        last_allowed_limit=item.last_allowed_limit,
        last_used=item.last_used,
        last_available=item.last_available,
        last_percent_used=item.last_percent_used,
        last_collection_status=item.last_collection_status,
        last_collected_at=item.last_collected_at,
        criticality=criticality(item, settings),
    )


def _limits_query(
    db: Session,
    settings: Settings,
    service: str | None,
    region: str | None,
    q: str | None,
    min_percent: float | None,
    level: str | None,
    near_limit: bool,
):
    query = select(LimitItem)
    if service:
        query = query.where(LimitItem.service_name == service)
    if region:
        query = query.where(LimitItem.region == region)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(LimitItem.limit_name).like(like),
                func.lower(LimitItem.service_name).like(like),
                func.lower(LimitItem.resource_name).like(like),
            )
        )
    if min_percent is not None:
        query = query.where(LimitItem.last_percent_used >= min_percent)
    if near_limit:
        query = query.where(LimitItem.last_percent_used >= settings.warning_threshold_percent)
    if level == "critical":
        query = query.where(LimitItem.last_percent_used >= settings.critical_threshold_percent)
    elif level == "warning":
        query = query.where(
            LimitItem.last_percent_used >= settings.warning_threshold_percent,
            LimitItem.last_percent_used < settings.critical_threshold_percent,
        )
    elif level == "normal":
        query = query.where(LimitItem.last_percent_used < settings.warning_threshold_percent)
    elif level == "error":
        query = query.where(LimitItem.last_collection_status == "failed")
    elif level == "unknown":
        query = query.where(LimitItem.last_percent_used.is_(None))
    return query


@router.get("/limits")
def list_limits(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    service: str | None = None,
    region: str | None = None,
    q: str | None = None,
    min_percent: float | None = None,
    level: str | None = Query(None, pattern="^(normal|warning|critical|error|unknown)$"),
    near_limit: bool = False,
    sort_by: str = Query("last_percent_used"),
    sort_dir: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    base = _limits_query(db, settings, service, region, q, min_percent, level, near_limit)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    sort_columns = {
        "service_name": LimitItem.service_name,
        "limit_name": LimitItem.limit_name,
        "region": LimitItem.region,
        "last_used": LimitItem.last_used,
        "last_allowed_limit": LimitItem.last_allowed_limit,
        "last_available": LimitItem.last_available,
        "last_percent_used": LimitItem.last_percent_used,
        "last_collected_at": LimitItem.last_collected_at,
    }
    sort_col = sort_columns.get(sort_by, LimitItem.last_percent_used)
    if sort_dir == "desc":
        base = base.order_by(desc(sort_col).nullslast())
    else:
        base = base.order_by(sort_col.nullslast())
    items = list(db.scalars(base.offset((page - 1) * page_size).limit(page_size)))
    return {
        "items": [item.model_dump(mode="json") for item in (limit_to_out(i, settings) for i in items)],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/limits/export")
def export_limits(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    service: str | None = None,
    region: str | None = None,
    q: str | None = None,
    level: str | None = None,
    near_limit: bool = False,
) -> StreamingResponse:
    query = _limits_query(db, settings, service, region, q, None, level, near_limit)
    rows = list(db.scalars(query.order_by(LimitItem.service_name, LimitItem.limit_name)))
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "service",
            "limit",
            "usage",
            "allowed",
            "percent_used",
            "remaining",
            "region",
            "scope",
            "availability_domain",
            "status",
            "last_updated",
            "criticality",
        ]
    )
    for item in rows:
        writer.writerow(
            [
                item.service_name,
                item.limit_name,
                item.last_used,
                item.last_allowed_limit,
                item.last_percent_used,
                item.last_available,
                item.region,
                item.scope_type,
                item.availability_domain,
                item.last_collection_status,
                item.last_collected_at,
                criticality(item, settings),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=oci-lip-limits.csv"},
    )


@router.get("/services")
def list_services(db: Session = Depends(get_db)) -> dict:
    services = list(db.scalars(select(distinct(LimitItem.service_name)).order_by(LimitItem.service_name)))
    regions = list(db.scalars(select(distinct(LimitItem.region)).order_by(LimitItem.region)))
    return {"services": services, "regions": regions}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DashboardOut:
    total = db.scalar(select(func.count(LimitItem.id))) or 0
    at_capacity = (
        db.scalar(
            select(func.count(LimitItem.id)).where(
                LimitItem.last_allowed_limit.is_not(None),
                or_(
                    LimitItem.last_percent_used >= 100,
                    and_(
                        LimitItem.last_allowed_limit > 0,
                        LimitItem.last_available <= 0,
                    ),
                    and_(
                        LimitItem.last_used.is_not(None),
                        LimitItem.last_allowed_limit > 0,
                        LimitItem.last_used >= LimitItem.last_allowed_limit,
                    ),
                ),
            )
        )
        or 0
    )
    near_capacity = (
        db.scalar(
            select(func.count(LimitItem.id)).where(
                LimitItem.last_percent_used >= settings.warning_threshold_percent,
                LimitItem.last_percent_used < 100,
            )
        )
        or 0
    )
    if at_capacity:
        overall_status = "red"
        status_reason = f"{at_capacity} limit(s) are at or above allowed capacity."
    elif near_capacity:
        overall_status = "yellow"
        status_reason = (
            f"{near_capacity} limit(s) are at or above the "
            f"{settings.warning_threshold_percent:g}% warning threshold."
        )
    else:
        overall_status = "green"
        status_reason = "No detected limit capacity risk."

    warning = (
        db.scalar(
            select(func.count(LimitItem.id)).where(
                LimitItem.last_percent_used >= settings.warning_threshold_percent,
                LimitItem.last_percent_used < settings.critical_threshold_percent,
            )
        )
        or 0
    )
    critical = (
        db.scalar(
            select(func.count(LimitItem.id)).where(
                LimitItem.last_percent_used >= settings.critical_threshold_percent
            )
        )
        or 0
    )

    top_usage = [
        limit_to_out(item, settings).model_dump(mode="json")
        for item in db.scalars(
            select(LimitItem)
            .where(LimitItem.last_percent_used.is_not(None))
            .order_by(desc(LimitItem.last_percent_used))
            .limit(10)
        )
    ]

    services_near_capacity = [
        {"service_name": service, "count": count}
        for service, count in db.execute(
            select(LimitItem.service_name, func.count(LimitItem.id))
            .where(LimitItem.last_percent_used >= settings.warning_threshold_percent)
            .group_by(LimitItem.service_name)
            .order_by(desc(func.count(LimitItem.id)))
            .limit(10)
        ).all()
    ]

    recent_trends = [
        {
            "limit_item_id": prediction.limit_item_id,
            "slope_used_per_day": prediction.slope_used_per_day,
            "eta_days_to_warning": prediction.eta_days_to_warning,
            "projected_breach_at": prediction.projected_breach_at,
            "confidence": prediction.confidence,
            "summary": prediction.summary,
        }
        for prediction in db.scalars(
            select(TrendPrediction).order_by(desc(TrendPrediction.calculated_at)).limit(10)
        )
    ]

    last_scan = db.scalar(select(ScanRun).order_by(desc(ScanRun.started_at)).limit(1))
    return DashboardOut(
        overall_status=overall_status,
        status_reason=status_reason,
        limits_at_capacity=at_capacity,
        limits_near_capacity=near_capacity,
        total_limits_scanned=total,
        warning_limits=warning,
        critical_limits=critical,
        services_near_capacity=services_near_capacity,
        top_usage=top_usage,
        recent_trends=recent_trends,
        last_scan=ScanRunOut.model_validate(last_scan) if last_scan else None,
    )


@router.get("/regions", response_model=list[RegionOut])
def list_regions(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[RegionOut]:
    if not db.scalar(select(func.count(MonitoredRegion.id))):
        try:
            RegionService(db, settings).sync_subscriptions()
            db.commit()
        except OciSdkError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _region_outputs(db)


@router.post("/regions/discover", response_model=list[RegionOut])
def discover_regions(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[RegionOut]:
    try:
        RegionService(db, settings).sync_subscriptions()
    except OciSdkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    return _region_outputs(db)


@router.put("/regions/allowlist", response_model=list[RegionOut])
def update_region_allowlist(
    payload: RegionAllowlistUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[RegionOut]:
    try:
        RegionService(db, settings).update_allowlist(payload.regions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _region_outputs(db)


@router.post("/regions/{region}/scan", response_model=ScanEnqueueOut)
def trigger_region_scan(
    region: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanEnqueueOut:
    return _enqueue_scan_response(db, settings, [region])


@router.get("/scan-requests", response_model=list[ScanRequestOut])
def scan_requests(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[ScanRequest]:
    return list(
        db.scalars(
            select(ScanRequest)
            .order_by(desc(ScanRequest.requested_at), ScanRequest.region)
            .limit(limit)
        )
    )


@router.post("/scan-runs", response_model=ScanEnqueueOut)
def trigger_scan(
    region: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanEnqueueOut:
    return _enqueue_scan_response(db, settings, [region] if region else None)


@router.get("/scan-schedule", response_model=ScanScheduleOut)
def scan_schedule(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanScheduleOut:
    schedule = get_or_create_schedule(db, settings)
    db.commit()
    return _schedule_out(schedule)


@router.put("/scan-schedule", response_model=ScanScheduleOut)
def set_scan_schedule(
    payload: ScanScheduleUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanScheduleOut:
    try:
        schedule = update_schedule(
            db,
            settings,
            is_enabled=payload.is_enabled,
            interval_minutes=payload.interval_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _schedule_out(schedule)


@router.get("/scan-runs", response_model=list[ScanRunOut])
def scan_runs(db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=100)) -> list[ScanRun]:
    return list(db.scalars(select(ScanRun).order_by(desc(ScanRun.started_at)).limit(limit)))


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(open|closed)$"),
    limit: int = Query(100, ge=1, le=500),
) -> list[Alert]:
    query = select(Alert).order_by(desc(Alert.last_seen_at)).limit(limit)
    if status:
        query = select(Alert).where(Alert.status == status).order_by(desc(Alert.last_seen_at)).limit(limit)
    return list(db.scalars(query))


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: str, db: Session = Depends(get_db)) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "closed"
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/notifications/ensure")
def ensure_notifications(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    config = AlertService(db, settings).ensure_notification_config()
    db.commit()
    return {
        "topic_name": config.topic_name,
        "topic_id": config.topic_id,
        "region": config.region,
        "emails": config.emails,
        "subscription_status": config.subscription_status,
        "enabled": settings.lip_enable_notifications,
    }
