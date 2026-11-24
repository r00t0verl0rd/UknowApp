"""Тесты запросов панели и текстовых сообщений."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Assignment, Conversation, Message, User
from app.modules.communication.accounts import sync_messenger_account
from app.modules.communication.contracts import (
    InboundMessage, MessageKind, MessengerPlatform,
)
from app.modules.messaging.inbound import process_inbound_message
from app.modules.telegram.teacher import teacher_chat_view, teacher_conversations


class RecordingGateway:
    platform = MessengerPlatform.TELEGRAM

    def __init__(self):
        self.copied = []
        self.sent = []

    async def send_text(self, chat_id, text, thread_id=None):
        self.sent.append((chat_id, text))
        return "500"

    async def copy_message(self, source_chat_id, source_message_id, target_chat_id,
                           target_thread_id=None, caption=None):
        self.copied.append((source_chat_id, target_chat_id))
        return "501"

    async def archive_media(self, inbound, row):
        return None

    async def delete_message(self, chat_id, message_id):
        return None


def _assignment(db, teacher_id, student_id):
    assignment = Assignment(teacher_id=teacher_id, student_id=student_id, active=True)
    db.add(assignment)
    db.flush()
    conversation = Conversation(
        assignment_id=assignment.id,
        teacher_id=teacher_id,
        student_id=student_id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    return conversation


def _message(db, conversation, sender, role, at, text, *, read_at=None,
             delivery_status="delivered"):
    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=role,
        text=text,
        content_type="text",
        metadata_json=json.dumps({"teacher_read_at": read_at}),
        delivery_status=delivery_status,
        created_at=at,
    )
    db.add(row)
    db.commit()
    return row


def test_teacher_panel_preserves_pending_and_latest_previews(api):
    _, users, sessions = api
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        conversation = _assignment(db, teacher.id, student.id)
        now = datetime.now(UTC)
        _message(db, conversation, student, "student", now, "old student")
        _message(db, conversation, teacher, "teacher", now + timedelta(seconds=1), "reply")
        _message(db, conversation, student, "student", now + timedelta(seconds=2), "already read",
                 read_at=now.isoformat())
        _message(db, conversation, student, "student", now + timedelta(seconds=3), "pending")
        _message(db, conversation, student, "student", now + timedelta(seconds=4),
                 "blocked", delivery_status="blocked_contact")
        _message(db, conversation, teacher, "admin", now + timedelta(seconds=5), "admin latest")

        items = teacher_conversations(db, teacher)
        assert len(items) == 1
        assert items[0]["unanswered"] == 1
        assert items[0]["unread"][0].text == "pending"
        assert items[0]["latest"].text == "admin latest"


def test_teacher_chat_shows_twelve_messages_and_exact_total(api):
    _, users, sessions = api
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        conversation = _assignment(db, teacher.id, student.id)
        now = datetime.now(UTC)
        for i in range(16):
            _message(db, conversation, student, "student", now + timedelta(seconds=i),
                     f"number-{i}")
        rendered = teacher_chat_view(db, conversation)
        assert "Показаны последние 12 из 16 сообщений." in rendered
        assert "number-15" in rendered
        assert "number-0" not in rendered


def test_student_plain_text_with_both_telegram_accounts_is_delivered(api):
    _, users, sessions = api
    gateway = RecordingGateway()
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        conversation = _assignment(db, teacher.id, student.id)
        sync_messenger_account(
            db, teacher.id, MessengerPlatform.TELEGRAM,
            external_user_id="teacher-100", external_chat_id="100",
        )
        sync_messenger_account(
            db, student.id, MessengerPlatform.TELEGRAM,
            external_user_id="student-200", external_chat_id="200",
        )
        db.commit()

        inbound = InboundMessage(
            platform=MessengerPlatform.TELEGRAM,
            event_id="telegram:200:21",
            external_user_id="student-200",
            external_chat_id="200",
            external_message_id="21",
            content_type=MessageKind.TEXT,
            text="Текст ученика",
        )
        result = asyncio.run(process_inbound_message(db, inbound, gateway))
        assert result.refresh_teacher_id == teacher.id
        messages = db.scalars(
            select(Message).where(Message.conversation_id == conversation.id),
        ).all()
        assert len(messages) == 1
        assert messages[0].delivery_status == "delivered"
        assert gateway.copied == []
        assert gateway.sent == []


def test_student_message_refreshes_teacher_panel_without_replacing_it(api):
    """New messages from a different student must not delete/re-send the Telegram panel."""
    from app.models import TeacherPanel, TeacherSession
    from app.modules.messaging.inbound import set_teacher_session
    from app.modules.telegram.teacher import (
        TEACHER_KEYBOARD_VERSION,
        teacher_keyboard_signature,
        teacher_panel_view,
        update_teacher_panel,
    )

    _, users, sessions = api
    gateway = RecordingGateway()
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        first = db.get(User, users["student-one"])
        second = db.get(User, users["student-two"])
        old_conversation = _assignment(db, teacher.id, first.id)
        new_conversation = _assignment(db, teacher.id, second.id)
        sync_messenger_account(
            db, teacher.id, MessengerPlatform.TELEGRAM,
            external_user_id="teacher-100", external_chat_id="100",
        )
        sync_messenger_account(
            db, second.id, MessengerPlatform.TELEGRAM,
            external_user_id="student-200", external_chat_id="200",
        )
        set_teacher_session(db, teacher, old_conversation)
        _, markup, _ = teacher_panel_view(db, teacher, selected_student_name=first.full_name)
        db.add(TeacherPanel(
            teacher_id=teacher.id, chat_id=100, message_id=321,
            keyboard_version=TEACHER_KEYBOARD_VERSION,
            keyboard_signature=teacher_keyboard_signature(markup),
        ))
        db.commit()

        inbound = InboundMessage(
            platform=MessengerPlatform.TELEGRAM,
            event_id="telegram:200:one-time-1",
            external_user_id="student-200",
            external_chat_id="200",
            external_message_id="456",
            content_type=MessageKind.TEXT,
            text="Новое сообщение из другого диалога",
        )
        result = asyncio.run(process_inbound_message(db, inbound, gateway))
        assert result.refresh_teacher_id == teacher.id
        assert not result.force_teacher_panel_refresh
        assert db.get(TeacherSession, teacher.id).conversation_id == old_conversation.id

        class RecordingBot:
            def __init__(self):
                self.edited = []
                self.sent = []
                self.deleted = []

            async def edit_message_text(self, **kwargs):
                self.edited.append(kwargs)

            async def send_message(self, **kwargs):
                self.sent.append(kwargs)

            async def delete_message(self, **kwargs):
                self.deleted.append(kwargs)

        bot = RecordingBot()
        assert asyncio.run(update_teacher_panel(bot, db, teacher))
        assert len(bot.edited) == 1
        assert bot.edited[0]["message_id"] == 321
        assert bot.sent == []
        assert bot.deleted == []
        assert db.get(TeacherPanel, teacher.id).message_id == 321

        duplicate = asyncio.run(process_inbound_message(db, inbound, gateway))
        assert not duplicate.force_teacher_panel_refresh
        assert db.get(TeacherSession, teacher.id).conversation_id == old_conversation.id

def test_admin_web_message_notifies_teacher_once_even_with_stale_keyboard(api, monkeypatch):
    from app.main import app
    from app.models import TeacherPanel, TeacherSession
    from app.modules.panel import delivery as panel_delivery
    from app.modules.communication.contracts import DeliveryResult, MessengerCapabilities
    from app.modules.communication.service import CommunicationService

    class RecordingAdapter:
        platform = MessengerPlatform.TELEGRAM
        capabilities = MessengerCapabilities(text=True, attachments=True)
        def __init__(self):
            self.sent = []
        async def send(self, message):
            self.sent.append(message)
            return DeliveryResult(platform=self.platform,
                                  external_chat_id=message.external_chat_id,
                                  external_message_id=str(1000 + len(self.sent)))

    class RecordingBot:
        def __init__(self):
            self.edited = []
            self.sent = []
            self.deleted = []
        async def edit_message_text(self, **kwargs):
            self.edited.append(kwargs)
        async def send_message(self, **kwargs):
            self.sent.append(kwargs)
            raise AssertionError("Background refresh must not create a new teacher panel")
        async def delete_message(self, **kwargs):
            self.deleted.append(kwargs)

    make_client, users, sessions = api
    telegram = RecordingAdapter()
    bot = RecordingBot()
    monkeypatch.setattr(panel_delivery, "SessionLocal", sessions)
    monkeypatch.setattr(app.state, "telegram_bot", bot, raising=False)
    monkeypatch.setattr(app.state, "communication", CommunicationService([telegram]), raising=False)
    admin = make_client()
    login = admin.post("/api/auth/login", json={
        "username": "test-admin", "password": "a-long-test-password-123",
    })
    assert login.status_code == 200
    created = admin.post("/api/admin/assignments", json={
        "teacher_id": users["teacher-one"], "student_id": users["student-one"],
    })
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        sync_messenger_account(db, teacher.id, MessengerPlatform.TELEGRAM,
                               external_user_id="100", external_chat_id="100")
        sync_messenger_account(db, student.id, MessengerPlatform.TELEGRAM,
                               external_user_id="200", external_chat_id="200")
        db.add(TeacherSession(teacher_id=teacher.id, conversation_id=conversation_id))
        db.add(TeacherPanel(teacher_id=teacher.id, chat_id=100, message_id=321,
                            keyboard_version=0, keyboard_signature="stale-keyboard"))
        db.commit()

    url = f"/api/panel/conversations/{conversation_id}/messages"
    payload = {"text": "Текст от администратора", "client_message_id": "admin-once-001"}
    first = admin.post(url, json=payload)
    repeated = admin.post(url, json=payload)
    assert first.status_code == repeated.status_code == 201
    assert first.json()["id"] == repeated.json()["id"]
    assert sorted(message.external_chat_id for message in telegram.sent) == ["100", "200"]
    assert len([m for m in telegram.sent if m.external_chat_id == "100"]) == 1
    assert len(bot.edited) == 1
    assert bot.edited[0]["message_id"] == 321
    assert "Администратор: Текст от администратора" in bot.edited[0]["text"]
    assert bot.sent == bot.deleted == []

    # If the panel was deleted, the teacher still gets a single direct alert.
    with sessions() as db:
        db.delete(db.get(TeacherPanel, users["teacher-one"]))
        db.commit()
    second = admin.post(url, json={
        "text": "Следующее сообщение", "client_message_id": "admin-once-002",
    })
    assert second.status_code == 201
    assert len([m for m in telegram.sent if m.external_chat_id == "100"]) == 2
    assert len(bot.edited) == 1
    assert bot.sent == []
    with sessions() as db:
        assert db.query(Message).filter(Message.conversation_id == conversation_id).count() == 2
