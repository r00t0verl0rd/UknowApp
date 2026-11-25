"""Indexes for delivery and push hot paths."""
from alembic import op
from app.migrations.performance_indexes import upgrade_performance_indexes

revision = "20261126_06"
down_revision = "20261126_05"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_performance_indexes(op.get_bind())


def downgrade():
    for table, name in (
        ("push_subscriptions", "ix_push_role_state"), ("push_subscriptions", "ix_push_session_hash"),
        ("connector_deliveries", "ix_connector_delivery_queue"),
        ("connector_deliveries", "ix_connector_delivery_route_order"),
        ("connector_deletions", "ix_connector_deletion_queue"),
    ):
        op.drop_index(name, table_name=table)
