import asyncio
import json

"""Regression tests for UknowApp-first message delivery and read receipts."""

from app.models import Assignment, Conversation, Message, User
from app.modules.communication.accounts import get_messenger_pair, sync_messenger_account
from app.modules.communication.contracts import (
    DeliveryResult,
    InboundMessage,
    MessageKind,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMessage,
)
from app.modules.messaging.inbound import process_inbound_message, set_teacher_session
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

    # The student receives the message through the primary UknowApp inbox;
    # no Telegram account or external messenger is required.
    received = student.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    )
    assert received.status_code == 200
    assert received.json()[0]["text"] == "Ответ доступен в UknowApp"

    # Reading the message is a separate event and turns the sender's two grey
    # ticks into two blue ticks on the next authoritative server sync.
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

    admin_received = admin.get(
        f"/api/panel/personal-conversations/{conversation_id}/messages",
    )
    assert admin_received.status_code == 200
    assert admin_received.json()[0]["text"] == "Личное сообщение"

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


class FakeMessengerAdapter:
    def __init__(self, platform):
        self.platform = platform
        self.capabilities = MessengerCapabilities(text=True)
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
    assert metadata["telegram_delivery_errors"][0]["reason"] == "Telegram не подключён"
    assert metadata["telegram_deliveries"] == []


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

        # Only the teacher has Telegram connected; the student receives messages
        # through the UknowApp inbox and does not need a messenger account.
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
        assert metadata["telegram_delivery_errors"][0]["reason"] == (
            "Аккаунт получателя не подключён к TELEGRAM"
        )
        # Incomplete pair: do not use Telegram send/delete APIs at all.
        assert gateway.sent_texts == []
        assert gateway.deleted_messages == []


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
