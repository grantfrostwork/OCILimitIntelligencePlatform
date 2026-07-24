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

    auth_enabled: bool = False
    auth_public_url: str = "http://localhost:5173"
    auth_session_secret: str = "local-development-session-secret"
    auth_session_max_age_seconds: int = 8 * 60 * 60
    auth_cookie_secure: bool = False
    auth_oidc_discovery_url: str | None = None
    auth_oidc_client_id: str | None = None
    auth_oidc_client_secret: str | None = None
    auth_oidc_scopes: str = "openid profile email groups"
    auth_group_claim: str = "groups"
    auth_viewer_groups: list[str] = Field(
        default_factory=lambda: ["OCI-LIP-Viewers"]
    )
    auth_operator_groups: list[str] = Field(
        default_factory=lambda: ["OCI-LIP-Operators"]
    )
    auth_admin_groups: list[str] = Field(
        default_factory=lambda: ["OCI-LIP-Admins"]
    )
    auth_bootstrap_admin_emails: list[str] = Field(default_factory=list)

    oci_auth_mode: Literal["profile", "instance_principal"] = "profile"
    oci_profile: str = "DEFAULT"
    oci_config_file: str = "~/.oci/config"
    oci_tenancy_ocid: str = (
        "ocid1.tenancy.oc1..aaaaaaaa5trur7whdyytam4nmh3tinrx2yfqnbss6yzz4q6i7gmm2leagnkq"
    )
    oci_default_region: str = "us-ashburn-1"
    oci_scan_all_regions: bool = False
    oci_connect_timeout_seconds: int = 10
    oci_read_timeout_seconds: int = 45
    oci_max_service_workers: int = 6
    oci_max_limit_workers: int = 10
    oci_max_region_workers: int = 2
    oci_global_max_concurrent_requests: int = 12
    oci_db_commit_batch_size: int = 25
    oci_region_stagger_seconds: int = 15
    oci_region_scan_max_attempts: int = 3
    oci_region_retry_base_seconds: int = 30
    oci_region_retry_max_seconds: int = 300

    warning_threshold_percent: float = 90.0
    critical_threshold_percent: float = 98.0
    trend_alert_window_days: int = 14
    trend_min_points: int = 4

    lip_scan_interval_minutes: int = 240
    lip_worker_poll_seconds: int = 2
    lip_prometheus_otlp_endpoint: str | None = None
    lip_metrics_publish_max_attempts: int = 3
    lip_metrics_publish_timeout_seconds: int = 30
    lip_enable_notifications: bool = False
    lip_notification_topic_name: str = "oci-lip-limit-alerts"
    lip_notification_compartment_ocid: str | None = None
    lip_notification_emails: list[str] = Field(
        default_factory=lambda: ["grant.frost@oracle.com"]
    )
    lip_alert_dedupe_minutes: int = 360

    upload_dir: Path = Path("./uploads")
    upload_max_bytes: int = 25 * 1024 * 1024

    def validate_auth_configuration(self) -> None:
        if not self.auth_enabled:
            return
        missing = [
            name
            for name, value in (
                ("AUTH_OIDC_DISCOVERY_URL", self.auth_oidc_discovery_url),
                ("AUTH_OIDC_CLIENT_ID", self.auth_oidc_client_id),
                ("AUTH_OIDC_CLIENT_SECRET", self.auth_oidc_client_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "OIDC authentication is enabled but required settings are missing: "
                + ", ".join(missing)
            )
        if len(self.auth_session_secret) < 32:
            raise RuntimeError("AUTH_SESSION_SECRET must contain at least 32 characters")
        if not self.auth_public_url.startswith("https://"):
            raise RuntimeError("AUTH_PUBLIC_URL must use HTTPS when authentication is enabled")
        if not self.auth_cookie_secure:
            raise RuntimeError("AUTH_COOKIE_SECURE must be true when authentication is enabled")


@lru_cache
def get_settings() -> Settings:
    return Settings()
