"""Upgrade frozen schemas from actual earlier revisions, not generated current models."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text, update
from app.infrastructure.storage.message_metadata import metadata_with_field
from sqlalchemy.orm import Session

from app import migrations
from app.core import runtime_database
from app.migrations.runtime_split import migrate_push_subscriptions, migrate_transport_state
from app.core.security import hash_web_password, verify_web_password
from app.models import (Assignment, ConnectorDelivery, Conversation, ExternalEndpoint,
                        Message, MessengerAccount, PersonalMessage, PushSubscription, User)


VERSIONS = ("embedded", "websocket", "single_route", "pre_push")


def historical_schema(name):
    module_name = "legacy_schema_" + name
    if module_name not in sys.modules:
        path = Path(__file__).parent / "fixtures" / ("schema_" + name + ".py")
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules[module_name].Base.metadata


def seed(connection, name):
    meta = historical_schema(name)
    meta.create_all(connection)
    tables = meta.tables

    def insert(table, **values):
        connection.execute(tables[table].insert().values(**values))

    for ident, role, login, external in ((11, "teacher", "УЧИТЕЛЬ", 1001),
                                          (22, "student", "УЧЕНИК", 1002)):
        values = dict(id=ident, full_name=login, role=role, web_username=login,
                      web_password_hash=hash_web_password("legacy-test-password"))
        if "telegram_id" in tables["users"].c:
            values["telegram_id"] = external
        insert("users", **values)
    insert("assignments", id=31, teacher_id=11, student_id=22, active=True)
    insert("conversations", id=41, assignment_id=31, teacher_id=11, student_id=22)
    metadata = {"teacher_read_at":"2026-01-01T10:00:00Z",
                "media":{"archive_status":"stored","local_path":"media/example.txt","file_name":"example.txt"},
                "messenger_deliveries":{"telegram":{"status":"delivered","delivered":[
                    {"external_chat_id":"1002","external_message_id":"555"}],"errors":[]}}}
    values = dict(id=51, conversation_id=41, sender_id=11, sender_role="teacher",
                  text="История и файл", content_type="document",
                  metadata_json=json.dumps(metadata), client_message_id="legacy-client")
    if "source_message_id" in tables["messages"].c:
        values["source_message_id"] = 777
        values["destination_message_id"] = 555
    insert("messages", **values)
    insert("messages", id=52, conversation_id=41, sender_id=11, sender_role="teacher", text="Ожидает доставки")
    insert("personal_conversations", id=61, participant_id=22)
    insert("personal_messages", id=71, conversation_id=61, sender_id=22,
           sender_role="student", text="Личное сообщение", client_message_id="personal-client")
    for ident in (81,82):
        insert("push_subscriptions", id=ident, role="admin", endpoint=f"https://web.push.apple.com/legacy-{ident}",
               p256dh="p" * 32, auth="a" * 16)
    # Existing universal account must survive, even if legacy columns are present.
    insert("messenger_accounts", id=91, platform="telegram", user_id=11,
           external_user_id="1001", external_chat_id="1001")
    if name == "pre_push":
        insert("messenger_accounts", id=92, platform="telegram", user_id=22,
               external_user_id="1002", external_chat_id="1002")
        insert("external_endpoints", platform="telegram", user_id=22, chat_id="-10099", thread_id="17")
    elif "student_telegram_groups" in tables:
        insert("student_telegram_groups", student_id=22, chat_id=-10099, thread_id=17)
    # Distinct groups may reuse the same topic ID; every existing binding must survive.
    for ident in range(100, 132):
        external = 10000 + ident
        values = dict(id=ident, full_name=f"Student {ident}", role="student",
                      web_username=f"student-{ident}")
        if "telegram_id" in tables["users"].c:
            values["telegram_id"] = external
        insert("users", **values)
        insert("messenger_accounts", id=ident + 1000, platform="telegram", user_id=ident,
               external_user_id=str(external), external_chat_id=str(external))
        if "student_telegram_groups" in tables:
            insert("student_telegram_groups", student_id=ident, chat_id=-1000000-ident, thread_id=17)
        else:
            insert("external_endpoints", platform="telegram", user_id=ident,
                   chat_id=str(-1000000-ident), thread_id="17")
    if "bot_delivery_jobs" in tables:
        insert("bot_delivery_jobs", message_id=52, status="queued")
    if "connector_deliveries" in tables:
        insert("connector_deliveries", id="previous-delivery", message_id=51, recipient_id=22,
               platform="telegram", external_user_id="1002", chat_id="1002",
               thread_id=None if name=="single_route" else "", status="delivered", external_message_id="555")


def assert_preserved(connection, name):
    migrations.validate_schema(connection)
    with Session(bind=connection) as db:
        user = db.get(User, 11)
        assert user.web_login_key == "учитель"
        assert verify_web_password("legacy-test-password", user.web_password_hash)
        assert db.get(Assignment,31).active
        assert db.get(Conversation,41).student_id == 22
        row = db.get(Message,51)
        assert row.text == "История и файл"
        assert row.client_message_id == "legacy-client"
        metadata = json.loads(row.metadata_json)
        assert metadata["media"]["local_path"] == "media/example.txt"
        assert row.teacher_read_at == "2026-01-01T10:00:00Z"
        assert "teacher_read_at" not in metadata
        assert metadata["messenger_deliveries"]["telegram"]["delivered"][0]["external_message_id"] == "555"
        if name != "pre_push":
            assert metadata["legacy_source_message_id"] == "777"
        assert db.get(PersonalMessage,71).text == "Личное сообщение"
        personal_counts = connection.execute(text("SELECT admin_unread_count, participant_unread_count, last_message_at FROM personal_conversations WHERE id=61")).one()
        assert personal_counts[:2] == (1, 0) and personal_counts[2] is not None
        assert {a.external_user_id for a in db.scalars(select(MessengerAccount))} == (
            {"1001", "1002"} | {str(10000+i) for i in range(100, 132)})
        assert {row.user_id: (row.chat_id, row.thread_id) for row in db.scalars(
            select(ExternalEndpoint).where(ExternalEndpoint.platform == "telegram"))} == {
                22: ("-10099", "17"),
                **{i: (str(-1000000-i), "17") for i in range(100, 132)},
            }
        assert {s.id for s in db.scalars(select(PushSubscription))} == {81,82}
        assert all(s.synced_at is None for s in db.scalars(select(PushSubscription)))
        if name in ("websocket","single_route"):
            assert {j.chat_id for j in db.scalars(select(ConnectorDelivery).where(
                ConnectorDelivery.message_id==52))} == {"1002","-10099"}
        if name in ("single_route","pre_push"):
            assert db.get(ConnectorDelivery,"previous-delivery").external_message_id == "555"
            assert db.get(ConnectorDelivery,"previous-delivery").thread_id == ""
        assert db.query(Message).count() == 2
        chat = db.get(Conversation, 41)
        assert (chat.message_count, chat.teacher_unread_count, chat.student_unread_count, chat.admin_unread_count) == (2, 0, 2, 2)
    with Session(bind=connection) as db:
        db.execute(update(Message).where(Message.id == 51).values(metadata_json=metadata_with_field(
            db, Message.metadata_json, "migration_test_field", "2026-02-01T00:00:00Z")))
        db.flush()
        updated = json.loads(db.scalar(select(Message.metadata_json).where(Message.id == 51)))
        assert updated["migration_test_field"] == "2026-02-01T00:00:00Z"
        assert "student_read_at" not in updated
        db.execute(update(Message).where(Message.id == 51).values(student_read_at="2026-02-01T00:00:00Z"))
        assert updated["messenger_deliveries"]["telegram"]["status"] == "delivered"
        counts = db.execute(select(Conversation.message_count, Conversation.student_unread_count, Conversation.admin_unread_count).where(Conversation.id == 41)).one()
        assert counts == (2, 1, 1)
    inspector = inspect(connection)
    assert {"ix_connector_delivery_queue", "ix_connector_delivery_route_order"} <= {i["name"] for i in inspector.get_indexes("connector_deliveries")}
    assert {"ix_push_role_state", "ix_push_session_hash"} <= {i["name"] for i in inspector.get_indexes("push_subscriptions")}
    assert not {"teacher_panels","teacher_sessions","student_telegram_groups","bot_delivery_jobs","realtime_events"} & set(inspector.get_table_names())
    assert "telegram_id" not in {c["name"] for c in inspector.get_columns("users")}
    assert "source_message_id" not in {c["name"] for c in inspector.get_columns("messages")}
    assert set(connection.scalars(text("SELECT version FROM schema_migrations"))) >= {v for v,_ in migrations.MIGRATIONS}
    # Exercise the physical split after the historical upgrade, for both dialects.
    runtime = create_engine("sqlite://")
    try:
        runtime_database.RuntimeBase.metadata.create_all(runtime)
        migrate_push_subscriptions(connection, runtime)
        migrate_transport_state(connection, runtime)
        migrate_push_subscriptions(connection, runtime)
        migrate_transport_state(connection, runtime)
        assert not inspect(connection).has_table("push_subscriptions")
        with Session(runtime) as db:
            assert {row.endpoint for row in db.scalars(select(PushSubscription))} == {
                "https://web.push.apple.com/legacy-81", "https://web.push.apple.com/legacy-82"}
        migrations.validate_schema(connection)
    finally:
        runtime.dispose()


@pytest.mark.parametrize("name", VERSIONS)
def test_sqlite_previous_release_startup(tmp_path, monkeypatch, name):
    engine = create_engine("sqlite:///" + str(tmp_path / "old.sqlite3"))
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=ON")
        seed(c, name)
    monkeypatch.setattr(migrations, "engine", engine)
    monkeypatch.setattr(migrations, "cleanup_expired_records", lambda: None)
    migrations.initialize_database()
    migrations.initialize_database()  # all migrations must be idempotent
    with engine.begin() as c:
        assert_preserved(c, name)
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    engine.dispose()


@pytest.mark.parametrize("name", VERSIONS)
def test_postgres_previous_release(name):
    url = os.getenv("UKNOWAPP_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit disposable PostgreSQL CI database")
    engine = create_engine(url)
    schema = "migration_test_" + uuid4().hex
    try:
        with engine.begin() as c:
            c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            c.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            seed(c, name)
            migrations.upgrade_schema(c)
            migrations.upgrade_schema(c)
            assert_preserved(c, name)
            # Everything is scoped to this disposable schema.
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    finally:
        engine.dispose()


def test_sqlite_failed_upgrade_rolls_back_schema_and_markers(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "old.sqlite3"))
    with engine.begin() as c:
        seed(c, "embedded")
    def fail(connection):
        connection.execute(text("UPDATE messages SET text='must roll back' WHERE id=51"))
        raise RuntimeError("simulated migration error")
    monkeypatch.setattr(migrations, "engine", engine)
    monkeypatch.setattr(migrations, "MIGRATIONS", (*migrations.MIGRATIONS, ("failure-test",fail)))
    with pytest.raises(RuntimeError,match="simulated migration error"):
        migrations.initialize_database()
    with engine.connect() as c:
        assert c.scalar(text("SELECT text FROM messages WHERE id=51")) == "История и файл"
        assert c.scalar(text("SELECT telegram_id FROM users WHERE id=22")) == 1002
        assert inspect(c).has_table("student_telegram_groups")
        assert not inspect(c).has_table("schema_migrations")
        assert not inspect(c).has_table("connector_deliveries")
    engine.dispose()
