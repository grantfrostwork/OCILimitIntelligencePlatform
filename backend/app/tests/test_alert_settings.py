from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.notifications import NotificationUpdate, config_for
from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Alert, AlertEvent, LimitItem, LimitSnapshot
from app.services.alerts import AlertService
from app.services.notification_settings import effective_settings
from app.services.oci_sdk import OciSdkError


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def payload(**changes):
    values = {
        "enabled": True,
        "warning_threshold_percent": 75,
        "critical_threshold_percent": 95,
        "emails": ["Grant.Frost@oracle.com", "grant.frost@oracle.com"],
        "subject_template": "Increase {service}: {limit}",
        "message_template": "{region}: {percent_used}% ({used}/{allowed_limit}); threshold {threshold}%. {message} {app_url}",
    }
    values.update(changes)
    return NotificationUpdate(**values)


class NotificationSdk:
    def __init__(self):
        self.subscriptions = [
            SimpleNamespace(
                id="removed-sub",
                endpoint="old@example.com",
                protocol="EMAIL",
                lifecycle_state="ACTIVE",
            )
        ]
        self.deleted = []
        self.published = []
        self.fail = False

    def list_topics(self, compartment_id, **kwargs):
        assert compartment_id == "dedicated"
        return [
            SimpleNamespace(
                name="oci-lip-limit-alerts", topic_id="topic-1", lifecycle_state="ACTIVE"
            )
        ]

    def list_subscriptions(self, *args, **kwargs):
        return self.subscriptions[:]

    def delete_subscription(self, subscription_id, **kwargs):
        self.deleted.append(subscription_id)
        self.subscriptions = [s for s in self.subscriptions if s.id != subscription_id]

    def create_subscription(self, compartment_id, topic_id, email, **kwargs):
        sub = SimpleNamespace(
            id="new-sub", endpoint=email, protocol="EMAIL", lifecycle_state="PENDING"
        )
        self.subscriptions.append(sub)
        return sub

    def publish_message(self, topic_id, title, body, **kwargs):
        if self.fail:
            raise OciSdkError("ons.publish_message", "test delivery failure")
        self.published.append((topic_id, title, body))
        return {"message_id": "test-1"}

    def to_dict(self, value):
        return value


def configured(db):
    settings = Settings(lip_notification_compartment_ocid="dedicated")
    config = config_for(db, settings)
    for key, value in payload().model_dump().items():
        setattr(config, key, value)
    db.commit()
    return settings, config


def test_settings_validate_addresses_thresholds_and_templates():
    assert payload().emails == ["grant.frost@oracle.com"]
    for changes in [
        {"warning_threshold_percent": 101},
        {"critical_threshold_percent": 70},
        {"emails": []},
        {"emails": ["bad-address"]},
        {"warning_threshold_percent": float("nan")},
        {"subject_template": "{service.__class__}"},
        {"message_template": "{unknown}"},
        {"subject_template": "bad\nsubject"},
        {"message_template": " "},
        {"message_template": "{message!r}"},
    ]:
        with pytest.raises(ValueError):
            payload(**changes)


def test_recipient_sync_removes_old_and_preserves_pending_confirmation(db):
    settings, config = configured(db)
    sdk = NotificationSdk()
    service = AlertService(db, settings, sdk)
    assert service.ensure_notification_config().topic_id == "topic-1"
    assert sdk.deleted == ["removed-sub"]
    assert config.subscription_status == {"grant.frost@oracle.com": "PENDING"}
    service.ensure_notification_config()
    assert len(sdk.subscriptions) == 1
    sdk.subscriptions[0].lifecycle_state = "ACTIVE"
    service.ensure_notification_config()
    assert config.subscription_status == {"grant.frost@oracle.com": "ACTIVE"}


def test_saved_threshold_controls_alerts_and_dedupe_ignores_changing_usage(db):
    settings, config = configured(db)
    sdk = NotificationSdk()
    item = LimitItem(
        region="us-ashburn-1",
        compartment_ocid="tenancy",
        service_name="compute",
        limit_name="cores",
        scope_type="REGION",
        subscription_id="",
    )
    db.add(item)
    db.flush()

    def evaluate(percent):
        snapshot = LimitSnapshot(
            limit_item_id=item.id,
            allowed_limit=100,
            used=percent,
            available=100 - percent,
            percent_used=percent,
            collection_status="ok",
        )
        AlertService(db, settings, sdk).evaluate_snapshot(item, snapshot)
        db.commit()

    evaluate(74)
    assert not sdk.published
    evaluate(75)
    assert len(sdk.published) == 1
    assert "75.0%" in sdk.published[0][2]
    evaluate(76)
    assert len(sdk.published) == 1
    assert db.scalar(select(Alert)).metadata_json["percent_used"] == 76
    evaluate(95)
    assert len(sdk.published) == 2  # escalation to critical
    assert effective_settings(db, settings).warning_threshold_percent == 75
    assert settings.warning_threshold_percent == 90  # global settings stay immutable
    config.enabled = False
    db.commit()
    evaluate(99)
    assert len(sdk.published) == 2


def test_notification_failure_is_recorded_without_aborting_collection(db):
    settings, config = configured(db)
    sdk = NotificationSdk()
    sdk.fail = True
    service = AlertService(db, settings, sdk)
    alert = service.upsert_alert(
        alert_type="threshold_exceeded",
        severity="warning",
        title="test",
        message="review",
        metadata={"limit_item_id": "item-1", "percent_used": 80},
    )
    db.commit()
    assert alert.dedupe_until is None
    assert "test delivery failure" in config.last_error
    assert db.scalar(select(AlertEvent)).delivery_status == "failed"


def test_api_requires_admin_and_rejects_invalid_values(db, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        "viewer-1", "v@example.com", "Viewer", "viewer", ()
    )
    client = TestClient(app)
    assert client.get("/api/notifications").status_code == 403
    assert client.put("/api/notifications", json=payload().model_dump()).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        "admin-1", "a@example.com", "Admin", "admin", ()
    )
    assert client.get("/api/notifications").status_code == 200
    monkeypatch.setattr("app.api.notifications.reconcile", lambda db, settings, config: config)
    response = client.put("/api/notifications", json=payload(enabled=False).model_dump())
    assert response.status_code == 200
    assert response.json()["warning_threshold_percent"] == 75
    assert client.get("/api/notifications").json()["emails"] == ["grant.frost@oracle.com"]
    bad = payload().model_dump()
    bad["critical_threshold_percent"] = 50
    assert client.put("/api/notifications", json=bad).status_code == 422
    assert client.get("/api/bom").status_code == 404
    assert client.post("/api/bom/analyze").status_code == 404
    app.dependency_overrides.clear()


def test_critical_message_uses_critical_threshold(db):
    from app.services.message_templates import render_message

    settings, config = configured(db)
    alert = Alert(
        severity="critical",
        service_name="compute",
        limit_name="cores",
        region="us-ashburn-1",
        message="review",
        metadata_json={"percent_used": 96, "used": 96, "allowed_limit": 100},
    )
    title, body = render_message(config, alert, settings)
    assert title == "Increase compute: cores"
    assert "threshold 95%" in body
