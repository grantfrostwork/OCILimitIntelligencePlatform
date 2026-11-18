"""Persist editable alert delivery settings."""

import sqlalchemy as sa
from alembic import op

revision = "0005_alert_settings"
down_revision = "0004_limit_alert_muting"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("notification_config")}
    columns = [
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warning_threshold_percent", sa.Float(), nullable=False, server_default="90"),
        sa.Column("critical_threshold_percent", sa.Float(), nullable=False, server_default="98"),
        sa.Column(
            "subject_template",
            sa.Text(),
            nullable=False,
            server_default="OCI limit increase needed: {service} / {limit}",
        ),
        sa.Column(
            "message_template",
            sa.Text(),
            nullable=False,
            server_default="{message}\nPlease review capacity and request a limit increase.\n{app_url}",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column("notification_config", column)


def downgrade():
    for name in [
        "last_error",
        "message_template",
        "subject_template",
        "critical_threshold_percent",
        "warning_threshold_percent",
        "enabled",
    ]:
        op.drop_column("notification_config", name)
