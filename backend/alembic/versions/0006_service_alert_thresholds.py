"""Optional per-service warning/critical thresholds; empty means inherit defaults."""
import sqlalchemy as sa
from alembic import op

revision = "0006_service_alert_thresholds"
down_revision = "0005_alert_settings"
branch_labels = None
depends_on = None


def upgrade():
    # The legacy initial migration creates tables from current ORM metadata.
    if sa.inspect(op.get_bind()).has_table("service_alert_thresholds"):
        return
    op.create_table(
        "service_alert_thresholds",
        sa.Column("service_name", sa.String(128), primary_key=True),
        sa.Column("warning_threshold_percent", sa.Float(), nullable=False),
        sa.Column("critical_threshold_percent", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("warning_threshold_percent > 0 AND warning_threshold_percent <= 100", name="ck_service_warning_range"),
        sa.CheckConstraint("critical_threshold_percent >= warning_threshold_percent AND critical_threshold_percent <= 100", name="ck_service_threshold_order"),
    )


def downgrade():
    op.drop_table("service_alert_thresholds")
