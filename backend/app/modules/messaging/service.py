"""Conversation access checks and safe message serialization."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, Conversation, Message, User


def _panel_visible_conversation(db: Session, principal: dict, conversation_id: int) -> Conversation:
    # Проверяем доступ к диалогу на сервере, даже если клиент подменит его ID.
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    if principal["role"] in {"teacher", "student"}:
        participant_id = (
            conversation.teacher_id if principal["role"] == "teacher" else conversation.student_id
        )
        if (
            participant_id != principal["user_id"]
            or conversation.status != "active"
        ):
            raise HTTPException(status_code=404, detail="Переписка не найдена")
        if principal["role"] == "student":
            current_conversation_id = db.scalar(
                select(Conversation.id)
                .join(Assignment, Conversation.assignment_id == Assignment.id)
                .join(User, Assignment.teacher_id == User.id)
                .where(
                    Assignment.student_id == principal["user_id"],
                    Assignment.active.is_(True),
                    Conversation.status == "active",
                )
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(1),
            )
            if current_conversation_id != conversation.id:
                raise HTTPException(status_code=404, detail="Переписка не найдена")
    return conversation


def _panel_message_dict(
    item: Message,
    expose_internal_metadata: bool = True,
    principal: dict | None = None,
) -> dict:
    # Внутренние Telegram ID и file_id не раскрываем учителю в обычном ответе API.
    metadata = json.loads(item.metadata_json or "{}")
    if not expose_internal_metadata:
        for key in (
            "source_chat_id", "source_thread_id", "source_platform", "source_event_id",
            "telegram_deliveries", "telegram_delivery_errors", "messenger_deliveries",
            "teacher_inbox_media_message_id", "teacher_inbox_notice_message_id",
        ):
            metadata.pop(key, None)
        for key in ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation"):
            attachment = metadata.get(key)
            if isinstance(attachment, dict):
                attachment.pop("file_id", None)
                attachment.pop("file_unique_id", None)
        media = metadata.get("media")
        if isinstance(media, dict):
            metadata["media"] = {
                key: media.get(key)
                for key in ("kind", "file_name", "mime_type", "file_size", "archive_status")
                if key in media
            }
    return {
        "id": item.id,
        "sender": item.sender.full_name if item.sender else "Администратор",
        "sender_role": item.sender_role,
        "can_delete": bool(
            principal
            and item.sender_role == principal["role"]
            and (
                principal["role"] == "admin"
                or item.sender_id == principal.get("user_id")
            ),
        ),
        "content_type": item.content_type,
        "text": item.text,
        "metadata": metadata,
        # A persisted message is delivered to its UknowApp conversation.
        # Messenger transport results are exposed separately to administrators.
        "delivery_status": (
            "blocked_contact" if item.delivery_status == "blocked_contact" else "delivered"
        ),
        "panel_read_at": (
            metadata.get("student_read_at") if item.sender_role == "teacher"
            else metadata.get("teacher_read_at") if item.sender_role == "student"
            else (
                metadata.get("teacher_read_at") and metadata.get("student_read_at")
                if item.sender_role == "admin" else None
            )
        ),
        "created_at": item.created_at.isoformat(),
    }
