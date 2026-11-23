"""Initialize the schema and exercise ORM storage on both supported dialects."""

import pytest
from sqlalchemy import inspect, select

from app.core.database import SessionLocal, engine
from app.models import User


@pytest.fixture(scope="module", autouse=True)
def require_prepared_test_database():
    # Never migrate a database implicitly from tests. CI explicitly runs Alembic
    # on isolated databases; the general test suite has no prepared DB.
    if not inspect(engine).has_table("alembic_version"):
        pytest.skip("Dialect smoke tests require a manually migrated test DB")


def test_tables_exist_after_manual_migration():
    inspector = inspect(engine)
    assert inspector.has_table("users")
    assert inspector.has_table("messages")
    assert inspector.has_table("conversations")
    assert inspector.has_table("alembic_version")


def test_user_round_trip_with_rollback():
    with SessionLocal() as session:
        user = User(full_name="Database CI Test", role="student")
        session.add(user)
        session.flush()
        assert session.scalar(select(User).where(User.id == user.id)).full_name == "Database CI Test"
        session.rollback()


def test_text_metadata_reads_match_on_both_dialects():
    from sqlalchemy import literal

    from app.infrastructure.storage.message_metadata import metadata_value

    with SessionLocal() as db:
        value = literal('{"client_message_id":"legacy-id","teacher_read_at":null}')
        fields = ["client_message_id", "teacher_read_at", "student_read_at"]
        assert db.execute(select(*(metadata_value(db, value, key) for key in fields))).one() == (
            "legacy-id", None, None,
        )
