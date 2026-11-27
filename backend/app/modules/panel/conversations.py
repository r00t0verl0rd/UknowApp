"""Диалоги ученика и учителя: список, сообщения, вложения, удаление."""

import json
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.database import begin_serialized_write
from app.infrastructure.storage.media import (
    MEDIA_DIR,
    attachment_response,
    delete_message_media,
)
from app.models import (
    Assignment,
    Conversation,
    Message,
    User,
)
from app.modules.auth.permissions import permits
from app.modules.communication.outbox import enqueue_message_deletions
from app.modules.conversations.service import (
    conversation_dicts,
    publish_conversation_update,
    read_cursor,
    unread_condition,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.history import history_page
from app.modules.messaging.read_state import mark_conversation_read
from app.modules.messaging.service import (
    panel_message_dict,
    panel_visible_conversation,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/conversations")
def panel_conversations(principal: PanelUser, db: Db):
    teacher = joinedload(Conversation.teacher)
    student = joinedload(Conversation.student)
    if principal["role"] == "admin":
        teacher = teacher.selectinload(User.messenger_accounts)
        student = student.selectinload(User.messenger_accounts)
    statement = (
        select(Conversation)
        .options(teacher, student)
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .where(
            Assignment.active.is_(True),
            Conversation.status == "active",
        )
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
    )
    if principal["role"] == "teacher":
        statement = statement.where(Assignment.teacher_id == principal["user_id"])
    elif principal["role"] == "student":
        statement = statement.where(Assignment.student_id == principal["user_id"]).limit(1)
    elif not permits(principal, "dialogs.observe"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    conversations = db.scalars(statement).all()
    return conversation_dicts(
        db,
        conversations,
        include_messenger_accounts=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )


@router.get("/panel/conversations/{conversation_id}/summary")
def panel_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    conversation = panel_visible_conversation(db, principal, conversation_id)
    return conversation_dicts(
        db, [conversation], include_messenger_accounts=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]


@router.get("/panel/conversations/{conversation_id}/messages")
def panel_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0,
                   limit: int | None = Query(None, ge=1, le=100), before_id: int | None = None,
                   mark_read: bool = True, forward: bool = False,
                   around_id: int | None = Query(None, ge=1), first_unread: bool = False):
    conversation = panel_visible_conversation(db, principal, conversation_id)
    if permits(principal, "dialogs.observe"):
        logger.info("Admin read conversation id=%s", conversation.id)
    query = select(Message).options(joinedload(Message.sender)).where(
        Message.conversation_id == conversation.id, Message.id > after_id,
    )
    if first_unread and around_id is None:
        around_id = db.scalar(select(Message.id).where(
            Message.conversation_id == conversation.id,
            *([Message.id > read_cursor(conversation.id, principal["role"])] if principal["role"] != "admin" else []),
            unread_condition(db, principal["role"]),
        ).order_by(Message.id).limit(1))
    if around_id is not None:
        # Ответ сразу содержит соседние страницы и якорное сообщение.
        size = limit or 50
        before = list(db.scalars(query.where(Message.id < around_id)
                                 .order_by(Message.id.desc()).limit(size)).all())
        following = list(db.scalars(query.where(Message.id >= around_id)
                                    .order_by(Message.id).limit(size)).all())
        rows = list(reversed(before)) + following
        return {"messages": [panel_message_dict(row, expose_internal_metadata=principal["role"] == "admin", principal=principal) for row in rows],
                "anchor_id": around_id, "has_older": len(before) == size,
                "has_newer": len(following) == size}
    if first_unread:
        size = limit or 50
        rows = list(reversed(db.scalars(query.order_by(Message.id.desc()).limit(size)).all()))
        return {"messages": [panel_message_dict(row, expose_internal_metadata=principal["role"] == "admin", principal=principal) for row in rows],
                "anchor_id": None, "has_older": len(rows) == size, "has_newer": False}
    if before_id is not None:
        query = query.where(Message.id < before_id)
    rows = history_page(db, query, Message, limit, after_id, forward)
    if mark_read and principal["role"] != "admin":
        mark_conversation_read(db, conversation, principal, after_id, [row.id for row in rows])
    return [
        panel_message_dict(
            item,
            expose_internal_metadata=(principal["role"] == "admin"),
            principal=principal,
        )
        for item in rows
    ]


@router.get("/panel/messages/{message_id}")
def panel_message(message_id: int, principal: PanelUser, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    panel_visible_conversation(db, principal, item.conversation_id)
    return panel_message_dict(
        item,
        expose_internal_metadata=(principal["role"] == "admin"),
        principal=principal,
    )


@router.get("/panel/messages/{message_id}/media")
def panel_message_media(message_id: int, request: Request, principal: PanelUser, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    panel_visible_conversation(db, principal, item.conversation_id)
    metadata = json.loads(item.metadata_json or "{}")
    media = metadata.get("media") or {}
    relative = media.get("local_path")
    if not relative or media.get("archive_status") != "stored":
        raise HTTPException(status_code=404, detail="Локальная копия вложения недоступна")
    root = MEDIA_DIR.resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл вложения не найден")
    return attachment_response(request, path, media)


@router.delete("/panel/messages/{message_id}")
def delete_panel_message(
    message_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    begin_serialized_write(db)
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    conversation = panel_visible_conversation(db, principal, item.conversation_id)
    owns_message = (
        item.sender_role == principal["role"]
        and (
            principal["role"] == "admin"
            or item.sender_id == principal.get("user_id")
        )
    )
    if not owns_message:
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")

    queued, unknown = enqueue_message_deletions(db, item)
    metadata_json = item.metadata_json
    db.delete(item)
    db.commit()
    delete_message_media(metadata_json)
    publish_conversation_update(db, conversation, message_id=message_id, action="delete")
    gateway = getattr(request.app.state, "bots_gateway", None)
    if gateway:
        gateway.wake_outbox()
    return {
        "ok": True,
        "deleted_message_id": message_id,
        "messenger_delete_queued": queued,
        "messenger_deleted": 0,
        "messenger_failed": unknown,
    }
