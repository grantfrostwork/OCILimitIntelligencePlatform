from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import LimitItem
from app.services.collector import LimitsCollector


class ConcurrentFakeSdk:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.service_active = 0
        self.service_max_active = 0
        self.availability_active = 0
        self.availability_max_active = 0

    def list_services(self, compartment_id: str, *, region: str):
        return [
            SimpleNamespace(name=name, description=name.title())
            for name in ("compute", "vcn", "block-storage", "load-balancer")
        ]

    def list_limit_values(self, compartment_id: str, service_name: str, *, region: str):
        with self._lock:
            self.service_active += 1
            self.service_max_active = max(self.service_max_active, self.service_active)
        time.sleep(0.03)
        with self._lock:
            self.service_active -= 1
        values = [
            SimpleNamespace(
                name=f"{service_name}-limit-{index}",
                scope_type="REGION",
                availability_domain=None,
                value=100,
            )
            for index in range(3)
        ]
        if service_name == "compute":
            values.append(
                SimpleNamespace(
                    name="dynamic-limit",
                    scope_type="REGION",
                    availability_domain=None,
                    value="Dynamic",
                )
            )
        return values

    def get_resource_availability(
        self,
        compartment_id: str,
        service_name: str,
        limit_name: str,
        *,
        region: str,
        availability_domain: str | None = None,
    ):
        with self._lock:
            self.availability_active += 1
            self.availability_max_active = max(
                self.availability_max_active, self.availability_active
            )
        time.sleep(0.02)
        with self._lock:
            self.availability_active -= 1
        return SimpleNamespace(
            effective_quota_value=100,
            used=25,
            available=75,
            fractional_usage=0.25,
            fractional_availability=0.75,
        )

    @staticmethod
    def to_dict(value):
        return vars(value) if value is not None else {}

    @staticmethod
    def is_not_found_or_unsupported(exc) -> bool:
        return False


def test_scan_parallelizes_sdk_calls_and_persists_results():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    sdk = ConcurrentFakeSdk()
    settings = Settings(
        oci_tenancy_ocid="tenancy",
        oci_max_service_workers=4,
        oci_max_limit_workers=4,
        oci_db_commit_batch_size=2,
    )

    scan = LimitsCollector(db, settings, sdk=sdk).run_scan("us-ashburn-1")

    assert scan.status == "succeeded"
    assert scan.total_limits_discovered == 12
    assert scan.limits_scanned == 12
    assert sdk.service_max_active > 1
    assert sdk.availability_max_active > 1
    assert db.scalar(select(func.count(LimitItem.id))) == 12
    assert db.scalar(select(LimitItem).where(LimitItem.limit_name == "dynamic-limit")) is None
