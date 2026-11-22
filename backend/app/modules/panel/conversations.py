"""Диалоги ученика и учителя: список, сообщения, вложения, удаление."""

import json
import logging
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.infrastructure.storage.media import (
    MEDIA_DIR,
    delete_message_media,
    media_content_disposition,
    safe_media_type,
)
from app.models import (
    Assignment,
    Conversation,
    Message,
    User,
)
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

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/conversations")
def panel_conversations(principal: PanelUser, db: Db):
    statement = (
        select(Conversation)
        .options(
            selectinload(Conversation.teacher),
            selectinload(Conversation.student),
        )
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .join(User, Assignment.student_id == User.id)
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
def panel_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if principal["role"] in {"teacher", "student"}:
        read_key = "teacher_read_at" if principal["role"] == "teacher" else "student_read_at"
        sender_roles = ("student", "admin") if principal["role"] == "teacher" else ("teacher", "admin")
        unread = db.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_role.in_(sender_roles),
                func.json_extract(Message.metadata_json, "$." + read_key).is_(None),
                Message.id > after_id,
            ),
        ).all()
        if unread:
            now = datetime.now(UTC).isoformat()
            for row in unread:
                metadata = json.loads(row.metadata_json or "{}")
                metadata[read_key] = now
                row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()
            publish_conversation_update(
                db, conversation, action="read", actor_role=principal["role"],
                message_ids=[row.id for row in unread], read_at=now,
            )
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.id > after_id)
        .order_by(Message.created_at, Message.id),
    ).all()
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
def panel_message_media(message_id: int, principal: PanelUser, db: Db):
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
    return FileResponse(
        path,
        media_type=safe_media_type(media.get("mime_type")),
        filename=media.get("file_name") or path.name,
        content_disposition_type=media_content_disposition(media.get("kind"), media.get("mime_type")),
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


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
