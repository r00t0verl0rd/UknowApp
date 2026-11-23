"""Отметки прочтения: помечают входящие сообщения прочитанными и публикуют событие."""

import json
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.models import Message, PersonalMessage
from app.modules.conversations.service import publish_conversation_update
from app.modules.personal_chat.service import publish_personal_update


def mark_conversation_read(db, conversation, principal, after_id: int, visible_ids=None) -> None:
    """Учитель и ученик помечают прочитанными новые сообщения собеседников; администратор ничего не помечает."""
    role = principal["role"]
    if role not in {"teacher", "student"}:
        return
    read_key = "teacher_read_at" if role == "teacher" else "student_read_at"
    sender_roles = ("student", "admin") if role == "teacher" else ("teacher", "admin")
    unread = db.scalars(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_role.in_(sender_roles),
            func.json_extract(Message.metadata_json, "$." + read_key).is_(None),
            Message.id > after_id,
            *([Message.id.in_(visible_ids)] if visible_ids is not None else []),
        ),
    ).all()
    if not unread:
        return
    read_at = datetime.now(UTC).isoformat()
    for row in unread:
        metadata = json.loads(row.metadata_json or "{}")
        metadata[read_key] = read_at
        row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()
    publish_conversation_update(
        db, conversation, action="read", actor_role=role,
        message_ids=[row.id for row in unread], read_at=read_at,
    )


def mark_personal_read(db, item, principal, after_id: int, visible_ids=None) -> None:
    """Помечает прочитанными новые сообщения собеседника в личном диалоге."""
    role = principal["role"]
    read_column = PersonalMessage.admin_read_at if role == "admin" else PersonalMessage.participant_read_at
    read_ids = db.scalars(
        select(PersonalMessage.id).where(
            PersonalMessage.conversation_id == item.id,
            PersonalMessage.sender_role != role,
            read_column.is_(None),
            PersonalMessage.id > after_id,
            *([PersonalMessage.id.in_(visible_ids)] if visible_ids is not None else []),
        ),
    ).all()
    if not read_ids:
        return
    read_at = datetime.now(UTC)
    db.execute(
        update(PersonalMessage)
        .where(PersonalMessage.id.in_(read_ids))
        .values({read_column.key: read_at}),
    )
    db.commit()
    publish_personal_update(
        db, item, action="read", actor_role=role,
        message_ids=read_ids, read_at=read_at.isoformat(),
    )
