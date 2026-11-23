import asyncio
import json

import pytest

"""Тесты доставки и статусов прочтения UknowApp."""

from app.models import Assignment, Conversation, Message, User
from app.modules.communication.accounts import get_messenger_pair, sync_messenger_account
from app.modules.communication.contracts import (
    DeliveryResult,
    InboundMessage,
    MessageKind,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)
from app.modules.messaging.inbound import process_inbound_message, set_teacher_session
from app.modules.panel.delivery import deliver_panel_message, save_panel_messenger_results
from app.modules.communication.service import (
    CommunicationService,
    record_messenger_delivery,
)


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



class FakeMessengerAdapter:
    def __init__(self, platform):
        self.platform = platform
        self.capabilities = MessengerCapabilities(text=True, attachments=True)
        self.sent = []

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        self.sent.append(message)
        return DeliveryResult(
            platform=self.platform,
            external_chat_id=message.external_chat_id,
            external_message_id=f"{self.platform.value}-message",
        )


def test_communication_service_registers_multiple_independent_channels():
    import asyncio

    telegram = FakeMessengerAdapter(MessengerPlatform.TELEGRAM)
    max_adapter = FakeMessengerAdapter(MessengerPlatform.MAX)
    communication = CommunicationService([telegram, max_adapter])

    assert communication.platforms == (
        MessengerPlatform.TELEGRAM,
        MessengerPlatform.MAX,
    )

    for platform, adapter in (
        (MessengerPlatform.TELEGRAM, telegram),
        (MessengerPlatform.MAX, max_adapter),
    ):
        result = asyncio.run(communication.send(OutboundMessage(
            platform=platform,
            external_chat_id="recipient",
            content_type=MessageKind.TEXT,
            text="Independent transport",
        )))
        assert result.platform == platform
        assert len(adapter.sent) == 1


def test_messenger_delivery_ledger_does_not_change_uknowapp_message_state():
    metadata = {"source_mode": "web"}
    record_messenger_delivery(
        metadata,
        MessengerPlatform.TELEGRAM,
        errors=[{
            "name": "Student One",
            "role": "student",
            "reason": "Telegram не подключён",
        }],
        status="not_connected",
    )
    record_messenger_delivery(
        metadata,
        MessengerPlatform.MAX,
        delivered=[{
            "user_id": 7,
            "external_message_id": "max-message-1",
            "external_chat_id": "max-chat-1",
        }],
    )

    channels = metadata["messenger_deliveries"]
    assert channels["telegram"]["status"] == "not_connected"
    assert channels["max"]["status"] == "delivered"
    assert metadata["messenger_deliveries"]["telegram"]["errors"][0]["reason"] == "Telegram не подключён"
    assert "telegram_deliveries" not in metadata
    assert "telegram_delivery_errors" not in metadata


class FakeInboundGateway:
    platform = MessengerPlatform.TELEGRAM

    def __init__(self):
        self.sent_texts = []
        self.deleted_messages = []

    async def send_text(self, external_chat_id, text, thread_id=None):
        self.sent_texts.append((external_chat_id, text, thread_id))
        return "confirmation-message"

    async def copy_message(
        self,
        source_chat_id,
        source_message_id,
        target_chat_id,
        target_thread_id=None,
        caption=None,
    ):
        raise AssertionError("No Telegram copy should be attempted for an unlinked student")

    async def archive_media(self, inbound, row):
        return None

    async def delete_message(self, external_chat_id, external_message_id):
        self.deleted_messages.append((external_chat_id, external_message_id))


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


def test_teacher_telegram_reply_without_student_telegram_is_delivered_in_uknowapp(api):
    _, users, sessions = api
    gateway = FakeInboundGateway()

    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        assignment = Assignment(
            teacher_id=teacher.id,
            student_id=student.id,
            active=True,
        )
        db.add(assignment)
        db.flush()
        conversation = Conversation(
            assignment_id=assignment.id,
            teacher_id=teacher.id,
            student_id=student.id,
            status="active",
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        # Telegram подключён только у преподавателя.
        sync_messenger_account(
            db,
            teacher.id,
            MessengerPlatform.TELEGRAM,
            external_user_id="teacher-telegram-user",
            external_chat_id="teacher-telegram-chat",
        )
        db.commit()
        set_teacher_session(db, teacher, conversation)

        inbound = InboundMessage(
            platform=MessengerPlatform.TELEGRAM,
            event_id="telegram:teacher:101",
            external_user_id="teacher-telegram-user",
            external_chat_id="teacher-telegram-chat",
            external_message_id="101",
            content_type=MessageKind.TEXT,
            text="Ответ преподавателя без Telegram у ученика",
        )
        result = asyncio.run(
            process_inbound_message(db, inbound, gateway),
        )
        duplicate_result = asyncio.run(
            process_inbound_message(db, inbound, gateway),
        )

        row = db.query(Message).filter(
            Message.conversation_id == conversation.id,
        ).one()
        metadata = json.loads(row.metadata_json or "{}")

        assert result.refresh_teacher_id == teacher.id
        assert duplicate_result.refresh_teacher_id == teacher.id
        assert db.query(Message).filter(
            Message.conversation_id == conversation.id,
        ).count() == 1
        assert row.delivery_status == "delivered"
        assert row.text == inbound.text
        assert metadata["messenger_deliveries"]["telegram"]["status"] == "not_connected"
        assert metadata["messenger_deliveries"]["telegram"]["errors"][0]["reason"] == (
            "Аккаунт получателя не подключён к TELEGRAM"
        )
        # Если получатель не подключён, во внешний чат ничего не отправляется.
        assert gateway.sent_texts == []
        assert gateway.deleted_messages == []



@pytest.mark.parametrize(
    ("sender_role", "linked_roles", "expected_chats", "expected_status"),
    [
        ("teacher", ("student",), ["student-chat"], "delivered"),
        ("student", ("teacher",), ["teacher-chat"], "delivered"),
        ("admin", ("student",), ["student-chat"], "partial"),
        ("admin", ("teacher",), ["teacher-chat"], "partial"),
        ("admin", ("student", "teacher"), ["student-chat", "teacher-chat"], "delivered"),
        ("teacher", ("teacher",), [], "not_connected"),
        ("student", ("student",), [], "not_connected"),
        ("admin", (), [], "not_connected"),
    ],
)
def test_panel_delivery_uses_recipient_connection_only(
    api, sender_role, linked_roles, expected_chats, expected_status,
):
    _, users, sessions = api
    adapter = FakeMessengerAdapter(MessengerPlatform.TELEGRAM)
    communication = CommunicationService([adapter])

    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        assignment = Assignment(
            teacher_id=teacher.id, student_id=student.id, active=True,
        )
        db.add(assignment)
        db.flush()
        conversation = Conversation(
            assignment_id=assignment.id,
            teacher_id=teacher.id,
            student_id=student.id,
            status="active",
        )
        db.add(conversation)
        db.flush()
        for role, user, chat_id in (
            ("teacher", teacher, "teacher-chat"),
            ("student", student, "student-chat"),
        ):
            if role in linked_roles:
                sync_messenger_account(
                    db, user.id, MessengerPlatform.TELEGRAM,
                    external_user_id=chat_id, external_chat_id=chat_id,
                )

        recipients = (
            [(student, "student")] if sender_role == "teacher"
            else [(teacher, "teacher")] if sender_role == "student"
            else [(student, "student"), (teacher, "teacher")]
        )
        row = Message(
            conversation_id=conversation.id,
            sender_id=student.id if sender_role == "student" else teacher.id,
            sender_role=sender_role,
            text="Сообщение из приложения",
            delivery_status="delivered",
        )
        db.add(row)
        db.commit()

        result = asyncio.run(deliver_panel_message(
            db, communication, row, conversation, recipients,
            sender_role, student, row.text, MessageKind.TEXT,
        ))
        save_panel_messenger_results(db, row, conversation, result)

        assert [message.external_chat_id for message in adapter.sent] == expected_chats
        assert all(message.text for message in adapter.sent)
        refreshed = db.get(Message, row.id)
        ledger = json.loads(refreshed.metadata_json)["messenger_deliveries"]["telegram"]
        assert ledger["status"] == expected_status
        assert len(ledger["delivered"]) == len(expected_chats)
        assert refreshed.delivery_status == "delivered"
        assert all(entry["external_chat_id"] in expected_chats for entry in ledger["delivered"])


def test_single_connected_student_receives_attachment_without_teacher_connection(api):
    _, users, sessions = api
    adapter = FakeMessengerAdapter(MessengerPlatform.TELEGRAM)
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        assignment = Assignment(
            teacher_id=teacher.id, student_id=student.id, active=True,
        )
        db.add(assignment)
        db.flush()
        conversation = Conversation(
            assignment_id=assignment.id,
            teacher_id=teacher.id,
            student_id=student.id,
            status="active",
        )
        db.add(conversation)
        db.flush()
        sync_messenger_account(
            db, student.id, MessengerPlatform.TELEGRAM,
            external_user_id="student-id", external_chat_id="student-chat",
        )
        row = Message(
            conversation_id=conversation.id, sender_id=teacher.id,
            sender_role="teacher", content_type="document",
            text="Файл для ученика", delivery_status="delivered",
        )
        db.add(row)
        db.commit()
        media = OutboundMedia(
            storage_key="documents/lesson.pdf",
            file_name="lesson.pdf",
            mime_type="application/pdf",
        )
        result = asyncio.run(deliver_panel_message(
            db, CommunicationService([adapter]), row, conversation,
            [(student, "student")], "teacher", student,
            row.text, MessageKind.DOCUMENT, media=media,
        ))
        assert result["telegram"]["delivered"][0]["user_id"] == student.id
        assert len(adapter.sent) == 1
        assert adapter.sent[0].media == media
        assert adapter.sent[0].external_chat_id == "student-chat"


def test_independent_routing_across_multiple_messengers(api):
    _, users, sessions = api
    telegram = FakeMessengerAdapter(MessengerPlatform.TELEGRAM)
    max_adapter = FakeMessengerAdapter(MessengerPlatform.MAX)
    communication = CommunicationService([telegram, max_adapter])

    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        assignment = Assignment(
            teacher_id=teacher.id, student_id=student.id, active=True,
        )
        db.add(assignment)
        db.flush()
        conversation = Conversation(
            assignment_id=assignment.id, teacher_id=teacher.id,
            student_id=student.id, status="active",
        )
        db.add(conversation)
        db.flush()
        sync_messenger_account(
            db, student.id, MessengerPlatform.TELEGRAM,
            external_user_id="student-telegram", external_chat_id="student-tg-chat",
        )
        sync_messenger_account(
            db, teacher.id, MessengerPlatform.MAX,
            external_user_id="teacher-max", external_chat_id="teacher-max-chat",
        )
        row = Message(
            conversation_id=conversation.id, sender_id=teacher.id,
            sender_role="admin", text="Сообщение всем", delivery_status="delivered",
        )
        db.add(row)
        db.commit()
        results = asyncio.run(deliver_panel_message(
            db, communication, row, conversation,
            [(student, "student"), (teacher, "teacher")],
            "admin", student, row.text, MessageKind.TEXT,
        ))
        save_panel_messenger_results(db, row, conversation, results)
        assert [m.external_chat_id for m in telegram.sent] == ["student-tg-chat"]
        assert [m.external_chat_id for m in max_adapter.sent] == ["teacher-max-chat"]
        metadata = json.loads(db.get(Message, row.id).metadata_json)
        assert metadata["messenger_deliveries"]["telegram"]["status"] == "partial"
        assert metadata["messenger_deliveries"]["max"]["status"] == "partial"

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
