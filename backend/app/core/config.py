from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = "OCI Limit Intelligence Platform"
    environment: str = "development"
    database_url: str = "sqlite:///./lip.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    oci_auth_mode: Literal["profile", "instance_principal"] = "profile"
    oci_profile: str = "DEFAULT"
    oci_tenancy_ocid: str = (
        "ocid1.tenancy.oc1..aaaaaaaa5trur7whdyytam4nmh3tinrx2yfqnbss6yzz4q6i7gmm2leagnkq"
    )
    oci_default_region: str = "us-ashburn-1"
    oci_scan_all_regions: bool = False
    oci_cli_path: str = "oci"
    oci_command_timeout_seconds: int = 45
    oci_max_service_workers: int = 6
    oci_max_limit_workers: int = 10

    warning_threshold_percent: float = 90.0
    critical_threshold_percent: float = 98.0
    trend_alert_window_days: int = 14
    trend_min_points: int = 4

    lip_enable_scheduler: bool = False
    lip_scan_interval_minutes: int = 60
    lip_enable_notifications: bool = False
    lip_notification_topic_name: str = "oci-lip-limit-alerts"
    lip_notification_compartment_ocid: str | None = None
    lip_notification_emails: list[str] = Field(
        default_factory=lambda: ["grant.frost@oracle.com"]
    )
    lip_alert_dedupe_minutes: int = 360

    upload_dir: Path = Path("./uploads")
    upload_max_bytes: int = 25 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
