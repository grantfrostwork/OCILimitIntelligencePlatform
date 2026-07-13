"""persist limit alert mute preferences

Revision ID: 0004_limit_alert_muting
Revises: 0003_scan_schedule_metrics
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op


revision = "0004_limit_alert_muting"
down_revision = "0003_scan_schedule_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("limit_items")}
    additions = (
        sa.Column("is_muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("muted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mute_reason", sa.Text(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("limit_items", column)

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("limit_items")}
    if "ix_limit_items_is_muted" not in indexes:
        op.create_index("ix_limit_items_is_muted", "limit_items", ["is_muted"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("limit_items")}
    if "ix_limit_items_is_muted" in indexes:
        op.drop_index("ix_limit_items_is_muted", table_name="limit_items")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("limit_items")}
    for column in ("mute_reason", "muted_at", "is_muted"):
        if column in columns:
            op.drop_column("limit_items", column)
