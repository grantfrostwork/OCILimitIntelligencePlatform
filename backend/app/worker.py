from __future__ import annotations

import logging
import signal
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.services.oci_sdk import OciSdkError
from app.services.regions import RegionService
from app.services.scan_queue import (
    claim_due_requests,
    enqueue_scan_requests,
    next_scheduled_scan_at,
    process_scan_request,
    recover_interrupted_requests,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("oci_lip.worker")
shutdown = False


def _stop(*_args) -> None:
    global shutdown
    shutdown = True


def _initialize(settings) -> datetime:
    with SessionLocal() as db:
        recovered = recover_interrupted_requests(db)
        try:
            regions = RegionService(db, settings).sync_subscriptions()
            logger.info(
                "region subscriptions synchronized",
                extra={"ready_regions": sum(item.subscription_status == "READY" for item in regions)},
            )
        except OciSdkError:
            logger.exception("region subscription synchronization failed; using persisted allowlist")
        next_scan_at = next_scheduled_scan_at(db, settings.lip_scan_interval_minutes)
        db.commit()
    if recovered:
        logger.warning("recovered interrupted scan requests", extra={"count": recovered})
    return next_scan_at


def _enqueue_scheduled_batch(settings) -> None:
    with SessionLocal() as db:
        try:
            RegionService(db, settings).sync_subscriptions()
        except OciSdkError:
            logger.exception("region subscription refresh failed; using persisted allowlist")
        batch_id, requests, skipped = enqueue_scan_requests(
            db,
            settings,
            trigger="scheduled",
        )
        db.commit()
    logger.info(
        "scheduled scan batch evaluated",
        extra={
            "batch_id": batch_id,
            "queued_regions": [item.region for item in requests],
            "skipped_regions": skipped,
        },
    )


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    settings = get_settings()
    init_db()
    next_scan_at = _initialize(settings)
    running: dict[Future[str], str] = {}

    with ThreadPoolExecutor(
        max_workers=max(1, settings.oci_max_region_workers),
        thread_name_prefix="oci-regions",
    ) as executor:
        while not shutdown:
            for future in [item for item in running if item.done()]:
                request_id = running.pop(future)
                try:
                    status = future.result()
                    logger.info(
                        "regional scan attempt completed",
                        extra={"request_id": request_id, "status": status},
                    )
                except Exception:
                    logger.exception(
                        "regional scan worker failed unexpectedly",
                        extra={"request_id": request_id},
                    )

            now = datetime.now(UTC)
            if now >= next_scan_at:
                _enqueue_scheduled_batch(settings)
                next_scan_at = now + timedelta(minutes=settings.lip_scan_interval_minutes)

            available_slots = max(0, settings.oci_max_region_workers - len(running))
            if available_slots:
                with SessionLocal() as db:
                    requests = claim_due_requests(db, available_slots)
                    request_ids = [item.id for item in requests]
                    db.commit()
                for request_id in request_ids:
                    running[executor.submit(process_scan_request, request_id, settings)] = request_id

            time.sleep(max(1, settings.lip_worker_poll_seconds))


if __name__ == "__main__":
    main()
