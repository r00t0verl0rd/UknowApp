"""Repeated sends persist business messages without a SQL SSE journal."""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.models import Message, PersonalMessage, User
from app.event_hub import current_event_id
from app.modules.communication.accounts import sync_messenger_account
from app.models import ConnectorDelivery
from app.bots_gateway.operations import receive_message
from app.bots_gateway.gateway import media_path
from test_message_delivery import login
from helpers import create_conversation


@pytest.mark.parametrize("source", ["admin", "student", "teacher", "telegram_student", "telegram_teacher",
                                     "personal_admin", "personal_student", "personal_teacher"])
def test_repeated_one_character_sends(api, monkeypatch, source):
    make_client, users, sessions = api
    client = make_client()
    login(client, "test-admin", "a-long-test-password-123")
    telegram = "telegram"
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        for role, chat_id in [("student", "200"), ("teacher", "100")]:
            sync_messenger_account(db, users[role + "-one"], telegram,
                                   external_user_id=role, external_chat_id=chat_id)
        db.commit()
        chat_id = chat.id
        sender = source.split("_")[-1]
        collection = "conversations"
        model = Message
        if source.startswith("personal_"):
            participant = "teacher" if sender == "teacher" else "student"
            personal = client.post("/api/panel/personal-conversations",
                                   json={"user_id": users[participant + "-one"]})
            personal.raise_for_status()
            chat_id = personal.json()["id"]
            collection = "personal-conversations"
            model = PersonalMessage
        if not source.startswith("telegram_") and sender != "admin":
            client = make_client()
            login(client, sender + "-one", sender + "-password-1")
        sizes = []
        for i in range(60):
            if not source.startswith("telegram_"):
                response = client.post(f"/api/panel/{collection}/{chat_id}/messages",
                                       json={"text": "я", "client_message_id": str(uuid4())})
                assert response.status_code == 201
            else:
                receive_message(db, telegram, {"id":f"event-{i}", "actor":sender,
                    "chat_id":"200" if sender == "student" else "100", "channel":"private",
                    "conversation_id":chat.id, "kind":"text", "text":"я"}, (telegram,), media_path)
            sizes.append(db.scalar(text("PRAGMA page_count")) * db.scalar(text("PRAGMA page_size")))
            db.rollback()
        print(source, "growth over last 59 sends", sizes[-1] - sizes[0],
              "sends with no file growth", sum(a == b for a, b in zip(sizes, sizes[1:])))
        if source.startswith("telegram_"):
            assert db.query(ConnectorDelivery).count() == 60
        assert db.query(model).count() == 60
        assert not inspect(db.get_bind()).has_table("realtime_events")
        assert sizes[-1] - sizes[0] < 59 * 4096


@pytest.mark.parametrize("collection", ["conversations", "personal-conversations"])
def test_reopening_read_messages_does_not_grow_database(api, collection):
    make_client, users, sessions = api
    admin = make_client()
    teacher = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    login(teacher, "teacher-one", "teacher-password-1")
    if collection == "personal-conversations":
        response = admin.post("/api/panel/personal-conversations", json={"user_id": users["teacher-one"]})
        response.raise_for_status()
        chat_id = response.json()["id"]
    else:
        with sessions() as db:
            chat_id = create_conversation(db, users["teacher-one"], users["student-one"]).id
    url = f"/api/panel/{collection}/{chat_id}"
    message = admin.post(url + "/messages", json={"text": "я"})
    message.raise_for_status()
    message_id = message.json()["id"]
    teacher.get(url + "/messages?limit=50").raise_for_status()

    def snapshot():
        with sessions() as db:
            return db.scalar(text("PRAGMA page_count")), current_event_id()

    original = snapshot()
    for _ in range(20):
        teacher.get(url + "/messages?limit=50").raise_for_status()
        teacher.post(url + "/sync", json={"paged": True, "after_id": message_id,
                                         "known_message_ids": [message_id]}).raise_for_status()
    assert snapshot() == original
