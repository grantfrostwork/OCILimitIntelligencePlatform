"""multi-region scanning

Revision ID: 0002_multi_region_scanning
Revises: 0001_initial_schema
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_multi_region_scanning"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    scan_run_columns = {column["name"] for column in inspector.get_columns("scan_runs")}
    scan_run_additions = (
        sa.Column("trigger", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("api_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_throttle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "api_concurrency_wait_seconds", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("api_retry_sleep_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("global_limits_skipped", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in scan_run_additions:
        if column.name not in scan_run_columns:
            op.add_column("scan_runs", column)

    scan_run_indexes = {index["name"] for index in inspector.get_indexes("scan_runs")}
    for index_name, column_name in (
        ("ix_scan_runs_trigger", "trigger"),
        ("ix_scan_runs_batch_id", "batch_id"),
    ):
        if index_name not in scan_run_indexes:
            op.create_index(index_name, "scan_runs", [column_name])

    if "monitored_regions" not in table_names:
        op.create_table(
            "monitored_regions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("region_name", sa.String(length=64), nullable=False),
            sa.Column("region_key", sa.String(length=16), nullable=True),
            sa.Column("subscription_status", sa.String(length=32), nullable=False),
            sa.Column("is_home_region", sa.Boolean(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("stagger_order", sa.Integer(), nullable=False),
            sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("region_name"),
        )
        op.create_index("ix_monitored_regions_region_name", "monitored_regions", ["region_name"])
        op.create_index(
            "ix_monitored_regions_subscription_status",
            "monitored_regions",
            ["subscription_status"],
        )
        op.create_index("ix_monitored_regions_is_enabled", "monitored_regions", ["is_enabled"])

    if "scan_requests" not in table_names:
        op.create_table(
            "scan_requests",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("batch_id", sa.String(length=36), nullable=False),
            sa.Column("region", sa.String(length=64), nullable=False),
            sa.Column("trigger", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts_completed", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("last_scan_run_id", sa.String(length=36), nullable=True),
            sa.Column("error_summary", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_scan_requests_batch_id", "scan_requests", ["batch_id"])
        op.create_index("ix_scan_requests_region", "scan_requests", ["region"])
        op.create_index("ix_scan_requests_trigger", "scan_requests", ["trigger"])
        op.create_index("ix_scan_requests_status", "scan_requests", ["status"])
        op.create_index("ix_scan_requests_not_before", "scan_requests", ["not_before"])
        op.create_index(
            "ix_scan_requests_last_scan_run_id", "scan_requests", ["last_scan_run_id"]
        )


def downgrade() -> None:
    op.drop_table("scan_requests")
    op.drop_table("monitored_regions")
    op.drop_index("ix_scan_runs_batch_id", table_name="scan_runs")
    op.drop_index("ix_scan_runs_trigger", table_name="scan_runs")
    for column in (
        "global_limits_skipped",
        "api_retry_sleep_seconds",
        "api_concurrency_wait_seconds",
        "api_throttle_count",
        "api_retry_count",
        "api_request_count",
        "max_attempts",
        "attempt",
        "batch_id",
        "trigger",
    ):
        op.drop_column("scan_runs", column)
