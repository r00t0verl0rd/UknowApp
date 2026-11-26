"""Hard SQL-count budgets are more repeatable than CI wall-clock thresholds."""
from sqlalchemy import event, insert
from app.models import Message, PersonalConversation, PersonalMessage
from helpers import create_conversation


def test_authenticated_profile_and_history_query_budget(api):
    make_client, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        chat_id = chat.id
        personal = PersonalConversation(participant_id=users["teacher-one"])
        db.add(personal)
        db.flush()
        personal_id = personal.id
        for model, cid in ((Message, chat_id), (PersonalMessage, personal_id)):
            db.execute(insert(model), [
                {"conversation_id": cid, "sender_id": users["teacher-one"], "sender_role": "teacher", "text": str(i)}
                for i in range(1000)
            ])
        db.commit()
        engine = db.get_bind()
    client = make_client()
    assert client.post("/api/auth/login", json={"username":"teacher-one","password":"teacher-password-1"}).status_code == 200  # pragma: allowlist secret
    statements = []
    def count(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get("/api/panel/me").status_code == 200
        assert len(statements) == 1
        for limit in (1, 100):
            statements.clear()
            result = client.get(f"/api/panel/conversations/{chat_id}/messages",
                                params={"limit":limit,"mark_read":"false"})
            assert result.status_code == 200 and len(result.json()) == limit
            assert len(statements) <= 4, statements
            assert not any("messenger_accounts" in s for s in statements)
            statements.clear()
            result = client.get(f"/api/panel/personal-conversations/{personal_id}/messages",
                                params={"limit":limit,"mark_read":"false"})
            assert result.status_code == 200 and len(result.json()) == limit
            assert len(statements) <= 3, statements
            assert not any("messenger_accounts" in s for s in statements)
        statements.clear()
        result = client.get("/api/panel/conversations")
        assert result.status_code == 200
        assert result.json()[0]["message_count"] == 1000
        assert len(statements) <= 3, statements
        assert not any("messenger_accounts" in s or "count(" in s.lower() or "json_extract" in s.lower() or "group by" in s.lower() for s in statements)
        statements.clear()
        sync = client.post(f"/api/panel/conversations/{chat_id}/sync",json={"after_id":1000000,"paged":True,"mark_read":False})
        assert sync.status_code == 200, sync.text
        assert sync.json()["summary"]["message_count"] == 1000
        assert not any("json_extract" in s.lower() or "group by" in s.lower() or "count(" in s.lower() for s in statements)
        statements.clear()
        result = client.get("/api/panel/personal-conversations")
        assert result.status_code == 200 and result.json()[0]["unread_count"] == 0
        assert len(statements) <= 2, statements
        assert not any("personal_messages" in sql.lower() for sql in statements)
        statements.clear()
        sync = client.post(f"/api/panel/personal-conversations/{personal_id}/sync",
                           json={"after_id":1000000,"paged":True,"mark_read":False})
        assert sync.status_code == 200, sync.text
        assert not any("group by" in sql.lower() or "count(" in sql.lower() or "max(" in sql.lower()
                       for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)
