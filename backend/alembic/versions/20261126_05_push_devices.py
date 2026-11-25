"""Per-device Web Push registration and diagnostics."""
from alembic import op
from app.migrations.push_devices import upgrade_push_devices

revision = "20261126_05"
down_revision = "20261126_04"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_push_devices(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a verified backup to roll back this migration")
