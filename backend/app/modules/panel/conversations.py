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
from sqlalchemy.orm import joinedload, selectinload

from app.infrastructure.storage.media import (
    MEDIA_DIR,
    attachment_response,
    delete_message_media,
)
from app.models import (
    Assignment,
    Conversation,
    Message,
)
from app.modules.auth.permissions import permits
from app.modules.communication.contracts import (
    MessengerError,
    MessengerPlatform,
)
from app.modules.conversations.service import (
    conversation_dicts,
    publish_conversation_update,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.service import (
    _panel_message_dict,
    _panel_visible_conversation,
)

from .read_state import mark_conversation_read

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/conversations")
def panel_conversations(principal: PanelUser, db: Db):
    statement = (
        select(Conversation)
        .options(
            joinedload(Conversation.teacher),
            joinedload(Conversation.student),
        )
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
        include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )


@router.get("/panel/conversations/{conversation_id}/summary")
def panel_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    return conversation_dicts(
        db, [conversation], include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]


@router.get("/panel/conversations/{conversation_id}/messages")
def panel_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0,
                   limit: int | None = Query(None, ge=1, le=100), before_id: int | None = None,
                   mark_read: bool = True):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if permits(principal, "dialogs.observe"):
        logger.info("Admin read conversation id=%s", conversation.id)
    query = select(Message).options(selectinload(Message.sender)).where(
        Message.conversation_id == conversation.id, Message.id > after_id,
    )
    if before_id is not None:
        query = query.where(Message.id < before_id)
    if limit is None:
        if mark_read:
            mark_conversation_read(db, conversation, principal, after_id)
        rows = db.scalars(query.order_by(Message.created_at, Message.id)).all()
    else:
        rows = list(reversed(db.scalars(query.order_by(Message.id.desc()).limit(limit)).all()))
        if mark_read:
            mark_conversation_read(db, conversation, principal, after_id, [row.id for row in rows])
    return [
        _panel_message_dict(
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
    _panel_visible_conversation(db, principal, item.conversation_id)
    return _panel_message_dict(
        item,
        expose_internal_metadata=(principal["role"] == "admin"),
        principal=principal,
    )


@router.get("/panel/messages/{message_id}/media")
def panel_message_media(message_id: int, request: Request, principal: PanelUser, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _panel_visible_conversation(db, principal, item.conversation_id)
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
async def delete_panel_message(
    message_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    conversation = _panel_visible_conversation(db, principal, item.conversation_id)
    owns_message = (
        item.sender_role == principal["role"]
        and (
            principal["role"] == "admin"
            or item.sender_id == principal.get("user_id")
        )
    )
    if not owns_message:
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")

    metadata = json.loads(item.metadata_json or "{}")
    deliveries_by_platform = metadata.get("messenger_deliveries") or {}
    if not deliveries_by_platform and metadata.get("telegram_deliveries"):
        # Поддерживаем сообщения без общего журнала внешних доставок.
        deliveries_by_platform = {
            MessengerPlatform.TELEGRAM.value: {
                "delivered": metadata["telegram_deliveries"],
            },
        }

    communication = getattr(request.app.state, "communication", None)
    messenger_deleted = 0
    messenger_failed = 0
    telegram_deleted = 0
    telegram_failed = 0

    # Удаляем внешние копии через адаптеры; UknowApp остаётся источником данных.
    for platform_value, result in deliveries_by_platform.items():
        try:
            platform = MessengerPlatform(platform_value)
        except ValueError:
            continue
        for delivery in result.get("delivered", []):
            external_chat_id = (
                delivery.get("external_chat_id") or delivery.get("chat_id")
            )
            external_message_id = (
                delivery.get("external_message_id")
                or delivery.get("telegram_message_id")
            )
            if not external_chat_id or not external_message_id:
                messenger_failed += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_failed += 1
                continue
            try:
                if not communication or not communication.has_adapter(platform):
                    raise RuntimeError("Messenger adapter is disabled")
                await communication.delete_message(
                    platform=platform,
                    external_chat_id=str(external_chat_id),
                    external_message_id=str(external_message_id),
                )
                messenger_deleted += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_deleted += 1
            except (MessengerError, RuntimeError, NotImplementedError) as exc:
                messenger_failed += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_failed += 1
                logger.warning(
                    "Could not delete messenger copy (platform=%s message_id=%s error_type=%s)",
                    platform.value,
                    item.id,
                    type(exc).__name__,
                )

    delete_message_media(item.metadata_json)
    db.delete(item)
    db.commit()
    publish_conversation_update(db, conversation, message_id=message_id, action="delete")

    return {
        "ok": True,
        "deleted_message_id": message_id,
        "messenger_deleted": messenger_deleted,
        "messenger_failed": messenger_failed,
        "telegram_deleted": telegram_deleted,
        "telegram_failed": telegram_failed,
    }
