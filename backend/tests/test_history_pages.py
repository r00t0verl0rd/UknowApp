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
    latest = client.get(base + "/messages?limit=50&mark_read=false").json()
    older = client.get(base + "/messages", params={"limit": 50, "before_id": latest[0]["id"], "mark_read": "false"}).json()
    assert [int(row["text"]) for row in older + latest] == list(range(9900, 10000))
    cursor = older[0]["id"] - 1
    following = client.get(base + "/messages", params={
        "limit": 6, "after_id": cursor, "forward": "true", "mark_read": "false",
    }).json()
    assert [row["id"] for row in following] == [row["id"] for row in older[:6]]
    if not personal:
        login(client, "student-one", "student-password-1")
    unread = client.get(base + "/messages", params={
        "first_unread": "true", "limit": 50, "mark_read": "false",
    }).json()
    assert unread["messages"][0]["text"] == "0"
    assert unread["anchor_id"] == unread["messages"][0]["id"]
    assert not unread["has_older"] and unread["has_newer"]
    anchor = older[25]["id"]
    window = client.get(base + "/messages", params={
        "around_id": anchor, "limit": 50, "mark_read": "false",
    }).json()
    assert len(window["messages"]) == 100
    assert window["messages"][50]["id"] == anchor
    assert window["has_older"] and window["has_newer"]
    batch = client.post(base + "/sync", json={"after_id": older[0]["id"] - 2, "paged": True}).json()
    assert len(batch["messages"]) == 100 and batch["has_more"]
