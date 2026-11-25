"""Move per-message receipts out of JSON and generated columns."""
from alembic import op
from app.infrastructure.storage.conversation_counters import upgrade_physical_receipts

revision = "20261126_09"
down_revision = "20261126_08"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_physical_receipts(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a backup to use an older Core")
