import pytest
from sqlalchemy import insert

from app.models import Message, PersonalConversation, PersonalMessage
from test_message_delivery import login
from test_telegram_bot import create_conversation


@pytest.mark.parametrize("personal", [False, True])
def test_large_history_pages_and_sync(api, personal):
    make_client, users, sessions = api
    with sessions() as db:
        teacher = users["teacher-one"]
        if personal:
            chat = PersonalConversation(participant_id=teacher)
            db.add(chat)
            db.flush()
            model, collection = PersonalMessage, "personal-conversations"
        else:
            chat = create_conversation(db, teacher, users["student-one"])
            model, collection = Message, "conversations"
        base = f"/api/panel/{collection}/{chat.id}"
        db.execute(insert(model), [dict(conversation_id=chat.id, sender_role="teacher",
                                       sender_id=teacher, text=str(i)) for i in range(10000)])
        db.commit()
    client = make_client()
    login(client, "test-admin", "a-long-test-password-123")
    latest = client.get(base + "/messages?limit=50").json()
    older = client.get(base + "/messages", params={"limit": 50, "before_id": latest[0]["id"]}).json()
    assert [int(row["text"]) for row in older + latest] == list(range(9900, 10000))
    batch = client.post(base + "/sync", json={"after_id": older[0]["id"] - 2, "paged": True}).json()
    assert len(batch["messages"]) == 100 and batch["has_more"]
