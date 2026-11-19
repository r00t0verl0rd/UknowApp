"""Access checks and serialization for private conversations."""

from fastapi import HTTPException

from ...models import PersonalConversation


def _personal_conversation(db: Session, principal: dict, conversation_id: int) -> PersonalConversation:
    conversation = db.get(PersonalConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    if principal["role"] != "admin" and conversation.participant_id != principal.get("user_id"):
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    return conversation


def _personal_conversation_dict(item: PersonalConversation, viewer_role: str, unread_count: int = 0) -> dict:
    participant = item.participant
    return {
        "id": item.id,
        "type": "personal",
        "participant": {"id": participant.id, "full_name": participant.full_name, "role": participant.role},
        "title": participant.full_name if viewer_role == "admin" else "Администратор",
        "created_at": item.created_at.isoformat(),
        "unread_count": unread_count,
    }
