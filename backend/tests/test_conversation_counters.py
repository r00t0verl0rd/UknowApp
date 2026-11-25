"""Exact summaries including holes, bulk deletes and rollback."""
from sqlalchemy import delete, event, insert, select, update
from app.models import Conversation, Message
from app.modules.conversations.service import conversation_dicts, conversation_event_summaries
from app.modules.messaging.read_state import mark_conversation_read
from helpers import create_conversation


def test_counters_preserve_sparse_read_receipts_and_rollback(api):
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        db.execute(insert(Message), [
            dict(conversation_id=chat.id, sender_id=users["student-one"], sender_role="student", text="old unread"),
            dict(conversation_id=chat.id, sender_id=users["student-one"], sender_role="student", text="visible"),
            dict(conversation_id=chat.id, sender_id=users["teacher-one"], sender_role="teacher", text="teacher"),
            dict(conversation_id=chat.id, sender_id=users["teacher-one"], sender_role="admin", text="admin"),
        ])
        db.commit()
        ids = db.scalars(select(Message.id).order_by(Message.id)).all()
        def counts():
            result = conversation_event_summaries(db, chat)
            return tuple(result[r]["unread_count"] for r in ("teacher","student","admin")), result["teacher"]["message_count"]
        assert counts() == ((3, 2, 3), 4)
        statements = []
        def capture(*args):
            statements.append(args[2])
        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            mark_conversation_read(db, chat, {"role":"teacher"}, 0, [ids[1]])
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)
        assert not any("json_extract" in sql.lower() for sql in statements)
        assert not any("metadata_json" in sql.lower().split("where")[0] for sql in statements if sql.lstrip().lower().startswith("update messages"))
        assert db.scalar(select(Message.metadata_json).where(Message.id == ids[1])) == "{}"
        assert db.scalar(select(Message.teacher_read_at).where(Message.id == ids[1])) is not None
        assert counts() == ((2, 2, 2), 4)
        assert db.scalar(select(Conversation.teacher_last_read_id).where(Conversation.id == chat.id)) == 0
        mark_conversation_read(db, chat, {"role":"teacher"}, 0, [ids[1]])
        assert counts() == ((2, 2, 2), 4)
        db.execute(update(Message).where(Message.id == ids[0]).values(metadata_json='{"delivery":"ok"}'))
        db.commit()
        assert counts() == ((2, 2, 2), 4)
        db.execute(delete(Message).where(Message.id.in_([ids[0], ids[3]])))
        assert counts() == ((0, 1, 1), 2)
        assert conversation_dicts(db,[chat])[0]["last_message"] == "teacher"
        assert db.scalar(select(Conversation.teacher_last_read_id).where(Conversation.id == chat.id)) == ids[2]
        db.rollback()
        assert counts() == ((2, 2, 2), 4)
        assert conversation_dicts(db,[chat])[0]["last_message"] == "admin"
        db.execute(delete(Message).where(Message.conversation_id == chat.id))
        db.commit()
        assert counts() == ((0, 0, 0), 0)
        assert conversation_dicts(db,[chat])[0]["last_message_at"] is None


def test_upgrade_generated_receipts_preserves_metadata_and_counters(tmp_path):
    # Reproduce the schema that already exists in test after 20261126_08.
    import json
    from sqlalchemy import create_engine, inspect, text
    from app.infrastructure.storage.conversation_counters import upgrade_conversation_counters, upgrade_physical_receipts
    engine = create_engine("sqlite:///" + str(tmp_path / "old.db"))
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql("CREATE TABLE conversations (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, sender_role TEXT, created_at TEXT, metadata_json TEXT)")
        connection.exec_driver_sql("CREATE INDEX ix_messages_conversation_id_id ON messages(conversation_id,id)")
        connection.exec_driver_sql("CREATE INDEX ix_messages_conversation_created_id ON messages(conversation_id,created_at,id)")
        connection.exec_driver_sql("INSERT INTO conversations VALUES (1)")
        connection.execute(text("INSERT INTO messages VALUES (1,1,'student','2026-01-01',:metadata)"),
                           {"metadata":json.dumps({"teacher_read_at":"2026-02-01","media":{"file":"keep"}})})
        connection.execute(text("INSERT INTO messages VALUES (2,1,'student','2026-01-02',:metadata)"),
                           {"metadata":json.dumps({"messenger_deliveries":{"telegram":{"status":"delivered"}}})})
        upgrade_conversation_counters(connection)
        assert any(col.get("computed") for col in inspect(connection).get_columns("messages"))
        upgrade_physical_receipts(connection)
        assert not any(col.get("computed") for col in inspect(connection).get_columns("messages"))
        row=connection.execute(text("SELECT teacher_read_at,metadata_json FROM messages WHERE id=1")).one()
        assert row[0]=="2026-02-01" and json.loads(row[1])=={"media":{"file":"keep"}}
        assert connection.execute(text("SELECT message_count,teacher_unread_count,teacher_last_read_id,last_message_id FROM conversations")).one()==(2,1,1,2)
        connection.exec_driver_sql("UPDATE messages SET teacher_read_at='2026-03-01' WHERE id=2")
        assert connection.execute(text("SELECT teacher_unread_count,teacher_last_read_id FROM conversations")).one()==(0,2)
        assert json.loads(connection.scalar(text("SELECT metadata_json FROM messages WHERE id=2")))["messenger_deliveries"]["telegram"]["status"]=="delivered"
    engine.dispose()


def test_admin_delivery_hint_does_not_reach_participants(api):
    import json
    from app.event_hub import current_event_id, replay_chat_updates
    from app.modules.conversations.service import publish_conversation_update
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db,users["teacher-one"],users["student-one"])
        cursor = current_event_id()
        status = {"id":123,"metadata":{"messenger_deliveries":{"telegram":{"status":"delivered","external_chat_id":"internal"}}}}
        publish_conversation_update(db,chat,action="delivery",message_id=123,admin_message_status=status)
        admin = json.loads(replay_chat_updates(db,{"role":"admin"},cursor)[0][1])
        assert admin["message_status"] == status
        assert "summary" not in admin
        assert not replay_chat_updates(db,{"role":"teacher","user_id":chat.teacher_id},cursor)
        assert not replay_chat_updates(db,{"role":"student","user_id":chat.student_id},cursor)


def test_summary_no_history_scan_even_with_100k_messages(api):
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db,users["teacher-one"],users["student-one"])
        for start in range(0,100000,2000):
            db.execute(insert(Message),[dict(conversation_id=chat.id,sender_id=chat.student_id,
                sender_role="student",text=str(i),teacher_read_at="2026-01-01" if i<99999 else None)
                for i in range(start,start+2000)])
        db.commit()
        statements=[]
        def capture(*args):
            statements.append(args[2])
        event.listen(db.get_bind(),"before_cursor_execute",capture)
        try:
            for _ in range(5):
                summary=conversation_event_summaries(db,chat)
                assert summary["teacher"]["message_count"]==100000
                assert summary["teacher"]["unread_count"]==1
                assert summary["teacher"]["last_message"]=="99999"
            assert not any("group by" in q.lower() or "count(" in q.lower() or "json_extract" in q.lower() or "sum(" in q.lower() for q in statements)
        finally:
            event.remove(db.get_bind(),"before_cursor_execute",capture)


def test_sql_trigger_references_reject_arbitrary_expressions():
    import pytest
    from app.infrastructure.storage.conversation_counters import cursor_assignments, latest_id

    for generator in (cursor_assignments, latest_id):
        for reference in ("NEW.conversation_id", "OLD.conversation_id", "conversations.id"):
            assert reference in generator(reference)
        with pytest.raises(ValueError, match="Unknown SQL conversation reference"):
            generator("untrusted_expression")
