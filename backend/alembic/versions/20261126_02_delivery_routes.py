"""Multi-address delivery and durable external deletion."""
from alembic import op

from app.migrations.delivery_routes import upgrade_delivery_routes
from app.models import ConnectorDeletion

revision = "20261126_02"
down_revision = "20261126_01"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    upgrade_delivery_routes(connection)
    ConnectorDeletion.__table__.create(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("Restore a backup to preserve per-address delivery history")
