"""Metadata for database-independent administration views."""

from sqlalchemy import text

from app.core.database import engine


def database_storage_details() -> tuple[str, int | None, int | None]:
    """Return engine, allocated bytes and reusable free-page bytes (when known)."""
    dialect = engine.dialect.name
    with engine.connect() as connection:
        if dialect == "sqlite":
            pages, size, free_pages = connection.execute(text(
                "SELECT p.page_count, s.page_size, f.freelist_count "
                "FROM pragma_page_count() AS p, pragma_page_size() AS s, "
                "pragma_freelist_count() AS f"
            )).one()
            return dialect, int(pages) * int(size), int(free_pages) * int(size)
        if dialect == "postgresql":
            size = connection.scalar(text("SELECT pg_database_size(current_database())"))
            return dialect, int(size) if size is not None else None, None
    return dialect, None, None


def database_storage_info() -> tuple[str, int | None]:
    """Retain the original allocated-size interface for existing callers."""
    dialect, size, _ = database_storage_details()
    return dialect, size
