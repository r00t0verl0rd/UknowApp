"""Automatic, transactional schema upgrades on every startup (including restore)."""
import logging
from datetime import UTC, datetime

from sqlalchemy import inspect, text

from app.core.database import Base, engine
from app.infrastructure.storage.conversation_counters import (
    upgrade_conversation_counters,
    upgrade_physical_receipts,
)

from .delivery_recovery import upgrade_delivery_recovery
from .delivery_routes import upgrade_delivery_routes
from .login_keys import migrate_login_keys
from .maintenance import cleanup_expired_records
from .performance_indexes import upgrade_performance_indexes
from .provider_channels import migrate_provider_channels, retire_legacy_schema
from .push_devices import upgrade_push_devices
from .remove_boards import remove_board_tables
from .volatile_events import retire_realtime_events

logger = logging.getLogger(__name__)

# Keep old identifiers permanently. New releases append explicit, tested steps.
MIGRATIONS = (
    ("2026-11-22-login-lookup", migrate_login_keys),
    ("2026-11-22-remove-interactive-boards", remove_board_tables),
    ("2026-11-26-delivery-routes", upgrade_delivery_routes),
    ("2026-11-26-delivery-recovery", upgrade_delivery_recovery),
    ("2026-11-26-conversation-counters", upgrade_conversation_counters),
    ("2026-11-26-provider-channels", migrate_provider_channels),
    ("2026-11-26-retire-legacy-provider", retire_legacy_schema),
    ("2026-11-26-push-devices", upgrade_push_devices),
    ("2026-11-26-performance-indexes", upgrade_performance_indexes),
    ("2026-11-26-volatile-events", retire_realtime_events),
    ("2026-11-26-physical-receipts", upgrade_physical_receipts),
)


def validate_schema(connection):
    inspector = inspect(connection)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise RuntimeError(f"Missing required table: {table.name}")
        columns = {c["name"] for c in inspector.get_columns(table.name)}
        missing = set(table.columns.keys()) - columns
        if missing:
            raise RuntimeError(f"Unsupported schema: {table.name} missing {', '.join(sorted(missing))}")
        connection.execute(table.select().limit(0)).close()


def upgrade_schema(connection):
    """Run on a caller-owned transaction. No nested commits or external I/O."""
    from app import models  # noqa: F401

    existing = set(inspect(connection).get_table_names())
    # Do not create a blank school over a partially copied business schema.
    required = {"users", "messages", "conversations", "assignments"}
    if existing & required and not required <= existing:
        raise RuntimeError("Incomplete UknowApp database: missing core tables")
    Base.metadata.create_all(bind=connection)
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
    ))
    applied = set(connection.scalars(text("SELECT version FROM schema_migrations")))
    for version, migrate in MIGRATIONS:
        if version in applied:
            continue
        logger.info("Applying database migration %s", version)
        migrate(connection)
        connection.execute(text(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :now)"
        ), {"version": version, "now": datetime.now(UTC)})
    validate_schema(connection)


def initialize_database():
    # SQLite's legacy driver does not start a transaction for DDL. BEGIN
    # IMMEDIATE ensures schema changes and markers roll back together.
    # PostgreSQL advisory lock serializes concurrent Core startups.
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(672612026)"))
        upgrade_schema(connection)
    cleanup_expired_records()
