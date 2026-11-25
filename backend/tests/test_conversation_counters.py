"""Exact summaries including holes, bulk deletes and rollback."""
from sqlalchemy import delete, event, insert, select, update
from app.models import Conversation, Message
from app.modules.conversations.service import conversation_dicts, conversation_event_summaries
from app.modules.panel.read_state import mark_conversation_read
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
