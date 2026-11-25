"""Durable connector event receipts and web delivery outbox."""
import sqlalchemy as sa
from alembic import op

revision = "20261125_01"
down_revision = "20261124_01"
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "bot_event_receipts" not in tables:
        op.create_table(
            "bot_event_receipts",
            sa.Column("platform", sa.String(32), primary_key=True),
            sa.Column("event_id", sa.String(200), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "bot_delivery_jobs" not in tables:
        op.create_table(
            "bot_delivery_jobs",
            sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_bot_delivery_jobs_status", "bot_delivery_jobs", ["status"])


def downgrade():
    raise RuntimeError("Restore a backup to preserve gateway queues and event receipts")
