"""Web messaging and provider-independent delivery tests."""
import json
import pytest
from app.models import Message, ConnectorDelivery
from app.modules.communication.accounts import get_messenger_pair, sync_messenger_account
from app.modules.communication.contracts import MessengerPlatform
from app.modules.communication.outbox import enqueue_web_delivery, record_result, job_payload
from app.bots_gateway.operations import receive_message
from app.bots_gateway.gateway import media_path
from helpers import create_conversation

def login(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def test_chat_delivery_ticks_follow_uknowapp_persistence_and_read_state(api):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    created = admin.post(
        "/api/admin/assignments",
        json={
            "teacher_id": users["teacher-one"],
            "student_id": users["student-one"],
        },
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    student = make_client()
    login(student, "student-one", "student-password-1")

    sent = teacher.post(
        f"/api/panel/conversations/{conversation_id}/messages",
        json={"text": "Ответ доступен в UknowApp"},
    )
    assert sent.status_code == 201
    assert sent.json()["delivery_status"] == "delivered"
    assert sent.json()["panel_read_at"] is None

    # Счётчик зависит от прочтения, а не от доставки.
    student_inbox_before_read = student.get("/api/panel/conversations")
    assert student_inbox_before_read.status_code == 200
    assert student_inbox_before_read.json()[0]["unread_count"] == 1

    # Ученик получает сообщение без привязки Telegram.
    received = student.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    )
    assert received.status_code == 200
    assert received.json()[0]["text"] == "Ответ доступен в UknowApp"
    student_inbox_after_read = student.get("/api/panel/conversations")
    assert student_inbox_after_read.status_code == 200
    assert student_inbox_after_read.json()[0]["unread_count"] == 0

    # Прочтение — отдельное событие, меняющее галочки.
    refreshed = teacher.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    )
    assert refreshed.status_code == 200
    assert refreshed.json()[0]["delivery_status"] == "delivered"
    assert refreshed.json()[0]["panel_read_at"] is not None
    recovered = teacher.post(
        f"/api/panel/conversations/{conversation_id}/sync",
        json={"after_id": sent.json()["id"], "known_message_ids": [sent.json()["id"]]},
    )
    assert recovered.status_code == 200
    assert recovered.json()["messages"] == []
    assert recovered.json()["updated_messages"][0]["panel_read_at"] is not None
    direct = teacher.get(f"/api/panel/messages/{sent.json()['id']}")
    assert direct.status_code == 200
    assert direct.json()["panel_read_at"] is not None

    # Обратное направление использует те же счётчики.
    student_reply = student.post(
        f"/api/panel/conversations/{conversation_id}/messages",
        json={"text": "Ответ ученика"},
    )
    assert student_reply.status_code == 201
    teacher_inbox_before_read = teacher.get("/api/panel/conversations")
    assert teacher_inbox_before_read.status_code == 200
    assert teacher_inbox_before_read.json()[0]["unread_count"] == 1
    teacher_read = teacher.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    )
    assert teacher_read.status_code == 200
    teacher_inbox_after_read = teacher.get("/api/panel/conversations")
    assert teacher_inbox_after_read.status_code == 200
    assert teacher_inbox_after_read.json()[0]["unread_count"] == 0


def test_personal_chat_exposes_admin_read_receipt_to_sender(api):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    created = admin.post(
        "/api/panel/personal-conversations",
        json={"user_id": users["teacher-one"]},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    sent = teacher.post(
        f"/api/panel/personal-conversations/{conversation_id}/messages",
        json={"text": "Личное сообщение", "client_message_id": "personal-retry-001"},
    )
    sent_duplicate = teacher.post(
        f"/api/panel/personal-conversations/{conversation_id}/messages",
        json={"text": "Личное сообщение", "client_message_id": "personal-retry-001"},
    )
    assert sent.status_code == 201
    assert sent_duplicate.json()["id"] == sent.json()["id"]
    assert sent.json()["panel_read_at"] is None

    admin_inbox_before_read = admin.get("/api/panel/personal-conversations")
    assert admin_inbox_before_read.status_code == 200
    assert admin_inbox_before_read.json()[0]["unread_count"] == 1

    admin_received = admin.get(
        f"/api/panel/personal-conversations/{conversation_id}/messages",
    )
    assert admin_received.status_code == 200
    assert admin_received.json()[0]["text"] == "Личное сообщение"
    admin_inbox_after_read = admin.get("/api/panel/personal-conversations")
    assert admin_inbox_after_read.status_code == 200
    assert admin_inbox_after_read.json()[0]["unread_count"] == 0

    teacher_refreshed = teacher.get(
        f"/api/panel/personal-conversations/{conversation_id}/messages",
    )
    assert teacher_refreshed.status_code == 200
    assert teacher_refreshed.json()[0]["panel_read_at"] is not None
    direct = teacher.get(f"/api/panel/personal-messages/{sent.json()['id']}")
    assert direct.status_code == 200
    assert direct.json()["panel_read_at"] is not None
    recovered = teacher.post(
        f"/api/panel/personal-conversations/{conversation_id}/sync",
        json={"after_id": sent.json()["id"], "known_message_ids": [sent.json()["id"]]},
    )
    assert recovered.status_code == 200
    assert recovered.json()["messages"] == []
    assert recovered.json()["updated_messages"][0]["panel_read_at"] is not None
    assert recovered.json()["summary"]["unread_count"] == 0



@pytest.mark.parametrize("personal", [False, True])
def test_background_fetch_preserves_unread_until_explicit_receipt(api, personal):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    if personal:
        collection = "/api/panel/personal-conversations"
        created = admin.post(collection, json={"user_id": users["teacher-one"]})
        reader = admin
    else:
        collection = "/api/panel/conversations"
        created = admin.post("/api/admin/assignments", json={
            "teacher_id": users["teacher-one"], "student_id": users["student-one"],
        })
        reader = make_client()
        login(reader, "student-one", "student-password-1")
    assert created.status_code == 201
    path = f"{collection}/{created.json()['id']}"

    first = teacher.post(f"{path}/messages", json={"text": "Первое"})
    first_id = first.json()["id"]
    fetched = reader.get(f"{path}/messages", params={"limit": 50, "mark_read": "false"})
    assert [row["id"] for row in fetched.json()] == [first_id]
    sync = reader.post(f"{path}/sync", json={"mark_read": False, "paged": True})
    assert sync.json()["summary"]["unread_count"] == 1
    assert sync.json()["messages"][0]["panel_read_at"] is None

    second = teacher.post(f"{path}/messages", json={"text": "Пришло после загрузки"})
    second_id = second.json()["id"]
    receipt = reader.post(f"{path}/read", json={"message_ids": [first_id]})
    assert receipt.status_code == 200
    assert receipt.json()["unread_count"] == 1
    repeated = reader.post(f"{path}/read", json={"message_ids": [first_id]})
    assert repeated.json()["unread_count"] == 1
    statuses = teacher.get(f"{path}/messages", params={"mark_read": "false"}).json()
    assert statuses[0]["panel_read_at"]
    assert statuses[1]["panel_read_at"] is None

    if not personal:
        # Observer receipts are independent from the participant's read state.
        observed = admin.get(collection).json()[0]
        assert observed["unread_count"] == 1
        assert observed["admin_unread_count"] == 2
        assert "admin_unread_count" not in reader.get(collection).json()[0]
        history = admin.get(f"{path}/messages").json()
        assert all(row["admin_read_at"] is None for row in history)
        assert admin.post(f"{path}/sync", json={"paged": True}).json()["summary"]["admin_unread_count"] == 2
        receipt = admin.post(f"{path}/read", json={"message_ids": [second_id]}).json()
        assert receipt["unread_count"] == 1
        assert receipt["admin_unread_count"] == 1
        assert "admin_read_at" not in teacher.get(f"{path}/messages", params={"mark_read": "false"}).json()[0]
    assert reader.post(f"{path}/read", json={"message_ids": [second_id]}).json()["unread_count"] == 0
    assert admin.get(collection).json()[0]["unread_count"] == 0


def test_personal_attachments_are_private_downloadable_and_idempotent(api):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    student = make_client()
    login(student, "student-one", "student-password-1")

    for member, user_id, name in (
        (teacher, users["teacher-one"], "teacher"),
        (student, users["student-one"], "student"),
    ):
        created = admin.post("/api/panel/personal-conversations", json={"user_id": user_id})
        assert created.status_code == 201
        chat_id = created.json()["id"]
        path = f"/api/panel/personal-conversations/{chat_id}/attachments"
        payload = {"text": "Смотрите вложение", "client_message_id": f"test-upload-{name}"}
        file = {"file": ("notes.txt", b"Hello from private chat", "text/plain")}
        uploaded = member.post(path, data=payload, files=file)
        assert uploaded.status_code == 201, uploaded.text
        message = uploaded.json()
        assert message["content_type"] == "document"
        assert message["text"] == "Смотрите вложение"
        assert message["metadata"]["media"]["file_name"] == "notes.txt"
        assert message["metadata"]["media"]["archive_status"] == "stored"
        assert "local_path" not in message["metadata"]["media"]
        duplicate = member.post(path, data=payload, files=file)
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == message["id"]

        media_url = f"/api/panel/personal-messages/{message['id']}/media"
        received = admin.get(media_url)
        assert received.status_code == 200
        assert received.content == b"Hello from private chat"
        cached = {"If-None-Match": received.headers["etag"]}
        assert received.headers["cache-control"] == "private, no-cache"
        reused = admin.get(media_url, headers=cached)
        assert reused.status_code == 304 and reused.content == b""
        received_by_sender = member.get(media_url)
        assert received_by_sender.status_code == 200
        unrelated = student if name == "teacher" else teacher
        assert unrelated.get(media_url, headers=cached).status_code == 404
        summary = admin.get(f"/api/panel/personal-conversations/{chat_id}/messages")
        assert summary.status_code == 200
        assert summary.json()[0]["metadata"]["media"]["file_name"] == "notes.txt"

        removed = member.delete(f"/api/panel/personal-messages/{message['id']}")
        assert removed.status_code == 200
        assert admin.get(media_url).status_code == 404



def test_messenger_pair_requires_both_participants_on_same_platform(api):
    _, users, sessions = api
    with sessions() as db:
        teacher_id = users["teacher-one"]
        student_id = users["student-one"]
        sync_messenger_account(
            db, teacher_id, MessengerPlatform.TELEGRAM,
            external_user_id="teacher-telegram-user",
        )
        db.commit()

        teacher_account, student_account = get_messenger_pair(
            db, teacher_id, student_id, MessengerPlatform.TELEGRAM,
        )
        assert teacher_account is not None
        assert student_account is None

        sync_messenger_account(
            db, student_id, MessengerPlatform.TELEGRAM,
            external_user_id="student-telegram-user",
        )
        db.commit()
        teacher_account, student_account = get_messenger_pair(
            db, teacher_id, student_id, MessengerPlatform.TELEGRAM,
        )
        assert teacher_account is not None
        assert student_account is not None
        assert get_messenger_pair(
            db, teacher_id, student_id, MessengerPlatform.MAX,
        ) == (None, None)


def test_panel_message_client_id_prevents_duplicate_persistence(api):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    assignment = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    conversation_id = assignment.json()["id"]

    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    payload = {"text": "Повторно отправленный запрос", "client_message_id": "retry-key-001"}
    first = teacher.post(
        f"/api/panel/conversations/{conversation_id}/messages",
        json=payload,
    )
    second = teacher.post(
        f"/api/panel/conversations/{conversation_id}/messages",
        json=payload,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    rows = teacher.get(f"/api/panel/conversations/{conversation_id}/messages")
    assert len(rows.json()) == 1


@pytest.mark.parametrize("role,linked,targets", [
    ("teacher", ("student",), {"student-chat"}),
    ("student", ("teacher",), {"teacher-chat"}),
    ("admin", ("student", "teacher"), {"student-chat", "teacher-chat"}),
    ("admin", ("student",), {"student-chat"}),
    ("teacher", ("teacher",), set()),
    ("student", ("student",), set()),
    ("admin", (), set()),
])
def test_panel_delivery_uses_recipient_connection_only(api, role, linked, targets):
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        for party in linked:
            sync_messenger_account(db, users[party + "-one"], "alpha", party, party + "-chat")
        db.commit()
        row = Message(conversation_id=chat.id, sender_id=chat.student_id if role == "student" else chat.teacher_id,
                      sender_role=role, text="Reply", delivery_status="delivered")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db, row, ("alpha",))
        db.commit()
        jobs = db.query(ConnectorDelivery).all()
        assert {job.chat_id for job in jobs} == targets
        for job in jobs:
            assert job_payload(db, job)["text"].endswith("Reply")
            record_result(db, job, "delivered", "provider-id")
        assert row.delivery_status == "delivered"


def test_reply_without_linked_student_is_still_saved(api):
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        sync_messenger_account(db, chat.teacher_id, "alpha", "teacher", "100")
        db.commit()
        receive_message(db, "alpha", {"id":"one", "actor":"teacher", "channel":"private",
            "chat_id":"100", "conversation_id":chat.id, "kind":"text", "text":"Reply"}, ("alpha",), media_path)
        assert db.query(Message).one().text == "Reply"
        assert db.query(ConnectorDelivery).count() == 0


@pytest.mark.parametrize("personal", [False, True])
def test_deleted_last_message_id_cannot_be_reused(api, personal):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    student = make_client()
    login(student, "student-one", "student-password-1")
    if personal:
        created = admin.post("/api/panel/personal-conversations",
                             json={"user_id": users["student-one"]})
        reader = admin
        collection = "personal-conversations"
        resource = "personal-messages"
    else:
        created = admin.post("/api/admin/assignments", json={
            "teacher_id": users["teacher-one"], "student_id": users["student-one"]})
        reader = make_client()
        login(reader, "teacher-one", "teacher-password-1")
        collection = "conversations"
        resource = "messages"
    assert created.status_code == 201
    path = f"/api/panel/{collection}/{created.json()['id']}"
    sent = student.post(path + "/messages", json={"text": "first"})
    assert sent.status_code == 201
    old = sent.json()["id"]
    assert student.delete(f"/api/panel/{resource}/{old}").status_code == 200
    sent = student.post(path + "/messages", json={"text": "second"})
    assert sent.status_code == 201
    assert sent.json()["id"] > old
    sync = reader.post(path + "/sync", json={
        "after_id": old, "known_message_ids": [old], "paged": True, "mark_read": False})
    assert sync.status_code == 200
    assert sync.json()["deleted_message_ids"] == [old]
    assert [row["text"] for row in sync.json()["messages"]] == ["second"]
