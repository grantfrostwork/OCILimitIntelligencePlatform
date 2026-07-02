from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuditLog, MonitoredRegion, utcnow
from app.services.oci_sdk import OciSdk


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, value.get(name.replace("_", "-"), default))
    return getattr(value, name, default)


class RegionService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        sdk: OciSdk | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.sdk = sdk or OciSdk(settings)

    def sync_subscriptions(self) -> list[MonitoredRegion]:
        subscriptions = self.sdk.list_region_subscriptions(
            self.settings.oci_tenancy_ocid,
            region=self.settings.oci_default_region,
        )
        existing = {
            item.region_name: item
            for item in self.db.scalars(select(MonitoredRegion))
        }
        first_discovery = not existing
        discovered_names: set[str] = set()

        for index, subscription in enumerate(subscriptions):
            region_name = _field(subscription, "region_name")
            if not region_name:
                continue
            discovered_names.add(region_name)
            status = _field(subscription, "status") or "UNKNOWN"
            item = existing.get(region_name)
            if item is None:
                enabled_by_default = (
                    status == "READY"
                    and (
                        self.settings.oci_scan_all_regions
                        or region_name == self.settings.oci_default_region
                    )
                )
                item = MonitoredRegion(
                    region_name=region_name,
                    region_key=_field(subscription, "region_key"),
                    subscription_status=status,
                    is_home_region=bool(_field(subscription, "is_home_region")),
                    is_enabled=enabled_by_default,
                    stagger_order=index,
                )
                self.db.add(item)
                existing[region_name] = item
            else:
                item.region_key = _field(subscription, "region_key")
                item.subscription_status = status
                item.is_home_region = bool(_field(subscription, "is_home_region"))
                item.discovered_at = utcnow()
                item.updated_at = utcnow()
                if status != "READY":
                    item.is_enabled = False

        for region_name, item in existing.items():
            if region_name not in discovered_names:
                item.subscription_status = "NOT_SUBSCRIBED"
                item.is_enabled = False
                item.updated_at = utcnow()

        self.db.flush()
        ready = self.ready_regions()
        if ready and not any(item.is_enabled for item in ready):
            default = next(
                (
                    item
                    for item in ready
                    if item.region_name == self.settings.oci_default_region
                ),
                next((item for item in ready if item.is_home_region), ready[0]),
            )
            default.is_enabled = True
            default.stagger_order = 0
            default.updated_at = utcnow()
            self.db.flush()

        if first_discovery:
            self.db.add(
                AuditLog(
                    action="regions.discovered",
                    target=self.settings.oci_tenancy_ocid,
                    detail={"ready_regions": [item.region_name for item in ready]},
                )
            )
        return self.all_regions()

    def update_allowlist(self, region_names: list[str]) -> list[MonitoredRegion]:
        unique_names = list(dict.fromkeys(region_names))
        if not unique_names:
            raise ValueError("At least one READY region must be enabled")
        if not self.all_regions():
            self.sync_subscriptions()
        ready = {item.region_name: item for item in self.ready_regions()}
        invalid = [name for name in unique_names if name not in ready]
        if invalid:
            raise ValueError(f"Regions are not READY subscriptions: {', '.join(invalid)}")

        selected = set(unique_names)
        for item in self.all_regions():
            item.is_enabled = item.region_name in selected
            if item.is_enabled:
                item.stagger_order = unique_names.index(item.region_name)
            item.updated_at = utcnow()

        self.db.add(
            AuditLog(
                action="regions.allowlist_updated",
                target=self.settings.oci_tenancy_ocid,
                detail={"regions": unique_names},
            )
        )
        self.db.flush()
        return self.all_regions()

    def all_regions(self) -> list[MonitoredRegion]:
        return list(
            self.db.scalars(
                select(MonitoredRegion).order_by(
                    MonitoredRegion.is_enabled.desc(),
                    MonitoredRegion.stagger_order,
                    MonitoredRegion.region_name,
                )
            )
        )

    def ready_regions(self) -> list[MonitoredRegion]:
        return list(
            self.db.scalars(
                select(MonitoredRegion)
                .where(MonitoredRegion.subscription_status == "READY")
                .order_by(MonitoredRegion.stagger_order, MonitoredRegion.region_name)
            )
        )

    def enabled_regions(self) -> list[MonitoredRegion]:
        return list(
            self.db.scalars(
                select(MonitoredRegion)
                .where(
                    MonitoredRegion.subscription_status == "READY",
                    MonitoredRegion.is_enabled.is_(True),
                )
                .order_by(MonitoredRegion.stagger_order, MonitoredRegion.region_name)
            )
        )

    def canonical_region(self) -> str:
        home = self.db.scalar(
            select(MonitoredRegion)
            .where(
                MonitoredRegion.subscription_status == "READY",
                MonitoredRegion.is_home_region.is_(True),
            )
            .limit(1)
        )
        return home.region_name if home else self.settings.oci_default_region
