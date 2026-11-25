"""Protocol, media authorization and durable Core queue tests."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.bots_gateway.gateway import BotsGateway, GatewayUnavailable, router
from app.bots_gateway.outbox import enqueue_web_delivery
from app.models import Assignment, BotDeliveryJob, Conversation, Message, User

SECRET = "test-gateway-" + "x" * 40


def test_duplex_rpc_event_ack_and_duplicate_connector():
    app = FastAPI()
    gateway = BotsGateway()
    app.state.bots_gateway = gateway
    app.include_router(router)
    received = []

    async def handle(event_id, payload):
        result = await gateway.call("telegram", "send", payload, timeout=2)
        received.append((event_id, result))

    gateway.register("telegram", SECRET, handle, lambda _: None)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/internal/bots/ws/telegram"):
                pass
        headers = {"Authorization": "Bearer " + SECRET}
        with client.websocket_connect("/internal/bots/ws/telegram", headers=headers) as socket:
            assert socket.receive_json() == {"type": "hello", "version": 1}
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/internal/bots/ws/telegram", headers=headers):
                    pass
            socket.send_json({"type": "event", "id": "event-1", "payload": {"text": "hello"}})
            command = socket.receive_json()
            assert command["type"] == "command"
            assert command["operation"] == "send"
            assert command["payload"] == {"text": "hello"}
            socket.send_json({"type": "result", "id": command["id"], "payload": {"id": "42"}})
            assert socket.receive_json() == {"type": "ack", "id": "event-1", "ok": True}
        assert received == [("event-1", {"id": "42"})]
    with pytest.raises(GatewayUnavailable):
        asyncio.run(gateway.call("telegram", "send", {}))


def test_media_tickets_are_scoped_and_single_use(tmp_path):
    app = FastAPI()
    gateway = BotsGateway()
    app.state.bots_gateway = gateway
    app.include_router(router)

    async def handle(*_):
        pass

    gateway.register("telegram", SECRET, handle, lambda _: None)
    gateway.register("max", SECRET + "max", handle, lambda _: None)
    headers = {"Authorization": "Bearer " + SECRET}
    source = tmp_path / "source"
    source.write_bytes(b"test media")
    ticket = gateway.issue_ticket("telegram", source, "download")
    target = tmp_path / "target"
    upload = gateway.issue_ticket("telegram", target, "upload")
    with TestClient(app) as client:
        url = f"/internal/bots/media/telegram/{ticket}"
        assert client.get(url).status_code == 403
        assert client.get(f"/internal/bots/media/max/{ticket}",
                          headers={"Authorization": "Bearer " + SECRET + "max"}).status_code == 404
        assert client.get(url, headers=headers).content == b"test media"
        assert client.get(url, headers=headers).status_code == 404
        assert client.put(f"/internal/bots/media/telegram/{upload}",
                          headers=headers, content=b"upload").json() == {"size": 6}
        assert target.read_bytes() == b"upload"
        assert gateway.tickets[upload].completed
        gateway.revoke_ticket(upload)
        assert client.put(f"/internal/bots/media/telegram/{upload}",
                          headers=headers, content=b"overwrite").status_code == 404
        assert target.read_bytes() == b"upload"


def test_outbox_message_and_job_commit_together(api):
    _, _, sessions = api
    with sessions() as db:
        teacher = db.query(User).filter_by(role="teacher").first()
        student = db.query(User).filter_by(role="student").first()
        assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
        db.add(assignment)
        db.flush()
        conversation = Conversation(assignment=assignment, teacher=teacher, student=student, status="active")
        db.add(conversation)
        db.flush()
        row = Message(conversation_id=conversation.id, sender_id=teacher.id, sender_role="teacher",
                      text="queued", metadata_json='{"source_mode":"web"}')
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row)
        db.commit()
        ident = row.id
    with sessions() as db:
        assert db.get(BotDeliveryJob, ident).status == "queued"
        assert json.loads(db.get(Message, ident).metadata_json)["messenger_deliveries"]["telegram"]["status"] == "queued"


def test_offline_outbox_does_not_read_database(monkeypatch):
    from app.bots_gateway import outbox

    def unexpected_db():
        raise AssertionError("No database polling while connector is offline")

    monkeypatch.setattr(outbox, "SessionLocal", unexpected_db)
    gateway = BotsGateway()
    assert asyncio.run(outbox.deliver_one(SimpleNamespace(), gateway)) is False
