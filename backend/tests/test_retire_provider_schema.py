"""Upgrade a legacy database while preserving identities, group bindings and message history."""
import json
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models import User, Message, MessengerAccount, ExternalEndpoint
from app.migrations.provider_channels import migrate_provider_channels, retire_legacy_schema
from helpers import create_conversation


def test_migrate_legacy_records_and_drop_old_columns(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.sqlite3"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        teacher = User(full_name="Teacher",role="teacher")
        student = User(full_name="Student",role="student")
        db.add_all([teacher,student])
        db.commit()
        chat = create_conversation(db, teacher.id, student.id)
        row = Message(conversation_id=chat.id,sender_id=teacher.id,sender_role="teacher",text="old")
        db.add(row)
        db.commit()
        user_id, message_id = student.id, row.id
    with engine.begin() as c:
        c.execute(text("ALTER TABLE users ADD COLUMN telegram_id BIGINT"))
        c.execute(text("CREATE UNIQUE INDEX ix_users_telegram_id ON users(telegram_id)"))
        c.execute(text("UPDATE users SET telegram_id=123 WHERE id=:id"), {"id":user_id})
        c.execute(text("ALTER TABLE messages ADD COLUMN source_message_id BIGINT"))
        c.execute(text("ALTER TABLE messages ADD COLUMN destination_message_id BIGINT"))
        c.execute(text("UPDATE messages SET destination_message_id=456 WHERE id=:id"), {"id":message_id})
        c.execute(text("CREATE TABLE student_telegram_groups(student_id INTEGER PRIMARY KEY, chat_id BIGINT, thread_id BIGINT)"))
        c.execute(text("INSERT INTO student_telegram_groups VALUES (:id,-1000,9)"), {"id":user_id})
        c.execute(text("CREATE TABLE teacher_panels (teacher_id INTEGER PRIMARY KEY)"))
        c.execute(text("CREATE TABLE teacher_sessions (teacher_id INTEGER PRIMARY KEY)"))
        migrate_provider_channels(c)
        retire_legacy_schema(c)
        assert "telegram_id" not in {i["name"] for i in inspect(c).get_columns("users")}
        assert "destination_message_id" not in {i["name"] for i in inspect(c).get_columns("messages")}
        assert not {"student_telegram_groups","teacher_panels","teacher_sessions"} & set(inspect(c).get_table_names())
    with Session(engine) as db:
        assert db.query(MessengerAccount).one().external_user_id == "123"
        endpoint = db.query(ExternalEndpoint).one()
        assert (endpoint.chat_id,endpoint.thread_id) == ("-1000","9")
        assert db.get(Message,message_id).text == "old"
        assert json.loads(db.get(Message,message_id).metadata_json)["legacy_destination_message_id"] == "456"
