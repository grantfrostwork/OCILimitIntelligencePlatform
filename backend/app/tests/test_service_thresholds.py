from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.limits import criticality, dashboard, limit_to_out, _limits_query
from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.main import create_app
from app.models import Alert, AuditLog, LimitItem, LimitSnapshot, ServiceAlertThreshold, utcnow
from app.services.alerts import AlertService
from app.services.metrics import render_metrics
from app.services.muting import mute_limit, unmute_limit
from app.services.notification_settings import effective_settings
from app.services.thresholds import thresholds_for
from app.services.trends import TrendService
from app.tests.test_alert_settings import db, configured, NotificationSdk  # noqa: F401


def limit(db, service="compute", region="us-ashburn-1", percent=82):
    item = LimitItem(service_name=service, region=region, compartment_ocid="tenancy", limit_name="test-count",
                     scope_type="REGION", subscription_id="", last_used=percent, last_allowed_limit=100,
                     last_available=100-percent, last_percent_used=percent, last_collection_status="ok")
    db.add(item)
    db.flush()
    return item


def override(db, service="compute", warning=85, critical=95):
    db.add(ServiceAlertThreshold(service_name=service, warning_threshold_percent=warning, critical_threshold_percent=critical))
    db.commit()


def test_default_and_override_precedence_across_regions_and_sql(db):
    settings = Settings(warning_threshold_percent=81)
    a = limit(db)
    b = limit(db, region="us-phoenix-1")
    other = limit(db, service="vcn")
    override(db)
    runtime = effective_settings(db, settings)
    assert thresholds_for(runtime, "compute").source == "service"
    assert criticality(a, runtime) == criticality(b, runtime) == "normal"
    assert criticality(other, runtime) == "warning"
    assert limit_to_out(a, runtime).warning_threshold_percent == 85
    assert limit_to_out(other, runtime).threshold_source == "default"
    query = _limits_query(db, runtime, None, None, None, None, "warning", False, "active")
    assert [row.id for row in db.scalars(query)] == [other.id]
    summary = dashboard(db, runtime)
    assert summary.warning_limits == 1
    assert summary.services_near_capacity == [{"service_name": "vcn", "count": 1}]
    metrics = render_metrics(db, settings).decode()
    assert 'oci_lip_limit_warning_threshold_percent{availability_domain="",limit_name="test-count",region="us-ashburn-1",scope="REGION",service="compute"} 85.0' in metrics


def test_override_alert_boundaries_email_threshold_dedupe_and_mute(db):
    settings, config = configured(db)  # global warning 75 / critical 95
    override(db, warning=85, critical=90)
    item = limit(db)
    sdk = NotificationSdk()
    def evaluate(percent):
        snapshot = LimitSnapshot(limit_item_id=item.id, allowed_limit=100, used=percent, available=100-percent, percent_used=percent, collection_status="ok")
        AlertService(db, settings, sdk).evaluate_snapshot(item, snapshot)
        db.commit()
    evaluate(84.9)
    assert not sdk.published
    evaluate(85)
    assert len(sdk.published) == 1
    assert "threshold 85%" in sdk.published[0][2]
    evaluate(86)
    assert len(sdk.published) == 1
    evaluate(90)
    assert len(sdk.published) == 2
    assert "threshold 90%" in sdk.published[1][2]
    mute_limit(db, item)
    db.commit()
    evaluate(100)
    assert len(sdk.published) == 2
    item.last_percent_used = 82
    unmute_limit(db, item, effective_settings(db, settings))
    assert all(row.status != "open" for row in db.scalars(select(Alert)))


def test_forecast_uses_service_warning(db):
    item = limit(db)
    started = utcnow() - timedelta(days=3)
    for index, used in enumerate([60, 65, 70, 75]):
        db.add(LimitSnapshot(limit_item_id=item.id, scan_run_id="test", allowed_limit=100, used=used,
                             collected_at=started+timedelta(days=index), collection_status="ok"))
    override(db, warning=80, critical=95)
    runtime = effective_settings(db, Settings(warning_threshold_percent=90))
    prediction = TrendService(db, runtime).calculate_for_limit(item)
    assert prediction.eta_days_to_warning == pytest.approx(1.0)


def client_for(db, settings, role="admin"):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_user] = lambda: AuthUser("test-user", "admin@example.com", "Test", role, ())
    return TestClient(app)


def test_admin_can_save_edit_reset_and_reclassify_without_sending(db):
    item = limit(db)
    settings = Settings(warning_threshold_percent=81)
    alert = Alert(fingerprint="previous", alert_type="threshold_exceeded", severity="warning", title="warning", message="old", service_name="compute", status="open", metadata_json={"limit_item_id": item.id})
    db.add(alert)
    db.commit()
    with client_for(db, settings) as client:
        values = {"warning_threshold_percent": 85, "critical_threshold_percent": 95}
        response = client.put("/api/service-thresholds/compute", json=values)
        assert response.status_code == 200
        assert response.json()["overrides"][0]["warning_threshold_percent"] == 85
        assert alert.status == "closed"
        assert client.get("/api/dashboard").json()["warning_limits"] == 0
        values["warning_threshold_percent"] = 80
        assert client.put("/api/service-thresholds/compute", json=values).status_code == 200
        assert client.get("/api/dashboard").json()["warning_limits"] == 1
        response = client.delete("/api/service-thresholds/compute")
        assert response.status_code == 200
        assert response.json()["overrides"] == []
        assert client.get("/api/dashboard").json()["warning_limits"] == 1
        assert db.get(ServiceAlertThreshold, "compute") is None
    assert [row.action for row in db.scalars(select(AuditLog))] == ["service_thresholds.updated", "service_thresholds.updated", "service_thresholds.reset"]


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_override_settings_require_admin(db, role):
    with client_for(db, Settings(), role) as client:
        assert client.get("/api/service-thresholds").status_code == 403
        assert client.put("/api/service-thresholds/compute", json={"warning_threshold_percent": 80, "critical_threshold_percent": 90}).status_code == 403
        assert client.delete("/api/service-thresholds/compute").status_code == 403


def test_api_rejects_invalid_thresholds_and_unknown_services(db):
    limit(db)
    db.commit()
    with client_for(db, Settings()) as client:
        for warning, critical in [(0, 90), (-1, 90), (91, 90), (80, 101)]:
            response = client.put("/api/service-thresholds/compute", json={"warning_threshold_percent": warning, "critical_threshold_percent": critical})
            assert response.status_code == 422
        assert client.put("/api/service-thresholds/typo", json={"warning_threshold_percent": 80, "critical_threshold_percent": 90}).status_code == 404
        assert client.get("/api/service-thresholds").json()["overrides"] == []
