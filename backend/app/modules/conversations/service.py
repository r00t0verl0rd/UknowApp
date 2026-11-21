"""Conversation-domain serialization and unread-count queries."""

import json

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

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
