"""Repeated web and bot sends must reuse realtime journal pages."""

import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.models import Message, PersonalMessage, RealtimeEvent, User
from app.modules.communication.accounts import sync_messenger_account
from app.modules.communication.contracts import InboundMessage, MessageKind, MessengerPlatform
from app.modules.communication.service import CommunicationService
from app.modules.messaging.inbound import process_inbound_message, set_teacher_session
from test_message_delivery import FakeMessengerAdapter, login
from test_telegram_bot import NoMediaCopyGateway, create_conversation


@pytest.mark.parametrize("source", ["admin", "student", "teacher", "telegram_student", "telegram_teacher",
                                     "personal_admin", "personal_student", "personal_teacher"])
def test_repeated_one_character_sends(api, monkeypatch, source):
    make_client, users, sessions = api
    client = make_client()
    login(client, "test-admin", "a-long-test-password-123")
    telegram = MessengerPlatform.TELEGRAM
    monkeypatch.setattr(client.app.state, "communication",
                        CommunicationService([FakeMessengerAdapter(telegram)]), raising=False)
    gateway = NoMediaCopyGateway()
    if source == "telegram_teacher":
        gateway.copy_message = AsyncMock(return_value="123")
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
        if source == "telegram_teacher":
            set_teacher_session(db, db.get(User, users["teacher-one"]), chat)
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
                inbound = InboundMessage(platform=telegram, event_id=f"telegram:200:{i+1}",
                                         external_user_id=sender, external_chat_id="200" if sender == "student" else "100",
                                         external_message_id=str(i+1), content_type=MessageKind.TEXT, text="я")
                asyncio.run(process_inbound_message(db, inbound, gateway))
            sizes.append(db.scalar(text("PRAGMA page_count")) * db.scalar(text("PRAGMA page_size")))
            db.rollback()
        print(source, "growth over last 59 sends", sizes[-1] - sizes[0],
              "sends with no file growth", sum(a == b for a, b in zip(sizes, sizes[1:])))
        if source == "telegram_teacher":
            assert gateway.copy_message.await_count == 60
            assert all(call.args[2] == "200" for call in gateway.copy_message.await_args_list)
        assert db.query(model).count() == 60
        assert db.query(RealtimeEvent).count() == 1
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
            return db.scalar(text("PRAGMA page_count")), db.query(RealtimeEvent).one().id

    original = snapshot()
    for _ in range(20):
        teacher.get(url + "/messages?limit=50").raise_for_status()
        teacher.post(url + "/sync", json={"paged": True, "after_id": message_id,
                                         "known_message_ids": [message_id]}).raise_for_status()
    assert snapshot() == original
