"""Provider-neutral gateway invariants (no provider SDK required)."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bots_gateway import gateway
from app.bots_gateway.operations import receive_message, rpc
from app.modules.communication.outbox import enqueue_message_deletions, enqueue_web_delivery, record_result
from app.models import Assignment, BotEventReceipt, ConnectorDeletion, ConnectorDelivery, Conversation, ExternalEndpoint, Message, User
from app.modules.communication.accounts import sync_messenger_account

SECRET = "test-media-" + "x" * 40  # pragma: allowlist secret


def authorize(db, platform, payload):
    result = rpc(db, platform, "delivery.authorize_batch", {"jobs": [payload]})[payload["id"]]
    if not result["ok"]:
        raise HTTPException(result["code"])
    return result["result"]


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
        # Повтор события сохраняет исходный ID сообщения.
        receive_message(db, "beta", {**event, "id":"event-2"}, ("alpha", "beta"), gateway.media_path)
        assert db.query(Message).count() == 1
        assert db.query(BotEventReceipt).count() == 2
        job = db.query(ConnectorDelivery).one()
        assert job.platform == "alpha" and job.chat_id == "100"
        assert job.status == "queued"
        assert authorize(db, "alpha", {"id":job.id})["text"].endswith("hello")
        with pytest.raises(HTTPException):
            authorize(db, "beta", {"id":job.id})
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
            authorize(db, "beta", {"id":job.id})
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
        payload = authorize(db, "beta", {"id":group.id})
        assert payload["thread_id"] == "topic"
        assert bool(payload["media"]) == (kind == "photo")
        record_result(db, group, "failed")
        assert json.loads(row.metadata_json)["messenger_deliveries"]["beta"]["status"] == "queued"
        assert authorize(db, "beta", {"id":private.id})["thread_id"] is None
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
            authorize(db, "beta", {"id":group.id})
        assert err.value.status_code == 403
        assert group.status == "cancelled"
        assert authorize(db, "beta", {"id":private.id})["chat_id"] == "200"


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
            assert authorize(db, "beta", {"id":deletion.id})["operation"] == "delete"
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
        authorize(db, "beta", {"id":group.id})
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
        assert authorize(db, "beta", {"id":first_private.id,"claim":claim})["id"] == first_private.id
        with pytest.raises(HTTPException) as error:
            authorize(db, "beta", {"id":first_private.id,"claim":"d"*32})
        assert error.value.status_code == 425
        first_private.started_at = now_utc() - timedelta(minutes=20)
        db.commit()
        transport.project_pending(db, ("beta",), {})
        assert first_private.id in {e[0] for e in transport.candidates(db, ("beta",))}
        with pytest.raises(HTTPException) as error:
            authorize(db, "beta", {"id":first_private.id,"claim":"d"*32})
        assert error.value.status_code == 409
        record_result(db, first_private, "delivered", "receipt")
        assert authorize(db, "beta", {"id":second_private.id,"claim":"c"*32})["id"] == second_private.id


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
        # Задержка личного адреса не блокирует группу.
        authorize(db, "beta", {"id":private[0].id})
        for i, job in enumerate(group):
            assert authorize(db, "beta", {"id":job.id})["thread_id"] == "topic"
            record_result(db, job, "delivered", str(i+1))
        record_result(db, private[0], "delivered", "1")
        for i, job in enumerate(private[1:], 2):
            assert authorize(db, "beta", {"id":job.id})["thread_id"] is None
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
        args = {"actor": "student", "chat_id": "group", "thread_id": "topic"}
        assert rpc(db, "beta", "endpoint.bind", args) == {"bound": True}
        assert rpc(db, "beta", "endpoint.bind", args) == {"bound": True}
        first = reply(db, chat)
        jobs = db.query(ConnectorDelivery).filter_by(message_id=first.id).all()
        assert {(job.chat_id, job.thread_id) for job in jobs} == {("200", ""), ("group", "topic")}
        assert db.query(Message).count() == 1
        for job in jobs:
            payload = authorize(db, "beta", {"id": job.id})
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


def test_telegram_forum_moves_between_groups_but_not_topics(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        sync_messenger_account(db, chat.teacher_id, "telegram", "456", "456")
        sync_messenger_account(db, users["student-two"], "telegram", "789", "789")
        db.add(ExternalEndpoint(platform="telegram", user_id=users["student-two"],
                                chat_id="-1001", thread_id="99"))
        db.commit()
        first = {"id": "forum-first", "external_message_id": "48", "actor": "123",
                 "chat_id": "-1001", "thread_id": "47", "channel": "group",
                 "kind": "text", "text": "1"}
        assert db.get(ExternalEndpoint, ("telegram", chat.student_id)) is None
        # Сообщение работает без приглашения и команды.
        receive_message(db, "telegram", first, ("telegram",), gateway.media_path)
        endpoint = db.get(ExternalEndpoint, ("telegram", chat.student_id))
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")
        incoming = db.query(Message).filter_by(sender_id=chat.student_id).one()
        assert incoming.text == "1"
        assert json.loads(incoming.metadata_json)["source_thread_id"] == "47"
        assert db.query(ConnectorDelivery).filter_by(message_id=incoming.id).one().chat_id == "456"

        def teacher_reply():
            row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                          text="Reply", metadata_json="{}", delivery_status="delivered")
            db.add(row)
            db.flush()
            enqueue_web_delivery(db, row, ("telegram",))
            db.commit()
            return db.query(ConnectorDelivery).filter_by(message_id=row.id).all()

        jobs = teacher_reply()
        assert {(job.chat_id, job.thread_id) for job in jobs} == {("123", ""), ("-1001", "47")}
        for job in jobs:
            payload = authorize(db, "telegram", {"id": job.id})
            assert payload["chat_id"] == job.chat_id
            assert payload["thread_id"] == (job.thread_id or None)
            record_result(db, job, "delivered", "previous-copy")
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", {**first, "id": "occupied", "external_message_id": "49",
                            "thread_id": "99"}, ("telegram",), gateway.media_path)
        assert exc.value.status_code == 403
        db.rollback()
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")

        # Нельзя привязать другую свободную тему этой группы.
        def allowed(group, thread):
            return rpc(db, "telegram", "account.resolve", {"actor": "123", "group": True,
                       "chat_id": group, "thread_id": thread})["route_allowed"]

        assert not allowed("-1001", "69")
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", {**first, "id": "other-topic",
                            "external_message_id": "70", "thread_id": "69"},
                            ("telegram",), gateway.media_path)
        assert exc.value.status_code == 403
        # Нельзя занять тему, уже назначенную другому ученику.
        other = db.get(ExternalEndpoint, ("telegram", users["student-two"]))
        other.chat_id = "-1002"
        db.commit()
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", {**first, "id": "other-owner",
                            "external_message_id": "71", "chat_id": "-1002", "thread_id": "99"},
                            ("telegram",), gateway.media_path)
        assert exc.value.status_code == 409
        db.rollback()
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")
        # Отклонённое сообщение не меняет адрес.
        receive_message(db, "telegram", {**first, "id": "blocked-move",
                        "external_message_id": "72", "chat_id": "-1002", "thread_id": "69",
                        "kind": "contact", "text": ""}, ("telegram",), gateway.media_path)
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1001", "47")
        # Первое сообщение новой группы заменяет старый адрес.
        queued = teacher_reply()
        assert allowed("-1002", "69")
        receive_message(db, "telegram", {**first, "id": "new-group",
                        "external_message_id": "73", "chat_id": "-1002", "thread_id": "69"},
                        ("telegram",), gateway.media_path)
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1002", "69")
        assert not allowed("-1002", "47")
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", {**first, "id": "new-group-other-topic",
                            "external_message_id": "74", "chat_id": "-1002", "thread_id": "47"},
                            ("telegram",), gateway.media_path)
        assert exc.value.status_code == 403
        receive_message(db, "telegram", {**first, "id": "forum-replay"}, ("telegram",), gateway.media_path)
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1002", "69")
        old_job = next(job for job in queued if job.thread_id)
        with pytest.raises(HTTPException) as exc:
            authorize(db, "telegram", {"id": old_job.id})
        assert exc.value.status_code == 403 and old_job.status == "cancelled"
        receive_message(db, "telegram", {**first, "id": "private", "external_message_id": "71",
                        "chat_id": "123", "thread_id": None, "channel": "private"},
                        ("telegram",), gateway.media_path)
        assert (endpoint.chat_id, endpoint.thread_id) == ("-1002", "69")
        assert db.query(Message).filter_by(sender_id=chat.student_id).count() == 4
        assert {(job.chat_id, job.thread_id) for job in teacher_reply()} == {("123", ""), ("-1002", "69")}
        assert allowed("-1002", "69")
        assert (other.chat_id, other.thread_id) == ("-1002", "99")
        for actor in ("456", "999"):
            with pytest.raises(HTTPException) as exc:
                receive_message(db, "telegram", {**first, "id": "invalid-" + actor,
                                "actor": actor, "conversation_id": chat.id}, ("telegram",), gateway.media_path)
            assert exc.value.status_code == 403


def test_group_identity_lookup_does_not_read_message_history(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        sync_messenger_account(db, chat.teacher_id, "telegram", "456", "456")
        sync_messenger_account(db, users["student-two"], "telegram", "789", "789")
        db.commit()
        chat_id = chat.id
        db.expire_all()
        statements = []

        def capture(*args):
            statements.append(args[2].lower())

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            for actor, role, conversations, budget in (
                ("123", "student", [{"id": chat_id}], 2),
                ("456", "teacher", [], 1),
                ("789", "student", [], 2),
                ("999", None, [], 1),
            ):
                statements.clear()
                result = rpc(db, "telegram", "account.resolve", {"actor": actor, "group": True})
                assert result["conversations"] == conversations
                assert (result["account"]["role"] if result["account"] else None) == role
                assert len(statements) <= budget, statements
                assert not any(" from messages" in sql.replace("\n", " ") or
                               "row_number(" in sql for sql in statements)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        # Преподаватель получает полный список в личном чате.
        view = rpc(db, "telegram", "account.resolve", {"actor": "456"})
        assert view["conversations"][0]["id"] == chat_id
        assert "unread_previews" in view["conversations"][0]


def test_outbox_fanout_uses_two_selects_and_is_idempotent_before_flush(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        rpc(db, "beta", "endpoint.bind", {"actor": "student", "chat_id": "group", "thread_id": "topic"})
        sync_messenger_account(db, chat.student_id, "alpha", "other-student", "300")
        db.commit()
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="Reply", metadata_json="{}")
        db.add(row)
        db.flush()
        statements = []

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            enqueue_web_delivery(db, row, ())
            assert not statements
            enqueue_web_delivery(db, row, ("alpha", "beta"))
            assert len(statements) == 2, statements
            # Повторная постановка учитывает незаписанные ORM-строки.
            enqueue_web_delivery(db, row, ("alpha", "beta"))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        db.commit()
        jobs = db.query(ConnectorDelivery).filter_by(message_id=row.id).all()
        assert {(j.platform, j.chat_id, j.thread_id) for j in jobs} == {
            ("alpha", "300", ""), ("beta", "200", ""), ("beta", "group", "topic"),
        }
        enqueue_web_delivery(db, row, ("alpha", "beta"))
        db.commit()
        assert db.query(ConnectorDelivery).filter_by(message_id=row.id).count() == 3


def test_telegram_explicit_invitation_takes_priority_before_student_message(api):
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        db.commit()
        assert rpc(db, "telegram", "endpoint.bind", {
            "actor": "123", "chat_id": "-1001", "thread_id": "47",
        }) == {"bound": True}
        assert not db.query(Message).count()
        assert rpc(db, "telegram", "endpoint.bind", {
            "actor": "123", "chat_id": "-1001", "thread_id": "99",
        }) == {"bound": False, "reason": "topic_locked"}
        event = {"id": "wrong-first", "external_message_id": "50", "actor": "123",
                 "chat_id": "-1001", "thread_id": "99", "channel": "group",
                 "kind": "text", "text": "Other topic"}
        with pytest.raises(HTTPException) as exc:
            receive_message(db, "telegram", event, ("telegram",), gateway.media_path)
        assert exc.value.status_code == 403
        assert not db.query(Message).count()
        assert not db.query(ConnectorDelivery).count()
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="First reply", metadata_json="{}", delivery_status="delivered")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("telegram",))
        db.commit()
        assert {(job.chat_id, job.thread_id) for job in db.query(ConnectorDelivery).all()} == {
            ("123", ""), ("-1001", "47"),
        }


def test_multipart_receipts_keep_all_known_copies_for_deletion(api):
    from app.modules.communication.outbox import enqueue_message_deletions
    _, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        db.add(ExternalEndpoint(platform="telegram", user_id=chat.student_id,
                                chat_id="-1001", thread_id="7"))
        db.commit()
        row = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher",
                      text="Long text", metadata_json="{}", delivery_status="delivered")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("telegram",))
        db.commit()
        jobs = db.query(ConnectorDelivery).filter_by(message_id=row.id).all()
        group = next(job for job in jobs if job.thread_id)
        private = next(job for job in jobs if not job.thread_id)
        record_result(db, group, "failed", "11", external_ids=["11", "12"])
        record_result(db, private, "delivered", "21")
        ledger = json.loads(row.metadata_json)["messenger_deliveries"]["telegram"]
        assert ledger["status"] == "partial"
        assert {copy["external_message_id"] for copy in ledger["delivered"]} == {"11", "12", "21"}
        enqueue_message_deletions(db, row)
        assert {(job.chat_id, job.external_message_id) for job in db.query(ConnectorDeletion)} == {
            ("-1001", "11"), ("-1001", "12"), ("123", "21")}


def test_admin_can_reset_only_selected_student_topic(api):
    make_client, users, sessions = api
    with sessions() as db:
        chat = prepare(db, users)
        student = chat.student_id
        other = users["student-two"]
        sync_messenger_account(db, student, "telegram", "123", "123")
        sync_messenger_account(db, other, "telegram", "789", "789")
        db.add_all([
            ExternalEndpoint(platform="telegram", user_id=student, chat_id="-1001", thread_id="7"),
            ExternalEndpoint(platform="telegram", user_id=other, chat_id="-1002", thread_id="7"),
        ])
        db.commit()
        first = Message(conversation_id=chat.id, sender_id=chat.teacher_id, sender_role="teacher", text="reply")
        db.add(first)
        db.flush()
        enqueue_web_delivery(db, first, ("telegram",))
        db.commit()
        jobs = db.query(ConnectorDelivery).filter_by(message_id=first.id, platform="telegram").all()
        group_id = next(job.id for job in jobs if job.thread_id)
        private_id = next(job.id for job in jobs if not job.thread_id)
    path = f"/api/admin/users/{student}/messengers/telegram/reset-topic"
    student_client = make_client()
    assert student_client.post("/api/auth/login", json={"username": "student-one",
        "password": "student-password-1"}).status_code == 200  # pragma: allowlist secret
    assert student_client.post(path).status_code == 401  # shared permission policy
    client = make_client()
    assert client.post("/api/auth/login", json={"username": "test-admin",
        "password": "a-long-test-password-123"}).status_code == 200  # pragma: allowlist secret
    assert client.post(path).json() == {"ok": True}
    assert client.post(path).json() == {"ok": True}
    with sessions() as db:
        assert db.get(ExternalEndpoint, ("telegram", student)) is None
        assert db.get(ExternalEndpoint, ("telegram", other)).thread_id == "7"
        with pytest.raises(HTTPException) as exc:
            authorize(db, "telegram", {"id": group_id})
        assert exc.value.status_code == 403
        assert authorize(db, "telegram", {"id": private_id})["chat_id"] == "123"
        assert rpc(db, "telegram", "endpoint.bind", {
            "actor": "123", "chat_id": "-1001", "thread_id": "9",
        }) == {"bound": True}
        assert db.get(ExternalEndpoint, ("telegram", student)).thread_id == "9"


def test_core_ack_confirms_only_current_committed_forum_route(api, monkeypatch):
    _, users, sessions = api
    monkeypatch.setattr(gateway, "SessionLocal", sessions)
    with sessions() as db:
        chat = prepare(db, users)
        sync_messenger_account(db, chat.student_id, "telegram", "123", "123")
        db.commit()
    core = gateway.BotsGateway()
    try:
        core.platforms = ("telegram",)
        event = {"id": "first", "external_message_id": "10", "actor": "123",
                 "channel": "group", "chat_id": "-1001", "thread_id": "7",
                 "pending_topic": True, "kind": "text", "text": "Hi"}
        blocked = {**event, "id": "blocked", "external_message_id": "9", "kind": "contact", "text": ""}
        assert core._consume_event("telegram", "inbound", blocked) == {"route_confirmed": False}
        assert core._consume_event("telegram", "inbound", event) == {"route_confirmed": True}
        assert core._consume_event("telegram", "inbound", event) == {"route_confirmed": True}
        moved = {**event, "id": "moved", "external_message_id": "11", "chat_id": "-1002"}
        assert core._consume_event("telegram", "inbound", moved) == {"route_confirmed": True}
        assert core._consume_event("telegram", "inbound", event) == {"route_confirmed": False}
    finally:
        core._db_executor.shutdown()
