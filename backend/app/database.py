from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # create_all does not add columns to an existing database. Keep this small,
    # idempotent migration here so existing local SQLite installs are upgraded
    # automatically when the backend starts.
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("teacher_panels")
        }
        migrations = {
            "keyboard_version": "INTEGER NOT NULL DEFAULT 0",
            "keyboard_signature": "VARCHAR(64)",
            "page_index": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, definition in migrations.items():
            if column_name not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE teacher_panels ADD COLUMN "
                        + column_name
                        + " "
                        + definition
                    )
                )
