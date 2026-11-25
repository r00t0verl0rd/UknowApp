"""Retire provider-specific columns and UI tables after migrating links."""
from alembic import op
from sqlalchemy import inspect, text
from app.migrations.provider_channels import migrate_provider_channels, retire_legacy_schema

revision = "20261126_03"
down_revision = "20261126_02"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    already_imported = inspect(connection).has_table("schema_migrations") and connection.scalar(
        text("SELECT 1 FROM schema_migrations WHERE version = '2026-11-26-provider-channels'"))
    if not already_imported:
        migrate_provider_channels(connection)
    retire_legacy_schema(connection)


def downgrade():
    raise RuntimeError("Restore a verified backup to recover retired provider tables")
