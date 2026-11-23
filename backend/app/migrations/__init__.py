"""Создание схемы и версионированные миграции БД."""

from datetime import UTC, datetime

from sqlalchemy import text

from app.core.database import create_tables, engine

from .login_keys import migrate_login_keys
from .maintenance import cleanup_expired_records
from .remove_boards import remove_board_tables

_LOGIN_VERSION = "2026-11-22-login-lookup"
_BOARDS_REMOVAL_VERSION = "2026-11-22-remove-interactive-boards"


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
    # Регистрируем модели до создания таблиц.
    from app import models  # noqa: F401

    create_tables()
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
        ))

    if not _is_applied(_LOGIN_VERSION):
        migrate_login_keys()
        _mark_applied(_LOGIN_VERSION)

    if not _is_applied(_BOARDS_REMOVAL_VERSION):
        remove_board_tables()
        _mark_applied(_BOARDS_REMOVAL_VERSION)

    cleanup_expired_records()
