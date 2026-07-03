from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import LimitItem, LimitSnapshot, utcnow
from app.services.trends import TrendService


def test_projection_ignores_breach_dates_beyond_ten_year_horizon() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    item = LimitItem(
        region="us-ashburn-1",
        compartment_ocid="tenancy",
        service_name="compute",
        limit_name="example-count",
        scope_type="REGION",
        subscription_id="",
    )
    db.add(item)
    db.flush()
    started_at = utcnow() - timedelta(minutes=3)
    for index, used in enumerate((1.0, 1.000001, 1.000002, 1.000003)):
        db.add(
            LimitSnapshot(
                limit_item_id=item.id,
                scan_run_id="scan-id",
                collected_at=started_at + timedelta(minutes=index),
                allowed_limit=100.0,
                used=used,
                collection_status="ok",
            )
        )
    db.commit()

    prediction = TrendService(db, Settings(trend_min_points=4)).calculate_for_limit(item)

    assert prediction is not None
    assert prediction.slope_used_per_day is not None
    assert prediction.slope_used_per_day > 0
    assert prediction.eta_days_to_warning is None
    assert prediction.projected_breach_at is None
    assert "10-year projection horizon" in prediction.summary
