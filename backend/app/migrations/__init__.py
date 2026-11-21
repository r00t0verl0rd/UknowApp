"""Explicit database initialization and one-time, versioned upgrades."""

from datetime import UTC, datetime
from sqlalchemy import text
from app.core.database import create_tables, engine, is_sqlite
from .legacy import migrate_legacy_schema
from .login_keys import migrate_login_keys
from .maintenance import cleanup_expired_records

_LEGACY_VERSION = "2026-11-22-legacy-schema"
_LOGIN_VERSION = "2026-11-22-login-lookup"


def _is_applied(version: str) -> bool:
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": version},
        ) is not None


def _mark_applied(version: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :now)"),
            {"version": version, "now": datetime.now(UTC)},
        )


def initialize_database() -> None:
    # Register tables explicitly at the application composition boundary.
    from app import models  # noqa: F401

    create_tables()
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
        ))

    # Legacy DDL contains SQLite-specific pragmas and table rebuilds.
    # On a fresh PostgreSQL database, create_tables() already creates the schema.
    if not _is_applied(_LEGACY_VERSION):
        if is_sqlite:
            migrate_legacy_schema()
        _mark_applied(_LEGACY_VERSION)
    if not _is_applied(_LOGIN_VERSION):
        migrate_login_keys()
        _mark_applied(_LOGIN_VERSION)

    cleanup_expired_records()
