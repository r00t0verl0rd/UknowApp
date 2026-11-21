"""Regression tests for UknowApp-first message delivery and read receipts."""

from app.modules.communication.contracts import (
    DeliveryResult,
    MessageKind,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMessage,
)
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
        json={"text": "Личное сообщение"},
    )
    assert sent.status_code == 201
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
