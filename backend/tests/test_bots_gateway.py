"""Provider-neutral gateway invariants (no provider SDK required)."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.bots_gateway import gateway
from app.bots_gateway.operations import receive_message, rpc
from app.bots_gateway.outbox import enqueue_web_delivery, record_result
from app.models import Assignment, BotEventReceipt, ConnectorDelivery, Conversation, Message, User
from app.modules.communication.accounts import sync_messenger_account

SECRET = "test-media-" + "x" * 40


def prepare(db, users):
    teacher = db.get(User, users["teacher-one"])
    student = db.get(User, users["student-one"])
    assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
    db.add(assignment)
    db.flush()
    chat = Conversation(assignment=assignment, teacher=teacher, student=student, status="active")
    db.add(chat)
    sync_messenger_account(db, teacher.id, "alpha", "teacher", "100")
    sync_messenger_account(db, student.id, "beta", "student", "200")
    db.commit()
    return chat


def test_media_is_platform_scoped_and_idempotent(tmp_path, monkeypatch):
    app = FastAPI()
    app.state.bots_gateway = SimpleNamespace(platforms=("alpha", "beta"))
    app.include_router(gateway.router)
    monkeypatch.setattr(gateway, "MEDIA_DIR", tmp_path)
    monkeypatch.setenv("BOTS_MEDIA_SECRET_ALPHA", SECRET)
    monkeypatch.setenv("BOTS_MEDIA_SECRET_BETA", SECRET + "beta")
    headers = {"Authorization": "Bearer " + SECRET}
    with TestClient(app) as client:
        url = "/internal/bots/media/alpha/inbound/event-1"
        assert client.put(url, content=b"test").status_code == 403
        assert client.put(url.replace("/alpha/", "/beta/"), content=b"test", headers=headers).status_code == 403
        assert client.put(url, content=b"test", headers=headers).json() == {"size": 4}
        assert client.put(url, content=b"new", headers=headers).json() == {"size": 4}
        assert gateway.media_path("alpha", "event-1")[0].read_bytes() == b"test"


def test_inbound_receipt_and_cross_provider_outbox(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        chat_id = chat.id
        event = {"id":"event-1", "external_message_id":"42", "actor":"student", "chat_id":"200",
                 "channel":"private", "kind":"text", "text":"hello"}
        receive_message(db, "beta", event, ("alpha", "beta"), gateway.media_path)
        receive_message(db, "beta", event, ("alpha", "beta"), gateway.media_path)
        # Provider retransmit with different delivery event ID, same source message.
        receive_message(db, "beta", {**event, "id":"event-2"}, ("alpha", "beta"), gateway.media_path)
        assert db.query(Message).count() == 1
        assert db.query(BotEventReceipt).count() == 2
        job = db.query(ConnectorDelivery).one()
        assert job.platform == "alpha" and job.chat_id == "100"
        assert job.status == "queued"
        assert rpc(db, "alpha", "delivery.authorize", {"id":job.id})["text"].endswith("hello")
        with pytest.raises(HTTPException):
            rpc(db, "beta", "delivery.authorize", {"id":job.id})
        view = rpc(db, "alpha", "conversation.open", {"actor":"teacher", "conversation_id":chat_id})
        assert view["messages"][0]["text"] == "hello"
        record_result(db, job, "delivered", "message-123")
        record_result(db, job, "unknown")
        row = db.query(Message).one()
        assert json.loads(row.metadata_json)["messenger_deliveries"]["alpha"]["status"] == "delivered"


def test_account_cannot_open_other_conversation(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, users["teacher-two"], "alpha", "other", "300")
        db.commit()
        with pytest.raises(HTTPException) as err:
            rpc(db, "alpha", "conversation.open", {"actor":"other", "conversation_id":chat.id})
        assert err.value.status_code == 403


def test_web_outbox_rolls_back_with_message(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="queued", metadata_json="{}")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("alpha", "beta"))
        db.flush()
        assert db.query(ConnectorDelivery).count() == 1
        db.rollback()
        assert db.query(Message).count() == db.query(ConnectorDelivery).count() == 0


def test_revoked_binding_cancels_pending_job(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="queued", metadata_json="{}")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("alpha", "beta"))
        db.commit()
        job = db.query(ConnectorDelivery).one()
        sync_messenger_account(db, chat.student_id, "beta", None)
        db.commit()
        with pytest.raises(HTTPException) as err:
            rpc(db, "beta", "delivery.authorize", {"id":job.id})
        assert err.value.status_code == 403
        assert job.status == "cancelled"
