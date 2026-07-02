from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.services.alerts import AlertService


class ExistingNotificationSdk:
    def __init__(self) -> None:
        self.created_topic = False
        self.created_subscription = False

    def list_topics(self, compartment_id: str, *, region: str, name: str | None = None):
        return [
            SimpleNamespace(
                name=name,
                lifecycle_state="ACTIVE",
                topic_id="ocid1.onstopic.test",
            )
        ]

    def create_topic(self, *args, **kwargs):
        self.created_topic = True
        raise AssertionError("Existing topic should be reused")

    def list_subscriptions(self, compartment_id: str, topic_id: str, *, region: str):
        return [
            SimpleNamespace(
                endpoint="grant.frost@oracle.com",
                lifecycle_state="ACTIVE",
            )
        ]

    def create_subscription(self, *args, **kwargs):
        self.created_subscription = True
        raise AssertionError("Existing subscription should be reused")


def test_notification_topic_and_subscription_are_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    sdk = ExistingNotificationSdk()
    settings = Settings(
        oci_tenancy_ocid="tenancy",
        lip_enable_notifications=True,
        lip_notification_emails=["grant.frost@oracle.com"],
    )

    config = AlertService(db, settings, sdk=sdk).ensure_notification_config()

    assert config.topic_id == "ocid1.onstopic.test"
    assert config.subscription_status == {"grant.frost@oracle.com": "ACTIVE"}
    assert sdk.created_topic is False
    assert sdk.created_subscription is False
