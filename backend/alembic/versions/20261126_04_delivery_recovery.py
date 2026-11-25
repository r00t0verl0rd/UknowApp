"""Track publication and claim times for recovery."""
from alembic import op
from app.migrations.delivery_recovery import upgrade_delivery_recovery

revision = "20261126_04"
down_revision = "20261126_03"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_delivery_recovery(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a backup to preserve recovery timestamps")
