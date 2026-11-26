"""Provider-neutral gateway invariants (no provider SDK required)."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.bots_gateway import gateway
from app.bots_gateway.operations import receive_message, rpc
from app.modules.communication.outbox import enqueue_message_deletions, enqueue_web_delivery, record_result
from app.models import Assignment, BotEventReceipt, ConnectorDeletion, ConnectorDelivery, Conversation, ExternalEndpoint, Message, User
from app.modules.communication.accounts import sync_messenger_account

SECRET = "test-media-" + "x" * 40  # pragma: allowlist secret


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


def reply(db, chat, kind="text"):
    row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                  text="reply", content_type=kind, metadata_json=json.dumps(
                      {"media": {"archive_status": "stored", "file_name": "photo.jpg", "mime_type": "image/jpeg"}}
                      if kind == "photo" else {}))
    db.add(row)
    db.flush()
    enqueue_web_delivery(db, row, ("alpha", "beta"))
    db.commit()
    return row


@pytest.mark.parametrize("kind", ["text", "photo"])
def test_private_and_group_fanout_and_partial_delivery(api, kind):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        db.add(ExternalEndpoint(platform="beta", user_id=chat.student_id,
                                chat_id="group", thread_id="topic", preferred=False))
        db.commit()
        receive_message(db, "beta", {"id":"private-1", "actor":"student", "chat_id":"200",
                        "channel":"private", "kind":"text", "text":"hello"}, ("alpha", "beta"), gateway.media_path)
        row = reply(db, chat, kind)
        jobs = db.query(ConnectorDelivery).filter_by(message_id=row.id).all()
        assert {(j.chat_id, j.thread_id) for j in jobs} == {("200", ""), ("group", "topic")}
        group = next(j for j in jobs if j.thread_id)
        private = next(j for j in jobs if not j.thread_id)
        payload = rpc(db, "beta", "delivery.authorize", {"id":group.id})
        assert payload["thread_id"] == "topic"
        assert bool(payload["media"]) == (kind == "photo")
        record_result(db, group, "failed")
        assert json.loads(row.metadata_json)["messenger_deliveries"]["beta"]["status"] == "queued"
        assert rpc(db, "beta", "delivery.authorize", {"id":private.id})["thread_id"] is None
        record_result(db, private, "delivered", "1000")
        ledger = json.loads(row.metadata_json)["messenger_deliveries"]["beta"]
        assert ledger["status"] == "partial"
        assert ledger["delivered"][0]["endpoint_type"] == "private"
        assert ledger["errors"][0]["endpoint_type"] == "group"
        assert db.query(Message).count() == 2


def test_bot_reply_fanout_and_rebind(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"group","thread_id":"topic"})
        receive_message(db, "alpha", {"id":"teacher-1","actor":"teacher","chat_id":"100",
                        "channel":"private","conversation_id":chat.id,"kind":"text","text":"hello"},
                        ("alpha","beta"), gateway.media_path)
        assert db.query(Message).count() == 1
        jobs = db.query(ConnectorDelivery).all()
        assert len(jobs) == 2
        group = next(j for j in jobs if j.thread_id)
        private = next(j for j in jobs if not j.thread_id)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"new-group","thread_id":"new-topic"})
        with pytest.raises(HTTPException) as err:
            rpc(db, "beta", "delivery.authorize", {"id":group.id})
        assert err.value.status_code == 403
        assert group.status == "cancelled"
        assert rpc(db, "beta", "delivery.authorize", {"id":private.id})["chat_id"] == "200"


def test_delete_copies_in_both_chats(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"group","thread_id":"topic"})
        row = reply(db, chat)
        for job in db.query(ConnectorDelivery).all():
            record_result(db, job, "delivered", "123")
        assert len(json.loads(row.metadata_json)["messenger_deliveries"]["beta"]["delivered"]) == 2
        assert enqueue_message_deletions(db, row) == (2, 0)
        db.delete(row)
        db.commit()
        assert db.query(Message).count() == 0
        deletes = db.query(ConnectorDeletion).all()
        assert {d.chat_id for d in deletes} == {"group", "200"}
        for deletion in deletes:
            assert rpc(db, "beta", "delivery.authorize", {"id":deletion.id})["operation"] == "delete"
            record_result(db, deletion, "delivered", "123")
        assert all(d.status == "delivered" for d in deletes)


def test_late_receipt_after_deletion(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"group","thread_id":"topic"})
        row = reply(db, chat)
        jobs = db.query(ConnectorDelivery).all()
        group = next(j for j in jobs if j.thread_id)
        private = next(j for j in jobs if not j.thread_id)
        rpc(db, "beta", "delivery.authorize", {"id":group.id})
        assert enqueue_message_deletions(db, row) == (1, 0)
        db.delete(row)
        db.commit()
        assert private.status == "cancelled"
        assert group.message_id is None
        record_result(db, group, "delivered", "late-id")
        assert db.query(ConnectorDeletion).one().chat_id == "group"
        record_result(db, group, "delivered", "late-id")
        assert db.query(ConnectorDeletion).count() == 1



def test_batch_claim_retry_and_route_order(api):
    from datetime import timedelta
    from app.modules.communication.outbox import now_utc
    from app.bots_gateway import transport

    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"group","thread_id":"topic"})
        first = reply(db, chat)
        second = reply(db, chat)
        jobs = db.query(ConnectorDelivery).order_by(ConnectorDelivery.created_at, ConnectorDelivery.id).all()
        first_private = next(j for j in jobs if j.message_id == first.id and not j.thread_id)
        first_group = next(j for j in jobs if j.message_id == first.id and j.thread_id)
        second_private = next(j for j in jobs if j.message_id == second.id and not j.thread_id)
        claim = "a" * 32
        batch = rpc(db, "beta", "delivery.authorize_batch", {"jobs":[
            {"id":first_private.id,"claim":claim}, {"id":first_group.id,"claim":"b"*32},
            {"id":second_private.id,"claim":"c"*32}]})
        assert batch[first_private.id]["ok"] and batch[first_group.id]["ok"]
        assert batch[second_private.id] == {"ok":False,"code":425}
        assert rpc(db, "beta", "delivery.authorize", {"id":first_private.id,"claim":claim})["id"] == first_private.id
        with pytest.raises(HTTPException) as error:
            rpc(db, "beta", "delivery.authorize", {"id":first_private.id,"claim":"d"*32})
        assert error.value.status_code == 425
        first_private.started_at = now_utc() - timedelta(minutes=20)
        db.commit()
        transport.project_pending(db, ("beta",), {})
        assert first_private.id in {e[0] for e in transport.candidates(db, ("beta",))}
        with pytest.raises(HTTPException) as error:
            rpc(db, "beta", "delivery.authorize", {"id":first_private.id,"claim":"d"*32})
        assert error.value.status_code == 409
        record_result(db, first_private, "delivered", "receipt")
        assert rpc(db, "beta", "delivery.authorize", {"id":second_private.id,"claim":"c"*32})["id"] == second_private.id


def test_additive_recovery_migration(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.migrations.delivery_recovery import upgrade_delivery_recovery

    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.sqlite"))
    with engine.begin() as c:
        for table in ("connector_deliveries", "connector_deletions"):
            c.execute(text("CREATE TABLE " + table + " (id VARCHAR(64) PRIMARY KEY)"))
            c.execute(text("INSERT INTO " + table + " VALUES (:value)"), {"value": "old"})  # nosec B608 - fixed test table names
        upgrade_delivery_recovery(c)
        upgrade_delivery_recovery(c)
        for table in ("connector_deliveries", "connector_deletions"):
            assert {"claim_id","started_at","published_at","broker_seq"} <= {col["name"] for col in inspect(c).get_columns(table)}
            assert c.scalar(text("SELECT id FROM " + table)) == "old"  # nosec B608 - fixed test table names


def test_outbox_publishes_private_and_topic_independently():
    import asyncio
    from types import SimpleNamespace
    from app.bots_gateway.contracts import decode

    async def run():
        core = gateway.BotsGateway()
        private_started = asyncio.Event()
        topic_started = asyncio.Event()
        calls = []

        async def publish(subject, data, headers):
            job = decode(data)
            calls.append(job["id"])
            if job["id"] == "private-1":
                private_started.set()
                await topic_started.wait()
                raise OSError("simulated temporary publication failure")
            if job["id"] == "topic-1":
                topic_started.set()
                await private_started.wait()
            return SimpleNamespace(seq=len(calls))

        core.js = SimpleNamespace(publish=publish)
        entries = [
            ("private-1", "telegram", "200", "", "queued", False, None),
            ("private-2", "telegram", "200", "", "queued", False, None),
            ("topic-1", "telegram", "-1001", "7", "queued", False, None),
            ("topic-2", "telegram", "-1001", "7", "queued", False, None),
        ]
        try:
            acks = await asyncio.wait_for(core.publish_route_batch(entries), 2)
            assert {job_id for job_id, _ in acks} == {"topic-1", "topic-2"}
            assert "private-2" not in calls
            assert calls.index("topic-1") < calls.index("topic-2")
        finally:
            await core.close()

    asyncio.run(run())


def test_topic_and_private_keep_independent_order_for_ten_messages(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor":"student","chat_id":"group","thread_id":"topic"})
        messages = [reply(db, chat) for _ in range(10)]
        private, group = [], []
        for message in messages:
            jobs = db.query(ConnectorDelivery).filter_by(message_id=message.id).all()
            assert len(jobs) == 2
            private.append(next(j for j in jobs if not j.thread_id))
            group.append(next(j for j in jobs if j.thread_id))
        # A stalled private route must not block any message in the group.
        rpc(db, "beta", "delivery.authorize", {"id":private[0].id})
        for i, job in enumerate(group):
            assert rpc(db, "beta", "delivery.authorize", {"id":job.id})["thread_id"] == "topic"
            record_result(db, job, "delivered", str(i+1))
        record_result(db, private[0], "delivered", "1")
        for i, job in enumerate(private[1:], 2):
            assert rpc(db, "beta", "delivery.authorize", {"id":job.id})["thread_id"] is None
            record_result(db, job, "delivered", str(i))
        for message in messages:
            ledger = json.loads(message.metadata_json)["messenger_deliveries"]["beta"]
            assert ledger["status"] == "delivered"
            assert {item["endpoint_type"] for item in ledger["delivered"]} == {"private", "group"}


def test_initial_topic_binding_routes_first_teacher_message_without_student_message(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        assert not db.query(Message).count()
        args = {"actor": "student", "chat_id": "group", "thread_id": "topic", "initial_only": True}
        assert rpc(db, "beta", "endpoint.bind", args) == {"bound": True}
        assert rpc(db, "beta", "endpoint.bind", args) == {"bound": True}
        assert rpc(db, "beta", "endpoint.bind", {**args, "thread_id": "another"}) == {"bound": False}
        first = reply(db, chat)
        jobs = db.query(ConnectorDelivery).filter_by(message_id=first.id).all()
        assert {(job.chat_id, job.thread_id) for job in jobs} == {("200", ""), ("group", "topic")}
        assert db.query(Message).count() == 1
        for job in jobs:
            payload = rpc(db, "beta", "delivery.authorize", {"id": job.id})
            assert payload["chat_id"] == job.chat_id
            assert payload["thread_id"] == (job.thread_id or None)


def test_telegram_candidate_discovery_is_platform_and_role_scoped(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        sync_messenger_account(db, chat.teacher_id, "telegram", "456", "456")
        db.commit()
        assert rpc(db, "telegram", "endpoint.student_candidates", {"after": 0}) == {
            "actors": ["123"], "next": None,
        }
        with pytest.raises(HTTPException) as exc:
            rpc(db, "alpha", "endpoint.student_candidates", {"after": 0})
        assert exc.value.status_code == 403


def test_telegram_forum_requires_authorized_invitation_and_replies_use_actual_topic(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        sync_messenger_account(db, chat.teacher_id, "telegram", "456", "456")
        db.commit()
        first = {"id": "forum-first", "external_message_id": "48", "actor": "123",
                 "chat_id": "-1001", "thread_id": "47", "channel": "group",
                 "kind": "text", "text": "Homework"}
        assert db.get(ExternalEndpoint, ("telegram", chat.student_id)) is None
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", first, ("telegram",), gateway.media_path)
        assert exc.value.status_code == 403
        assert rpc(db, "telegram", "endpoint.bind", {
            "actor": "123", "chat_id": "-1001", "thread_id": "47",
        }) == {"bound": True}
        endpoint = db.get(ExternalEndpoint, ("telegram", chat.student_id))
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="Reply", metadata_json="{}", delivery_status="delivered")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("telegram",))
        db.commit()
        jobs = db.query(ConnectorDelivery).filter_by(message_id=row.id).all()
        assert {(job.chat_id, job.thread_id) for job in jobs} == {("123", ""), ("-1001", "47")}
        # First teacher message already has both destinations; no student
        # message was necessary. Neither another topic nor another group may move it.
        receive_message(db, "telegram", first, ("telegram",), gateway.media_path)
        for group, thread in (("-1001", "69"), ("-1002", "69")):
            with pytest.raises(HTTPException) as exc:
                receive_message(db, "telegram", {**first, "id": "other-" + group,
                                "external_message_id": "70", "chat_id": group, "thread_id": thread},
                                ("telegram",), gateway.media_path)
            assert exc.value.status_code == 403
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")
        assert rpc(db, "telegram", "endpoint.bind", {
            "actor": "123", "chat_id": "-1002", "thread_id": "69",
        }) == {"bound": True}
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1002", "69")
        # A redelivery of an older message must not move the authorized route.
        receive_message(db, "telegram", {**first, "id": "forum-replay"}, ("telegram",), gateway.media_path)
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1002", "69")
        assert db.query(Message).filter_by(sender_id=chat.student_id).count() == 1
        old_group = next(job for job in jobs if job.thread_id)
        with pytest.raises(HTTPException):
            rpc(db, "telegram", "delivery.authorize", {"id": old_group.id})
        private = next(job for job in jobs if not job.thread_id)
        assert rpc(db, "telegram", "delivery.authorize", {"id": private.id})["chat_id"] == "123"
        for actor in ("456", "999"):
            with pytest.raises(HTTPException) as exc:
                receive_message(db, "telegram", {**first, "id": "invalid-" + actor,
                                "actor": actor, "conversation_id": chat.id}, ("telegram",), gateway.media_path)
            assert exc.value.status_code == 403
