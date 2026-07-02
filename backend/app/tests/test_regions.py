from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.services.regions import RegionService


class RegionFakeSdk:
    def list_region_subscriptions(self, tenancy_id: str, *, region: str):
        return [
            SimpleNamespace(
                region_name="us-ashburn-1",
                region_key="IAD",
                status="READY",
                is_home_region=True,
            ),
            SimpleNamespace(
                region_name="us-phoenix-1",
                region_key="PHX",
                status="READY",
                is_home_region=False,
            ),
            SimpleNamespace(
                region_name="eu-frankfurt-1",
                region_key="FRA",
                status="READY",
                is_home_region=False,
            ),
        ]


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_first_discovery_enables_only_default_region():
    db = _db()
    service = RegionService(
        db,
        Settings(oci_default_region="us-ashburn-1", oci_scan_all_regions=False),
        sdk=RegionFakeSdk(),
    )

    regions = service.sync_subscriptions()

    assert len(regions) == 3
    assert [item.region_name for item in regions if item.is_enabled] == ["us-ashburn-1"]
    assert service.canonical_region() == "us-ashburn-1"


def test_allowlist_order_is_persisted_and_validated():
    db = _db()
    service = RegionService(db, Settings(), sdk=RegionFakeSdk())
    service.sync_subscriptions()

    regions = service.update_allowlist(["us-phoenix-1", "eu-frankfurt-1"])

    enabled = [item for item in regions if item.is_enabled]
    assert [item.region_name for item in enabled] == ["us-phoenix-1", "eu-frankfurt-1"]
    assert [item.stagger_order for item in enabled] == [0, 1]
    with pytest.raises(ValueError, match="not READY"):
        service.update_allowlist(["ap-sydney-1"])
