"""Права доступа и данные личных переписок."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update

from ...models import PersonalConversation


def personal_conversation(db: Session, principal: dict, conversation_id: int) -> PersonalConversation:
    conversation = db.get(PersonalConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    if principal["role"] != "admin" and conversation.participant_id != principal.get("user_id"):
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    return conversation


def personal_conversation_dict(
    item: PersonalConversation, viewer_role: str, unread_count: int = 0,
    last_message_at: datetime | None = None,
) -> dict:
    participant = item.participant
    return {
        "id": item.id,
        "type": "personal",
        "participant": {"id": participant.id, "full_name": participant.full_name, "role": participant.role},
        "title": participant.full_name if viewer_role == "admin" else "Администратор",
        "created_at": item.created_at.isoformat(),
        "unread_count": unread_count,
        "last_message_at": last_message_at.isoformat() if last_message_at else None,
    }


def personal_stats(db: Session, ids: list[int]) -> dict:
    # Scalar columns bypass stale ORM identity-map values after SQL triggers.
    rows = db.execute(select(PersonalConversation.id, PersonalConversation.admin_unread_count,
                             PersonalConversation.participant_unread_count, PersonalConversation.last_message_at)
                      .where(PersonalConversation.id.in_(ids))).all()
    return {row.id: row for row in rows}


def personal_event_summaries(db: Session, item: PersonalConversation) -> dict[str, dict]:
    """Read both roles' exact counters without scanning history."""
    counts = personal_stats(db, [item.id])[item.id]
    participant_role = item.participant.role
    return {
        "admin": personal_conversation_dict(item, "admin", counts.admin_unread_count, counts.last_message_at),
        participant_role: personal_conversation_dict(
            item, participant_role, counts.participant_unread_count, counts.last_message_at,
        ),
    }


def publish_personal_update(
    db: Session,
    item: PersonalConversation,
    *,
    message_id: int | None = None,
    action: str = "upsert",
    actor_role: str | None = None,
    message_ids: list[int] | None = None,
    sender_role: str | None = None,
    read_at: str | None = None,
) -> None:
    """Оповестить участников об изменении личного чата."""
    publish_chat_update(
        item.id,
        conversation_type="personal",
        message_id=message_id,
        action=action,
        actor_role=actor_role,
        message_ids=message_ids,
        sender_role=sender_role,
        read_at=read_at,
        audience={"participant_id": item.participant_id},
        summary_by_role=personal_event_summaries(db, item),
        db=db,
    )
