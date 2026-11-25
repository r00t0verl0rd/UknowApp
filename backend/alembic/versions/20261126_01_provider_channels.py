"""Generic external endpoints and per-recipient delivery outbox."""
import sqlalchemy as sa
from alembic import op

revision = "20261126_01"
down_revision = "20261125_01"
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "external_endpoints" not in tables:
        op.create_table("external_endpoints",
            sa.Column("platform", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("chat_id", sa.String(255), nullable=False),
            sa.Column("thread_id", sa.String(255), nullable=False),
            sa.Column("preferred", sa.Boolean, nullable=False),
            sa.UniqueConstraint("platform", "chat_id", "thread_id"))
    if "connector_deliveries" not in tables:
        op.create_table("connector_deliveries",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("recipient_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("external_user_id", sa.String(255), nullable=False),
            sa.Column("chat_id", sa.String(255), nullable=False),
            sa.Column("thread_id", sa.String(255)),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("external_message_id", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("message_id", "platform", "recipient_id"))
        for name in ("message_id", "recipient_id", "platform", "status"):
            op.create_index("ix_connector_deliveries_" + name, "connector_deliveries", [name])


def downgrade():
    raise RuntimeError("Restore a backup to preserve delivery history")
