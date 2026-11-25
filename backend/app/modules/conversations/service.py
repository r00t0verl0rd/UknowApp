"""Данные переписок и счётчики непрочитанных."""

import json

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update
from app.infrastructure.storage.message_metadata import metadata_value
from app.models import Conversation, Message
from app.modules.users.service import user_dict


def conversation_dicts(
    db: Session,
    conversations: list[Conversation],
    include_messenger_accounts: bool = True,
    viewer_role: str = "teacher",
) -> list[dict]:
    if not conversations:
        return []

    conversation_ids = [item.id for item in conversations]
    summaries = _summary_rows(db, conversation_ids)

    result = []
    for conversation in conversations:
        _, message_count, teacher_unread, student_unread, admin_unread, last_message = summaries[conversation.id]
        unread_count = {"teacher": teacher_unread, "student": student_unread, "admin": admin_unread}.get(viewer_role, teacher_unread)
        result.append({
            "id": conversation.id,
            "status": conversation.status,
            "created_at": conversation.created_at.isoformat(),
            "teacher": user_dict(conversation.teacher, include_messenger_accounts=include_messenger_accounts),
            "student": user_dict(conversation.student, include_messenger_accounts=include_messenger_accounts),
            "last_message": _message_preview(last_message),
            "last_message_at": last_message.created_at.isoformat() if last_message else None,
            "message_count": message_count,
            "unread_count": unread_count,
        })
    return result


def conversation_dict(
    db: Session, conversation: Conversation, include_messenger_accounts: bool = True,
) -> dict:
    return conversation_dicts(db, [conversation], include_messenger_accounts)[0]



def _message_preview(item: Message | None) -> str:
    if item is None:
        return "Переписка пока пуста"
    if item.content_type == "text":
        return item.text or "Сообщение"
    metadata = json.loads(item.metadata_json or "{}")
    media_name = (metadata.get("media") or {}).get("file_name")
    label = {
        "photo": "🖼 Фотография",
        "voice": "🎤 Голосовое сообщение",
        "audio": "🎵 Аудио",
        "video": "🎬 Видео",
        "video_note": "⭕ Видеосообщение",
        "document": "📎 Документ",
        "sticker": "Стикер",
        "animation": "GIF-анимация",
    }.get(item.content_type, "📎 Вложение")
    return (media_name or label) + ((": " + item.text) if item.text else "")


def _unread_condition(db, role: str):
    teacher_unread = and_(
        Message.sender_role.in_(("student", "admin")),
        metadata_value(db, Message.metadata_json, "teacher_read_at").is_(None),
    )
    student_unread = and_(
        Message.sender_role.in_(("teacher", "admin")),
        metadata_value(db, Message.metadata_json, "student_read_at").is_(None),
    )
    if role == "admin":
        return and_(Message.sender_role.in_(("teacher", "student")), or_(teacher_unread, student_unread))
    return student_unread if role == "student" else teacher_unread


def _summary_rows(db, conversation_ids):
    # Read scalar columns rather than ORM attributes: triggers may have changed
    # a Conversation already in the session identity map.
    rows = db.execute(
        select(Conversation.id, Conversation.message_count, Conversation.teacher_unread_count,
               Conversation.student_unread_count, Conversation.admin_unread_count, Message)
        .outerjoin(Message, Message.id == Conversation.last_message_id)
        .where(Conversation.id.in_(conversation_ids))
    ).all()
    return {row[0]: row for row in rows}


def conversation_event_summaries(db: Session, conversation: Conversation) -> dict[str, dict]:
    """Constant-size indexed summary for all roles."""
    _, total, teacher_unread, student_unread, admin_unread, last_message = _summary_rows(db, [conversation.id])[conversation.id]
    last_message_preview = _message_preview(last_message)
    if len(last_message_preview) > 240:
        last_message_preview = last_message_preview[:237] + "…"
    common = {
        "id": conversation.id,
        "status": conversation.status,
        "created_at": conversation.created_at.isoformat(),
        "teacher": user_dict(conversation.teacher, include_messenger_accounts=False),
        "student": user_dict(conversation.student, include_messenger_accounts=False),
        "last_message": last_message_preview,
        "last_message_at": last_message.created_at.isoformat() if last_message else None,
        "message_count": int(total),
    }
    return {
        "teacher": {**common, "unread_count": int(teacher_unread)},
        "student": {**common, "unread_count": int(student_unread)},
        "admin": {**common, "unread_count": int(admin_unread)},
    }


def publish_conversation_update(
    db: Session,
    conversation: Conversation,
    *,
    message_id: int | None = None,
    action: str = "upsert",
    actor_role: str | None = None,
    message_ids: list[int] | None = None,
    sender_role: str | None = None,
    read_at: str | None = None,
) -> None:
    """Передать событие чата с актуальными счётчиками."""
    publish_chat_update(
        conversation.id,
        message_id=message_id,
        action=action,
        actor_role=actor_role,
        message_ids=message_ids,
        sender_role=sender_role,
        read_at=read_at,
        audience={
            "teacher_id": conversation.teacher_id,
            "student_id": conversation.student_id,
        },
        # Delivery metadata does not change message counts, unread counts or preview.
        summary_by_role=None if action == "delivery" else conversation_event_summaries(db, conversation),
        db=db,
    )
