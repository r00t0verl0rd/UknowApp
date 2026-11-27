"""Smoke tests for database-agnostic storage reporting."""

from sqlalchemy import create_engine, text

from app.infrastructure.storage import database_info


def test_sqlite_storage_bytes_include_schema(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'storage.db'}")
    try:
        with engine.begin() as db:
            db.execute(text("CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)"))
        monkeypatch.setattr(database_info, "engine", engine)
        driver, size = database_info.database_storage_info()
        assert driver == "sqlite"
        assert size > 0
        assert size % 512 == 0
    finally:
        engine.dispose()


def test_postgres_size_query_avoids_sqlite_pragmas(monkeypatch):
    class Dialect:
        name = "postgresql"

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def scalar(self, query):
            assert str(query) == "SELECT pg_database_size(current_database())"
            return 123456

    class Engine:
        dialect = Dialect()

        def connect(self):
            return Connection()

    monkeypatch.setattr(database_info, "engine", Engine())
    assert database_info.database_storage_info() == ("postgresql", 123456)


def test_sqlite_allocated_size_does_not_shrink_after_delete(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'freelist.db'}")
    try:
        monkeypatch.setattr(database_info, "engine", engine)
        with engine.begin() as db:
            db.execute(text("PRAGMA auto_vacuum=NONE"))
            db.execute(text("CREATE TABLE example (id INTEGER PRIMARY KEY, value BLOB)"))
            db.execute(text("INSERT INTO example (value) VALUES (zeroblob(524288))"))
        driver, before = database_info.database_storage_info()
        with engine.begin() as db:
            db.execute(text("DELETE FROM example"))
        _, after = database_info.database_storage_info()
        assert driver == "sqlite"
        assert after == before
    finally:
        engine.dispose()
