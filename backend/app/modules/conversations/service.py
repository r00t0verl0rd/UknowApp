"""Данные переписок и счётчики непрочитанных."""

import json

from sqlalchemy import and_, case, func, or_, select
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
    latest_id = (
        select(Message.id)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    latest_messages = db.scalars(
        select(Message)
        .select_from(Conversation)
        .join(Message, Message.id == latest_id)
        .where(Conversation.id.in_(conversation_ids)),
    ).all()
    latest_by_conversation = {item.conversation_id: item for item in latest_messages}

    unread_condition = _unread_condition(db, viewer_role)
    statistics = db.execute(
        select(
            Message.conversation_id,
            func.count(Message.id),
            func.coalesce(func.sum(case((unread_condition, 1), else_=0)), 0),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id),
    ).all()
    stats_by_conversation = {
        conversation_id: (message_count, unread_count)
        for conversation_id, message_count, unread_count in statistics
    }

    result = []
    for conversation in conversations:
        last_message = latest_by_conversation.get(conversation.id)
        message_count, unread_count = stats_by_conversation.get(conversation.id, (0, 0))
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


def conversation_event_summaries(db: Session, conversation: Conversation) -> dict[str, dict]:
    """Сформировать счётчики и превью для роли."""
    stats = db.execute(
        select(
            func.count(Message.id),
            func.coalesce(func.sum(case((_unread_condition(db, "teacher"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((_unread_condition(db, "student"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((_unread_condition(db, "admin"), 1), else_=0)), 0),
        ).where(Message.conversation_id == conversation.id),
    ).one()
    last_message = db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1),
    )
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
        "message_count": int(stats[0] or 0),
    }
    return {
        "teacher": {**common, "unread_count": int(stats[1] or 0)},
        "student": {**common, "unread_count": int(stats[2] or 0)},
        "admin": {**common, "unread_count": int(stats[3] or 0)},
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
        summary_by_role=conversation_event_summaries(db, conversation),
        db=db,
    )
