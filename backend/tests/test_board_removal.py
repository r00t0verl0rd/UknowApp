"""Проверки полного удаления старого функционала досок."""

from sqlalchemy import create_engine, inspect, text

from app.core.database import Base
from app.main import app
from app.migrations import remove_boards


def test_board_routes_and_models_are_removed():
    assert "graph_objects" not in Base.metadata.tables
    assert "graph_object_deletions" not in Base.metadata.tables
    assert not any(
        getattr(route, "path", "").startswith("/api/admin/boards")
        for route in app.routes
    )


def test_legacy_board_tables_are_removed_idempotently(monkeypatch):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE graph_objects (id INTEGER PRIMARY KEY, "
                "parent_id INTEGER REFERENCES graph_objects(id) ON DELETE CASCADE)"
            ))
            connection.execute(text("CREATE TABLE graph_object_deletions (object_key TEXT PRIMARY KEY)"))
            connection.execute(text("INSERT INTO graph_objects (id) VALUES (1)"))
            connection.execute(text("INSERT INTO graph_objects (id, parent_id) VALUES (2, 1)"))
        monkeypatch.setattr(remove_boards, "engine", engine)
        remove_boards.remove_board_tables()
        remove_boards.remove_board_tables()
        tables = inspect(engine).get_table_names()
        assert "graph_objects" not in tables
        assert "graph_object_deletions" not in tables
    finally:
        engine.dispose()
