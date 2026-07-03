"""scan schedule and event-driven metrics publishing

Revision ID: 0003_scan_schedule_metrics
Revises: 0002_multi_region_scanning
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from alembic import op


revision = "0003_scan_schedule_metrics"
down_revision = "0002_multi_region_scanning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    scan_run_columns = {column["name"] for column in inspector.get_columns("scan_runs")}
    additions = (
        sa.Column(
            "metrics_publish_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("metrics_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_publish_error", sa.Text(), nullable=True),
    )
    for column in additions:
        if column.name not in scan_run_columns:
            op.add_column("scan_runs", column)

    if "scan_schedule" not in table_names:
        op.create_table(
            "scan_schedule",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("interval_minutes", sa.Integer(), nullable=False),
            sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_scan_schedule_next_scan_at",
            "scan_schedule",
            ["next_scan_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_scan_schedule_next_scan_at", table_name="scan_schedule")
    op.drop_table("scan_schedule")
    op.drop_column("scan_runs", "metrics_publish_error")
    op.drop_column("scan_runs", "metrics_published_at")
    op.drop_column("scan_runs", "metrics_publish_status")
