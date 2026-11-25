"""Backfill exact conversation aggregates."""
from alembic import op
from app.infrastructure.storage.conversation_counters import upgrade_conversation_counters

revision = "20261126_08"
down_revision = "20261126_07"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_conversation_counters(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a backup to use an older Core")
