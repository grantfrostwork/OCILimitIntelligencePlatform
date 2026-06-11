from __future__ import annotations

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import bom, health, limits
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.services.collector import LimitsCollector


def run_scheduled_scan() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        LimitsCollector(db, settings).run_all_configured_regions()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    scheduler: BackgroundScheduler | None = None
    if settings.lip_enable_scheduler:
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            run_scheduled_scan,
            trigger="interval",
            minutes=settings.lip_scan_interval_minutes,
            id="oci-limit-scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(limits.router)
    app.include_router(bom.router)
    return app


app = create_app()
