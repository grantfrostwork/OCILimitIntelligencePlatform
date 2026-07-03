from __future__ import annotations

from datetime import timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import LimitItem, LimitSnapshot, TrendPrediction, utcnow


MAX_PROJECTION_DAYS = 3650.0


class TrendService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def calculate_for_limit(self, limit_item: LimitItem, lookback_hours: int = 168) -> TrendPrediction | None:
        since = utcnow() - timedelta(hours=lookback_hours)
        snapshots = list(
            self.db.scalars(
                select(LimitSnapshot)
                .where(LimitSnapshot.limit_item_id == limit_item.id)
                .where(LimitSnapshot.collected_at >= since)
                .where(LimitSnapshot.used.is_not(None))
                .where(LimitSnapshot.allowed_limit.is_not(None))
                .order_by(LimitSnapshot.collected_at.asc())
            )
        )
        if len(snapshots) < self.settings.trend_min_points:
            return None

        xs = [(snap.collected_at - snapshots[0].collected_at).total_seconds() / 86400 for snap in snapshots]
        ys = [float(snap.used or 0) for snap in snapshots]
        allowed = snapshots[-1].allowed_limit
        if not allowed or allowed <= 0:
            return None

        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator == 0:
            return None
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
        warning_value = allowed * (self.settings.warning_threshold_percent / 100.0)

        eta_days = None
        projected_at = None
        confidence = "low"
        summary = "Usage is flat or declining."
        latest_used = ys[-1]

        if slope > 0 and latest_used < warning_value:
            candidate_eta_days = (warning_value - latest_used) / slope
            if candidate_eta_days <= MAX_PROJECTION_DAYS:
                eta_days = candidate_eta_days
                projected_at = utcnow() + timedelta(days=eta_days)
                confidence = "medium" if len(snapshots) >= 8 else "low"
                summary = f"Usage is increasing by {slope:.2f} units/day."
            else:
                summary = (
                    f"Usage is increasing by {slope:.2f} units/day, but the warning threshold "
                    "is beyond the 10-year projection horizon."
                )
        elif latest_used >= warning_value:
            eta_days = 0
            projected_at = utcnow()
            confidence = "high"
            summary = "Usage is already above the warning threshold."

        prediction = TrendPrediction(
            limit_item_id=limit_item.id,
            lookback_hours=lookback_hours,
            slope_used_per_day=slope,
            projected_breach_at=projected_at,
            eta_days_to_warning=eta_days,
            confidence=confidence,
            summary=summary,
        )
        self.db.add(prediction)
        return prediction

    def calculate_recent(self, limit_ids: list[str] | None = None) -> list[TrendPrediction]:
        query = select(LimitItem)
        if limit_ids:
            query = query.where(LimitItem.id.in_(limit_ids))
        items = list(self.db.scalars(query))
        predictions: list[TrendPrediction] = []
        for item in items:
            prediction = self.calculate_for_limit(item)
            if prediction:
                predictions.append(prediction)
        return predictions

    def latest_predictions(self, limit: int = 10) -> list[TrendPrediction]:
        return list(
            self.db.scalars(
                select(TrendPrediction).order_by(desc(TrendPrediction.calculated_at)).limit(limit)
            )
        )
