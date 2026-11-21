"""Regression checks for Telegram panel queries and plain-text delivery."""

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
