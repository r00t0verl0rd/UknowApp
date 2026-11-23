"""Тесты бота, панели преподавателя и вложений."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import FSInputFile

from app.models import Assignment, Conversation, Message, User
from app.modules.communication.accounts import sync_messenger_account
from app.modules.communication.contracts import (
    InboundMessage,
    MessageKind,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)
from app.modules.messaging.inbound import process_inbound_message
from app.modules.telegram import transport
from app.modules.telegram.adapter import TelegramAdapter
from app.modules.telegram.teacher import (
    handle_teacher_keyboard_message,
    teacher_chat_view,
    teacher_conversations,
    teacher_panel_view,
)


def test_self_hosted_api_archives_large_mounted_file(tmp_path, monkeypatch):
    cache = tmp_path / "remote-cache"
    cache.mkdir()
    size = 21 * 1024 * 1024
    with (cache / "lesson.bin").open("wb") as sample:
        sample.truncate(size)
    monkeypatch.setattr(transport, "TELEGRAM_FILES_DIR", cache)
    monkeypatch.setattr(transport, "TELEGRAM_API_URL", "http://telegram-private:8081")

    async def run():
        bot = transport.create_telegram_bot("123:" + "a" * 32)
        try:
            assert bot.session.api.api_url(bot.token, "getMe").startswith("http://telegram-private:8081/")
            async def get_file(self, file_id):
                return SimpleNamespace(file_path="/var/lib/telegram-bot-api/lesson.bin")
            monkeypatch.setattr(type(bot), "get_file", get_file)
            adapter = TelegramAdapter(bot, tmp_path / "archive")
            inbound, = adapter.normalize_event({
                "chat_id": 1, "message_id": 2, "content_type": "document",
                "media": {"file_id": "fixture", "file_name": "lesson.bin", "file_size": size},
            })
            row = SimpleNamespace(id=2, conversation_id=1, metadata_json="{}")
            await adapter.archive_media(inbound, row)
            media = json.loads(row.metadata_json)["media"]
            assert media["archive_status"] == "stored"
            assert (tmp_path / "archive" / media["local_path"]).stat().st_size == size
        finally:
            await bot.session.close()

    asyncio.run(run())


class NoMediaCopyGateway:
    platform = MessengerPlatform.TELEGRAM

    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_text(self, external_chat_id, text, thread_id=None):
        self.sent.append((external_chat_id, text, thread_id))
        return "42"

    async def copy_message(self, *args, **kwargs):
        raise AssertionError("Text messages must use the teacher panel, not media copy")

    async def archive_media(self, inbound, row):
        return None

    async def delete_message(self, external_chat_id, external_message_id):
        self.deleted.append((external_chat_id, external_message_id))


def create_conversation(db, teacher_id, student_id):
    assignment = Assignment(
        teacher_id=teacher_id, student_id=student_id, active=True,
    )
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


def test_student_plain_text_appears_in_teacher_panel_without_media_copy(api):
    _, users, sessions = api
    gateway = NoMediaCopyGateway()
    with sessions() as db:
        teacher_id = users["teacher-one"]
        student_id = users["student-one"]
        conversation = create_conversation(db, teacher_id, student_id)
        sync_messenger_account(
            db, teacher_id, MessengerPlatform.TELEGRAM,
            external_user_id="teacher-telegram", external_chat_id="100",
        )
        sync_messenger_account(
            db, student_id, MessengerPlatform.TELEGRAM,
            external_user_id="student-telegram", external_chat_id="200",
        )
        db.commit()
        inbound = InboundMessage(
            platform=MessengerPlatform.TELEGRAM,
            event_id="telegram:200:77",
            external_user_id="student-telegram",
            external_chat_id="200",
            external_message_id="77",
            content_type=MessageKind.TEXT,
            text="Проверяем обычное сообщение",
        )

        first = asyncio.run(process_inbound_message(db, inbound, gateway))
        duplicate = asyncio.run(process_inbound_message(db, inbound, gateway))
        rows = db.query(Message).filter(Message.conversation_id == conversation.id).all()
        assert first.refresh_teacher_id == teacher_id
        assert duplicate.refresh_teacher_id == teacher_id
        assert len(rows) == 1
        assert rows[0].text == inbound.text
        assert rows[0].delivery_status == "delivered"
        assert "teacher_inbox_media_message_id" not in json.loads(rows[0].metadata_json)
        panel_text, _, _ = teacher_panel_view(db, db.get(User, teacher_id))
        assert inbound.text in panel_text
        assert gateway.sent == []
        assert gateway.deleted == []


def test_teacher_panel_preserves_unread_state_and_bounded_history(api):
    _, users, sessions = api
    with sessions() as db:
        teacher_id = users["teacher-one"]
        student_id = users["student-one"]
        conversation = create_conversation(db, teacher_id, student_id)
        started = datetime(2026, 1, 1, tzinfo=UTC)
        rows = []
        for index in range(20):
            sender_role = (
                "teacher" if index == 14
                else "student" if index in (15, 16)
                else "admin"
            )
            metadata = (
                {"teacher_read_at": started.isoformat() if index == 15 else None}
                if sender_role == "student" else {}
            )
            rows.append(Message(
                conversation_id=conversation.id,
                sender_id=teacher_id if sender_role != "student" else student_id,
                sender_role=sender_role,
                text=f"Telegram history {index}",
                content_type="text",
                metadata_json=json.dumps(metadata),
                delivery_status="delivered",
                created_at=started + timedelta(minutes=index),
            ))
        db.add_all(rows)
        db.commit()

        teacher = db.get(User, teacher_id)
        items = teacher_conversations(db, teacher)
        assert len(items) == 1
        assert items[0]["unanswered"] == 1
        assert items[0]["unread"][0].text == "Telegram history 16"
        assert items[0]["latest"].text == "Telegram history 19"
        chat_text = teacher_chat_view(db, conversation)
        assert "Показаны последние 12 из 20 сообщений." in chat_text
        assert "Telegram history 19" in chat_text
        assert "Telegram history 7" not in chat_text
        panel_text, _, _ = teacher_panel_view(db, teacher)
        assert "1 новых" in panel_text
        assert "Telegram history 16" in panel_text
        assert "Администратор: Telegram history 19" in panel_text
        assert db.get(User, student_id).full_name + ": Telegram history 16" in chat_text
        assert "Ученик: Telegram history 16" not in chat_text


def test_ordinary_teacher_reply_does_not_build_keyboard_previews(api, monkeypatch):
    _, users, sessions = api
    import app.modules.telegram.teacher as teacher_module

    def fail_if_called(*args, **kwargs):
        raise AssertionError("A normal reply must not load all teacher conversations")

    monkeypatch.setattr(teacher_module, "teacher_keyboard_actions", fail_if_called)
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        incoming = InboundMessage(
            platform=MessengerPlatform.TELEGRAM,
            event_id="telegram:100:123",
            external_user_id="teacher-telegram",
            external_chat_id="100",
            external_message_id="123",
            content_type=MessageKind.TEXT,
            text="Обычный ответ преподавателя",
        )
        outcome = asyncio.run(
            handle_teacher_keyboard_message(db, incoming, teacher, NoMediaCopyGateway()),
        )
        assert not outcome.handled


def test_telegram_outbound_media_uses_streaming_file_upload(tmp_path):
    class RecordingBot:
        def __init__(self):
            self.upload = None
            self.params = None

        async def send_document(self, *, document, **kwargs):
            self.upload = document
            self.params = kwargs
            return SimpleNamespace(message_id=818)

    stored = tmp_path / "conversation" / "attachment.bin"
    stored.parent.mkdir()
    stored.write_bytes(b"test attachment")
    bot = RecordingBot()
    adapter = TelegramAdapter(bot, media_dir=tmp_path)
    message = OutboundMessage(
        platform=MessengerPlatform.TELEGRAM,
        external_chat_id="123",
        external_thread_id="456",
        content_type=MessageKind.DOCUMENT,
        text="Подпись к файлу",
        media=OutboundMedia(
            storage_key="conversation/attachment.bin",
            file_name="attachment.bin",
        ),
    )

    result = asyncio.run(adapter.send(message))
    assert result.external_message_id == "818"
    assert isinstance(bot.upload, FSInputFile)
    assert Path(bot.upload.path).resolve() == stored.resolve()
    assert bot.params == {
        "chat_id": 123,
        "message_thread_id": 456,
        "caption": "Подпись к файлу",
    }
