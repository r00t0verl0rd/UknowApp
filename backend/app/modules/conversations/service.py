"""Conversation-domain serialization and unread-count queries."""

import json

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update
from app.models import Conversation, Message
from app.modules.users.service import user_dict


def conversation_dicts(
    db: Session,
    conversations: list[Conversation],
    include_telegram_ids: bool = True,
    viewer_role: str = "teacher",
) -> list[dict]:
    if not conversations:
        return []

    conversation_ids = [item.id for item in conversations]
    latest_rank = (
        select(
            Message.id.label("message_id"),
            func.row_number().over(
                partition_by=Message.conversation_id,
                order_by=[Message.created_at.desc(), Message.id.desc()],
            ).label("position"),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .subquery()
    )
    latest_messages = db.scalars(
        select(Message)
        .join(latest_rank, Message.id == latest_rank.c.message_id)
        .where(latest_rank.c.position == 1),
    ).all()
    latest_by_conversation = {item.conversation_id: item for item in latest_messages}

    if viewer_role == "student":
        unread_condition = and_(
            Message.sender_role.in_(("teacher", "admin")),
            func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
        )
    elif viewer_role == "admin":
        unread_condition = and_(
            Message.sender_role.in_(("teacher", "student")),
            or_(
                func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
                func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
            ),
        )
    else:
        unread_condition = and_(
            Message.sender_role.in_(("student", "admin")),
            func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
        )
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
            "teacher": user_dict(conversation.teacher, include_telegram_id=include_telegram_ids),
            "student": user_dict(conversation.student, include_telegram_id=include_telegram_ids),
            "last_message": (
                (last_message.text or "Сообщение") if last_message.content_type == "text"
                else (
                    (json.loads(last_message.metadata_json or "{}").get("media") or {}).get("file_name")
                    or {
                        "photo": "🖼 Фотография",
                        "voice": "🎤 Голосовое сообщение",
                        "audio": "🎵 Аудио",
                        "video": "🎬 Видео",
                        "video_note": "⭕ Видеосообщение",
                        "document": "📎 Документ",
                        "sticker": "Стикер",
                        "animation": "GIF-анимация",
                    }.get(last_message.content_type, "📎 Вложение")
                ) + ((": " + last_message.text) if last_message.text else "")
            ) if last_message else "Переписка пока пуста",
            "last_message_at": last_message.created_at.isoformat() if last_message else None,
            "message_count": message_count,
            "unread_count": unread_count,
        })
    return result


def conversation_dict(
    db: Session, conversation: Conversation, include_telegram_ids: bool = True,
) -> dict:
    return conversation_dicts(db, [conversation], include_telegram_ids)[0]



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


def conversation_event_summaries(db: Session, conversation: Conversation) -> dict[str, dict]:
    """Build one authoritative counter/preview snapshot for each panel role."""
    teacher_unread = and_(
        Message.sender_role.in_(("student", "admin")),
        func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
    )
    student_unread = and_(
        Message.sender_role.in_(("teacher", "admin")),
        func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
    )
    admin_unread = and_(
        Message.sender_role.in_(("teacher", "student")),
        or_(
            func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
            func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
        ),
    )
    stats = db.execute(
        select(
            func.count(Message.id),
            func.coalesce(func.sum(case((teacher_unread, 1), else_=0)), 0),
            func.coalesce(func.sum(case((student_unread, 1), else_=0)), 0),
            func.coalesce(func.sum(case((admin_unread, 1), else_=0)), 0),
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
        "teacher": user_dict(conversation.teacher, include_telegram_id=False),
        "student": user_dict(conversation.student, include_telegram_id=False),
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
    """Publish a committed conversation change with role-specific live counters."""
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
