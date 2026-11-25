"""Retire the redundant persistent SSE hint table."""
from alembic import op
from app.migrations.volatile_events import retire_realtime_events

revision = "20261126_07"
down_revision = "20261126_06"
branch_labels = None
depends_on = None


def upgrade():
    retire_realtime_events(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a backup to use an older Core")
