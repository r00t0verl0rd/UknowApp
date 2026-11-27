"""Проверка доступа и подготовка сообщений для API."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, Conversation, Message
from app.modules.auth.permissions import permits


def panel_visible_conversation(db: Session, principal: dict, conversation_id: int) -> Conversation:
    # Проверяем доступ к диалогу на сервере, даже если клиент подменит его ID.
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    if not permits(principal, "dialogs.observe"):
        if principal.get("role") not in {"teacher", "student"}:
            raise HTTPException(status_code=404, detail="Переписка не найдена")
        assignment = db.get(Assignment, conversation.assignment_id) if conversation.assignment_id else None
        participant_id = (
            conversation.teacher_id if principal["role"] == "teacher" else conversation.student_id
        )
        if (
            not assignment or not assignment.active
            or (assignment.teacher_id, assignment.student_id) != (conversation.teacher_id, conversation.student_id)
            or participant_id != principal["user_id"]
            or conversation.status != "active"
        ):
            raise HTTPException(status_code=404, detail="Переписка не найдена")
        if principal["role"] == "student":
            current_conversation_id = db.scalar(
                select(Conversation.id)
                .join(Assignment, Conversation.assignment_id == Assignment.id)
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


def panel_message_dict(
    item: Message,
    expose_internal_metadata: bool = True,
    principal: dict | None = None,
) -> dict:
    # Внутренние ID внешних каналов и file_id не раскрываем учителю в обычном ответе API.
    metadata = json.loads(item.metadata_json or "{}")
    if metadata.get("source_mode") == "web":
        metadata.setdefault("web_sender_role", item.sender_role)
    # Сохраняем формат ответа для старых клиентов.
    metadata["teacher_read_at"] = item.teacher_read_at
    metadata["student_read_at"] = item.student_read_at
    if item.client_message_id:
        metadata["client_message_id"] = item.client_message_id
    if expose_internal_metadata and item.source_platform:
        metadata.update(source_platform=item.source_platform, source_event_id=item.source_event_id or "")
    if not expose_internal_metadata:
        for key in (
            "source_chat_id", "source_thread_id", "source_platform", "source_event_id",
            "messenger_deliveries",
            "teacher_inbox_media_message_id", "teacher_inbox_notice_message_id", "legacy_source_message_id", "legacy_destination_message_id",
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
        **({"admin_read_at": item.admin_read_at} if principal and principal.get("role") == "admin" else {}),
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
        # Сообщение считается доставленным после сохранения в UknowApp.
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



def panel_message_status_dict(item: Message, principal: dict) -> dict:
    """Вернуть изменённые статусы загруженных сообщений."""
    metadata = json.loads(item.metadata_json or "{}")
    if item.sender_role == "teacher":
        read_at = item.student_read_at
    elif item.sender_role == "student":
        read_at = item.teacher_read_at
    elif item.sender_role == "admin":
        read_at = item.teacher_read_at and item.student_read_at
    else:
        read_at = None
    result = {
        "id": item.id,
        "delivery_status": (
            "blocked_contact" if item.delivery_status == "blocked_contact" else "delivered"
        ),
        "panel_read_at": read_at,
    }
    changed_metadata = {"teacher_read_at": item.teacher_read_at, "student_read_at": item.student_read_at}
    media = metadata.get("media")
    if isinstance(media, dict):
        changed_metadata["media"] = {
            key: media[key]
            for key in ("kind", "file_name", "mime_type", "file_size", "archive_status")
            if key in media
        }
    if principal.get("role") == "admin":
        result["admin_read_at"] = item.admin_read_at
        changed_metadata.update({
            key: metadata[key]
            for key in (
                "messenger_deliveries",
            )
            if key in metadata
        })
    if changed_metadata:
        result["metadata"] = changed_metadata
    return result
