"""Metadata for database-independent administration views."""

from sqlalchemy import text
from app.core.database import engine


def database_storage_info() -> tuple[str, int | None]:
    """Database engine name and actual storage size (including schema/indexes)."""
    dialect = engine.dialect.name
    with engine.connect() as connection:
        if dialect == "sqlite":
            pages = connection.scalar(text("PRAGMA page_count"))
            size = connection.scalar(text("PRAGMA page_size"))
            return dialect, int(pages) * int(size)
        if dialect == "postgresql":
            size = connection.scalar(text("SELECT pg_database_size(current_database())"))
            return dialect, int(size) if size is not None else None
    return dialect, None
