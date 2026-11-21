"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import asyncio
import json
import logging
import mimetypes
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from aiogram.exceptions import TelegramAPIError
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.event_hub import (
    publish_chat_update,
    subscribe_chat_updates,
    unsubscribe_chat_updates,
)
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
    PersonalConversation,
    PersonalMessage,
    StudentTelegramGroup,
    TeacherSession,
    User,
)
from app.modules.communication.accounts import get_messenger_account
from app.modules.communication.contracts import (
    MessageKind,
    MessengerError,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)
from app.modules.conversations.service import conversation_dicts
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.messaging.service import (
    _panel_message_dict,
    _panel_visible_conversation,
)
from app.modules.notifications.service import schedule_push
from app.modules.personal_chat.service import (
    _personal_conversation,
    _personal_conversation_dict,
)
from app.request_validation import message_payload, personal_conversation_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

def _panel_student_telegram_target(
    db: Session,
    conversation: Conversation,
    rows: list[Message],
) -> dict | None:
    student = conversation.student
    account = get_messenger_account(db, student.id, MessengerPlatform.TELEGRAM)
    if not account:
        return None
    target = {"chat_id": account.external_chat_id or account.external_user_id}
    last_reply_index = max(
        (
            i for i, item in enumerate(rows)
            if item.sender_role in {"teacher", "admin"}
            and item.delivery_status in {"delivered", "partial"}
            and (
                item.sender_role == "teacher"
                or any(
                    delivery.get("user_id") == student.id
                    for delivery in (json.loads(item.metadata_json or "{}").get("telegram_deliveries") or [])
                )
                or not json.loads(item.metadata_json or "{}").get("telegram_deliveries")
            )
        ),
        default=-1,
    )
    for incoming in reversed(rows[last_reply_index + 1:]):
        if incoming.sender_role != "student":
            continue
        incoming_meta = json.loads(incoming.metadata_json or "{}")
        if incoming_meta.get("source_mode") == "group_topic":
            try:
                group_chat_id = int(incoming_meta["source_chat_id"])
                thread_id = int(incoming_meta["source_thread_id"])
            except (KeyError, TypeError, ValueError):
                return target
            linked_topic = db.scalar(select(StudentTelegramGroup).where(
                StudentTelegramGroup.student_id == student.id,
                StudentTelegramGroup.chat_id == group_chat_id,
                StudentTelegramGroup.thread_id == thread_id,
            ))
            if linked_topic:
                return {"chat_id": group_chat_id, "message_thread_id": thread_id}
        return target

    # Preserve the group topic used by the last answer after an administrator
    # has intervened and there is no newer student message.
    if last_reply_index >= 0:
        response_meta = json.loads(rows[last_reply_index].metadata_json or "{}")
        for delivery in response_meta.get("telegram_deliveries") or []:
            if delivery.get("user_id") != student.id or delivery.get("thread_id") is None:
                continue
            try:
                group_chat_id = int(delivery["chat_id"])
                thread_id = int(delivery["thread_id"])
            except (KeyError, TypeError, ValueError):
                return target
            linked_topic = db.scalar(select(StudentTelegramGroup).where(
                StudentTelegramGroup.student_id == student.id,
                StudentTelegramGroup.chat_id == group_chat_id,
                StudentTelegramGroup.thread_id == thread_id,
            ))
            if linked_topic:
                return {"chat_id": group_chat_id, "message_thread_id": thread_id}

    # If the conversation has no usable recent delivery route yet, fall back
    # to the student's current verified forum-topic binding instead of always
    # sending the first teacher-initiated message to the private bot chat.
    current_binding = db.get(StudentTelegramGroup, student.id)
    if current_binding:
        return {
            "chat_id": current_binding.chat_id,
            "message_thread_id": current_binding.thread_id,
        }
    return target


@router.get("/panel/me")
def panel_me(principal: PanelUser, db: Db):
    if principal["role"] == "admin":
        return {"role": "admin", "full_name": "Администратор"}
    user = db.get(User, principal["user_id"])
    if (
        not user
        or user.role != principal["role"]
        or user.role not in {"teacher", "student"}
    ):
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"role": user.role, "id": user.id, "full_name": user.full_name}


@router.get("/panel/events")
async def panel_events(request: Request, principal: PanelUser):
    """Keep an authenticated browser connection open for conversation changes."""

    async def event_stream():
        queue = subscribe_chat_updates()
        try:
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    # SSE comment frames keep intermediaries from closing an idle
                    # connection; they do not trigger a browser data callback.
                    yield ": keep-alive\n\n"
                    continue
                yield "event: update\ndata: " + payload + "\n\n"
        finally:
            unsubscribe_chat_updates(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.get("/panel/personal-conversations")
def personal_conversations(principal: PanelUser, db: Db):
    statement = select(PersonalConversation).options(
        selectinload(PersonalConversation.participant),
    ).order_by(PersonalConversation.created_at.desc(), PersonalConversation.id.desc())
    if principal["role"] != "admin":
        statement = statement.where(PersonalConversation.participant_id == principal["user_id"])
    items = db.scalars(statement).all()
    if not items:
        return []
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    counts = db.execute(
        select(PersonalMessage.conversation_id, func.count(PersonalMessage.id))
        .where(
            PersonalMessage.conversation_id.in_([item.id for item in items]),
            PersonalMessage.sender_role != principal["role"],
            read_column.is_(None),
        )
        .group_by(PersonalMessage.conversation_id),
    ).all()
    unread_by_conversation = dict(counts)
    return [
        _personal_conversation_dict(item, principal["role"], unread_by_conversation.get(item.id, 0))
        for item in items
    ]


@router.post("/panel/personal-conversations", status_code=201)
def create_personal_conversation(payload: dict, principal: PanelUser, db: Db):
    payload = personal_conversation_payload(payload)
    if principal["role"] != "admin":
        raise HTTPException(status_code=403, detail="Создавать личные диалоги может только администратор")
    participant = db.get(User, payload["user_id"])
    if not participant or participant.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Участник не найден")
    item = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == participant.id))
    if not item:
        item = PersonalConversation(participant_id=participant.id)
        db.add(item)
        db.commit()
        db.refresh(item)
    publish_chat_update(item.id, "personal")
    return _personal_conversation_dict(item, principal["role"])


@router.get("/panel/personal-conversations/{conversation_id}/summary")
def personal_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    item = _personal_conversation(db, principal, conversation_id)
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    unread_count = db.scalar(
        select(func.count(PersonalMessage.id)).where(
            PersonalMessage.conversation_id == item.id,
            PersonalMessage.sender_role != principal["role"],
            read_column.is_(None),
        ),
    ) or 0
    return _personal_conversation_dict(item, principal["role"], unread_count)


@router.get("/panel/conversations/{conversation_id}/summary")
def panel_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    return conversation_dicts(
        db, [conversation], include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]


@router.get("/panel/personal-conversations/{conversation_id}/messages")
def personal_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0):
    item = _personal_conversation(db, principal, conversation_id)
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    read_result = db.execute(
        update(PersonalMessage)
        .where(
            PersonalMessage.conversation_id == item.id,
            PersonalMessage.sender_role != principal["role"],
            read_column.is_(None),
            PersonalMessage.id > after_id,
        )
        .values({read_column.key: datetime.now(UTC)}),
    )
    if read_result.rowcount:
        db.commit()
        publish_chat_update(item.id, "personal", action="read", actor_role=principal["role"])
    rows = db.scalars(
        select(PersonalMessage)
        .options(selectinload(PersonalMessage.sender))
        .where(PersonalMessage.conversation_id == item.id, PersonalMessage.id > after_id)
        .order_by(PersonalMessage.created_at, PersonalMessage.id),
    ).all()
    return [{
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": row.sender_role == principal["role"] and (
            principal["role"] == "admin" or row.sender_id == principal.get("user_id")
        ),
        "content_type": "text",
        "text": row.text,
        "metadata": {},
        "delivery_status": "delivered",
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.post("/panel/personal-conversations/{conversation_id}/messages", status_code=201)
def send_personal_message(
    conversation_id: int,
    payload: dict,
    principal: PanelUser,
    db: Db,
):
    payload = message_payload(payload)
    item = _personal_conversation(db, principal, conversation_id)
    if principal["role"] not in {"admin", "teacher", "student"}:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    if principal["role"] == "admin":
        sender_id = None
    else:
        sender = db.get(User, principal["user_id"])
        if not sender or sender.id != item.participant_id:
            raise HTTPException(status_code=403, detail="Нет доступа к личному диалогу")
        sender_id = sender.id
    row = PersonalMessage(
        conversation_id=item.id,
        sender_id=sender_id,
        sender_role=principal["role"],
        text=payload["text"].strip(),
    )
    if not row.text:
        raise HTTPException(status_code=400, detail="Введите сообщение")
    db.add(row)
    db.commit()
    db.refresh(row)
    schedule_push(
        db,
        [item.participant_id] if principal["role"] == "admin" else [],
        "Новое личное сообщение",
        (("Администратор: " if principal["role"] == "admin" else item.participant.full_name + ": ") + row.text)[:240],
        f"/?openConversation={item.id}&type=personal",
        include_admin=principal["role"] != "admin",
    )
    publish_chat_update(item.id, "personal", row.id)
    return {
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": True,
        "content_type": "text",
        "text": row.text,
        "metadata": {},
        "delivery_status": "delivered",
        "created_at": row.created_at.isoformat(),
    }


@router.delete("/panel/personal-messages/{message_id}")
def delete_personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    if row.sender_role != principal["role"] or (
        principal["role"] != "admin" and row.sender_id != principal.get("user_id")
    ):
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")
    conversation_id = row.conversation_id
    db.delete(row)
    db.commit()
    publish_chat_update(conversation_id, "personal", message_id, "delete")
    return {"ok": True, "deleted_message_id": message_id}


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
            publish_chat_update(
                conversation.id,
                action="read",
                actor_role=principal["role"],
                message_ids=[row.id for row in unread],
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
    deliveries = metadata.get("telegram_deliveries") or []
    communication = getattr(request.app.state, "communication", None)
    telegram_deleted = 0
    telegram_failed = 0

    # Remove every external copy recorded at delivery time. The provider adapter
    # owns the platform-specific API call; the panel only tracks the result.
    if deliveries and communication and communication.has_adapter(MessengerPlatform.TELEGRAM):
        for delivery in deliveries:
            try:
                await communication.delete_message(
                    platform=MessengerPlatform.TELEGRAM,
                    external_chat_id=str(delivery["chat_id"]),
                    external_message_id=str(delivery["telegram_message_id"]),
                )
                telegram_deleted += 1
            except MessengerError as exc:
                telegram_failed += 1
                logger.warning(
                    "Could not delete Telegram copy (message_id=%s error_type=%s)",
                    item.id,
                    type(exc).__name__,
                )
    else:
        telegram_failed = len(deliveries)

    delete_message_media(item.metadata_json)
    db.delete(item)
    db.commit()
    publish_chat_update(conversation.id, message_id=message_id, action="delete")

    return {
        "ok": True,
        "deleted_message_id": message_id,
        "telegram_deleted": telegram_deleted,
        "telegram_failed": telegram_failed,
    }


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


def _panel_sender_and_recipients(db: Session, principal: dict, conversation: Conversation):
    """Resolve the sender and Telegram recipients for a panel message."""
    student = conversation.student
    teacher = conversation.teacher
    if principal["role"] == "teacher":
        sender = teacher
        recipients = [(student, "student")]
    elif principal["role"] == "student":
        sender = student
        recipients = [(teacher, "teacher")]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin")
            db.add(sender)
            db.flush()
        recipients = [(student, "student"), (teacher, "teacher")]
    if not sender:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return sender, recipients, student, teacher


def _save_panel_delivery_result(db: Session, row: Message, conversation: Conversation, delivered: list[dict], delivery_errors: list[dict]) -> None:
    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = delivered
    if delivery_errors:
        metadata["telegram_delivery_errors"] = delivery_errors
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = (
        "delivered" if delivered and not delivery_errors
        else ("partial" if delivered else "failed")
    )
    db.commit()
    publish_chat_update(conversation.id, message_id=row.id)


async def _store_panel_attachment(request: Request, file: UploadFile, conversation_id: int):
    """Validate and persist an uploaded attachment; return normalized metadata."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 22 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Максимальный размер файла — 20 МБ")
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный Content-Length")

    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Максимальный размер файла — 20 МБ")
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")

    original_name = (file.filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
    original_name = "".join(
        char for char in original_name
        if ord(char) >= 32 and char not in "\r\n"
    )[:180].strip() or "attachment"
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(original_name).suffix)[:12]
    if not suffix:
        suffix = mimetypes.guess_extension(file.content_type or "") or ".bin"

    relative = Path(str(conversation_id)) / (uuid.uuid4().hex + suffix)
    target_path = (MEDIA_DIR / relative).resolve()
    root = MEDIA_DIR.resolve()
    if root not in target_path.parents:
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)

    reported_mime_type = file.content_type or mimetypes.guess_type(original_name)[0]
    mime_type = safe_media_type(reported_mime_type)
    if mime_type == "image/gif":
        kind = "animation"
    elif mime_type.startswith("image/"):
        kind = "photo"
    elif mime_type.startswith("video/"):
        kind = "video"
    elif mime_type.startswith("audio/"):
        kind = "voice" if mime_type in {"audio/ogg", "audio/opus"} else "audio"
    else:
        kind = "document"
    return content, original_name, relative, mime_type, kind


async def _refresh_teacher_panel_after_web_delivery(bot, db: Session, teacher: User, conversation: Conversation) -> None:
    """Refresh the teacher's Telegram panel after a web message has been persisted."""
    teacher_account = get_messenger_account(db, teacher.id, MessengerPlatform.TELEGRAM)
    if not bot or not teacher_account:
        return
    try:
        from app.modules.telegram.teacher import (
            clear_teacher_session,
            update_teacher_panel,
        )
        current_session = db.get(TeacherSession, teacher.id)
        if current_session and current_session.conversation_id != conversation.id:
            clear_teacher_session(db, teacher)
        await update_teacher_panel(bot, db, teacher)
    except (TelegramAPIError, SQLAlchemyError) as exc:
        # Delivery is already committed; a panel refresh failure must not undo it.
        logger.warning(
            "Could not refresh teacher panel after web delivery "
            "(teacher_id=%s conversation_id=%s error_type=%s)",
            teacher.id, conversation.id, type(exc).__name__,
        )


@router.post("/panel/conversations/{conversation_id}/messages", status_code=201)
async def send_panel_message(
    conversation_id: int,
    payload: dict,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    payload = message_payload(payload)
    # Сначала сохраняем сообщение в БД, затем отправляем его адресатам в Telegram.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    body = payload["text"].strip()
    if text_contains_contact_data(body):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)

    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id),
    ).all()
    student_target = (
        _panel_student_telegram_target(db, conversation, rows)
        if any(role == "student" for _, role in recipients) else None
    )

    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type="text",
        text=body,
        metadata_json=json.dumps({"source_mode": "web", "web_sender_role": principal["role"]}, ensure_ascii=False),
        delivery_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    push_recipients = [student.id, teacher.id] if principal["role"] == "admin" else ([student.id] if principal["role"] == "teacher" else [teacher.id])
    schedule_push(
        db, push_recipients, "Новое сообщение · UknowApp",
        (sender.full_name + ": " + (body or "Новое сообщение"))[:240],
        f"/?openConversation={conversation.id}", include_admin=principal["role"] != "admin",
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    communication = getattr(request.app.state, "communication", None)
    delivery_errors = []
    delivered = []
    if communication and communication.has_adapter(MessengerPlatform.TELEGRAM):
        for recipient, recipient_role in recipients:
            recipient_account = get_messenger_account(
                db, recipient.id, MessengerPlatform.TELEGRAM,
            )
            if not recipient_account:
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            try:
                target = student_target if recipient_role == "student" else {
                    "chat_id": recipient_account.external_chat_id or recipient_account.external_user_id,
                }
                if not target:
                    delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Не удалось определить Telegram-чат ученика"})
                    continue
                # The student already knows this is the teacher's private chat.
                # Deliver teacher text naturally; only label a separate admin role.
                outgoing_text = (
                    body if principal["role"] == "teacher"
                    else "Сообщение от ученика " + student.full_name + ":\n" + body
                    if principal["role"] == "student"
                    else "Сообщение от администратора школы:\n" + body
                )
                sent = await communication.send(OutboundMessage(
                    platform=MessengerPlatform.TELEGRAM,
                    external_chat_id=str(target["chat_id"]),
                    external_thread_id=(
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                    content_type=MessageKind.TEXT,
                    text=outgoing_text,
                    idempotency_key=f"panel-message:{row.id}:recipient:{recipient.id}",
                ))
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": int(sent.external_message_id),
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except (MessengerError, OSError, ValueError, TypeError, RuntimeError) as exc:
                logger.warning(
                    "Telegram delivery failed for conversation_id=%s: %s",
                    conversation.id,
                    getattr(exc, "provider_error_type", type(exc).__name__),
                )
                delivery_errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "ошибка Telegram (" + getattr(exc, "provider_error_type", type(exc).__name__) + ")",
                })
    else:
        delivery_errors.extend(
            {"name": recipient.full_name, "role": recipient_role, "reason": "Telegram-бот не подключён к веб-приложению"}
            for recipient, recipient_role in recipients
        )

    _save_panel_delivery_result(db, row, conversation, delivered, delivery_errors)

    await _refresh_teacher_panel_after_web_delivery(bot, db, teacher, conversation)

    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


@router.post("/panel/conversations/{conversation_id}/attachments", status_code=201)
async def send_panel_attachment(
    conversation_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form()] = "",
):
    # Ограничиваем размер до чтения файла целиком и сохраняем локальную копию для веб-панели.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)

    if text_contains_contact_data((text or "").strip()):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    content, original_name, relative, mime_type, kind = await _store_panel_attachment(
        request, file, conversation.id,
    )

    media = {
        "kind": kind,
        "file_name": original_name,
        "mime_type": mime_type,
        "file_size": len(content),
        "local_path": relative.as_posix(),
        "archive_status": "stored",
    }
    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type=kind,
        text=(text or "").strip(),
        metadata_json=json.dumps({
            "source_mode": "web",
            "web_sender_role": principal["role"],
            "media": media,
        }, ensure_ascii=False),
        delivery_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    push_recipients = [student.id, teacher.id] if principal["role"] == "admin" else ([student.id] if principal["role"] == "teacher" else [teacher.id])
    schedule_push(
        db, push_recipients, "Новое сообщение · UknowApp",
        (sender.full_name + ": " + (row.text or "Отправлено вложение"))[:240],
        f"/?openConversation={conversation.id}", include_admin=principal["role"] != "admin",
    )

    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id),
    ).all()
    student_target = (
        _panel_student_telegram_target(db, conversation, rows[:-1])
        if any(role == "student" for _, role in recipients) else None
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    communication = getattr(request.app.state, "communication", None)
    delivery_errors = []
    delivered = []
    if communication and communication.has_adapter(MessengerPlatform.TELEGRAM):
        for recipient, recipient_role in recipients:
            recipient_account = get_messenger_account(
                db, recipient.id, MessengerPlatform.TELEGRAM,
            )
            if not recipient_account:
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            target = student_target if recipient_role == "student" else {
                "chat_id": recipient_account.external_chat_id or recipient_account.external_user_id,
            }
            if not target:
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Не удалось определить Telegram-чат ученика"})
                continue
            # Teacher and student already share this conversation; avoid repeating
            # a sender label on every teacher attachment.
            caption = (
                (row.text or "").strip()[:1024]
                if principal["role"] == "teacher"
                else (
                    "Сообщение от ученика " + student.full_name
                    + ((": " + row.text) if row.text else "")
                    if principal["role"] == "student"
                    else ("От администратора школы" + ((": " + row.text) if row.text else ""))
                )
            )
            try:
                sent = await communication.send(OutboundMessage(
                    platform=MessengerPlatform.TELEGRAM,
                    external_chat_id=str(target["chat_id"]),
                    external_thread_id=(
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                    content_type=MessageKind(kind),
                    text=caption,
                    media=OutboundMedia(
                        storage_key=relative.as_posix(),
                        file_name=original_name,
                        mime_type=mime_type,
                    ),
                    idempotency_key=f"panel-message:{row.id}:recipient:{recipient.id}",
                ))
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": int(sent.external_message_id),
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except (MessengerError, OSError, ValueError, TypeError, RuntimeError) as exc:
                logger.warning(
                    "Telegram delivery failed for conversation_id=%s: %s",
                    conversation.id,
                    getattr(exc, "provider_error_type", type(exc).__name__),
                )
                delivery_errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "ошибка Telegram (" + type(exc).__name__ + ")",
                })
    else:
        delivery_errors.extend(
            {"name": recipient.full_name, "role": recipient_role, "reason": "Telegram-бот не подключён к веб-приложению"}
            for recipient, recipient_role in recipients
        )

    _save_panel_delivery_result(db, row, conversation, delivered, delivery_errors)

    await _refresh_teacher_panel_after_web_delivery(bot, db, teacher, conversation)
    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)
