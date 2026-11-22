"""Доставка сообщений панели во внешние мессенджеры и сохранение вложений."""

import json
import logging
import mimetypes
import re
import uuid
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from fastapi import (
    HTTPException,
    UploadFile,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import SessionLocal
from app.infrastructure.storage.media import (
    ATTACHMENT_SIZE_ERROR,
    MAX_ATTACHMENT_BYTES,
    MEDIA_DIR,
    safe_media_type,
)
from app.models import (
    Conversation,
    Message,
    StudentTelegramGroup,
    TeacherSession,
    User,
)
from app.modules.communication.accounts import get_messenger_account, get_messenger_pair
from app.modules.communication.contracts import (
    MessageKind,
    MessengerError,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)
from app.modules.communication.service import record_messenger_delivery
from app.modules.conversations.service import (
    publish_conversation_update,
)

logger = logging.getLogger(__name__)


def panel_student_telegram_target(
    db: Session,
    conversation: Conversation,
    account=None,
) -> dict | None:
    student = conversation.student
    account = account or get_messenger_account(db, student.id, MessengerPlatform.TELEGRAM)
    if not account:
        return None
    target = {"chat_id": account.external_chat_id or account.external_user_id}

    teacher_reply = db.execute(
        select(Message.id, Message.created_at, Message.metadata_json)
        .where(
            Message.conversation_id == conversation.id,
            Message.sender_role == "teacher",
            Message.delivery_status != "blocked_contact",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1),
    ).first()

    admin_replies = db.execute(
        select(Message.id, Message.created_at, Message.metadata_json)
        .where(
            Message.conversation_id == conversation.id,
            Message.sender_role == "admin",
            Message.delivery_status != "blocked_contact",
        )
        .order_by(Message.created_at.desc(), Message.id.desc()),
    ).all()
    admin_reply = None
    for candidate in admin_replies:
        metadata = json.loads(candidate.metadata_json or "{}")
        deliveries = (
            (metadata.get("messenger_deliveries") or {}).get("telegram", {}).get("delivered")
            or metadata.get("telegram_deliveries")
            or []
        )
        if not deliveries or any(delivery.get("user_id") == student.id for delivery in deliveries):
            admin_reply = candidate
            break

    last_reply = max(
        (item for item in (teacher_reply, admin_reply) if item is not None),
        key=lambda item: (item.created_at, item.id),
        default=None,
    )
    incoming_query = select(Message.metadata_json).where(
        Message.conversation_id == conversation.id,
        Message.sender_role == "student",
    )
    if last_reply is not None:
        incoming_query = incoming_query.where(
            or_(
                Message.created_at > last_reply.created_at,
                and_(
                    Message.created_at == last_reply.created_at,
                    Message.id > last_reply.id,
                ),
            ),
        )
    incoming_metadata = db.scalar(
        incoming_query
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1),
    )
    if incoming_metadata is not None:
        incoming_meta = json.loads(incoming_metadata or "{}")
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

    if last_reply is not None:
        response_meta = json.loads(last_reply.metadata_json or "{}")
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

    current_binding = db.get(StudentTelegramGroup, student.id)
    if current_binding:
        return {
            "chat_id": current_binding.chat_id,
            "message_thread_id": current_binding.thread_id,
        }
    return target


def panel_sender_and_recipients(db: Session, principal: dict, conversation: Conversation):
    """Определить отправителя и адресатов в Telegram."""
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


def save_panel_messenger_results(
    db: Session,
    row: Message,
    conversation: Conversation,
    results: dict[str, dict[str, list[dict]]],
) -> None:
    if not results:
        return
    metadata = json.loads(row.metadata_json or "{}")
    for platform, result in results.items():
        record_messenger_delivery(
            metadata,
            platform,
            delivered=result.get("delivered", []),
            errors=result.get("errors", []),
        )
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    # Статус сообщения отражает хранение в UknowApp, не внешнюю доставку.
    row.delivery_status = "delivered"
    db.commit()
    publish_conversation_update(
        db, conversation, message_id=row.id, action="delivery",
        sender_role=row.sender_role,
    )


async def deliver_panel_message(
    db: Session,
    communication,
    row: Message,
    conversation: Conversation,
    recipients: list[tuple[User, str]],
    sender_role: str,
    student: User,
    body: str,
    content_type: MessageKind,
    media: OutboundMedia | None = None,
) -> dict[str, dict[str, list[dict]]]:
    """Отправлять через канал только при привязке обоих участников."""
    results: dict[str, dict[str, list[dict]]] = {}
    if communication is None:
        return results

    for platform in communication.platforms:
        teacher_account, student_account = get_messenger_pair(
            db, conversation.teacher_id, conversation.student_id, platform,
        )
        # Отправляем только когда оба участника привязаны к каналу.
        if not teacher_account or not student_account:
            continue

        accounts_by_user = {
            conversation.teacher_id: teacher_account,
            conversation.student_id: student_account,
        }
        student_telegram_target = (
            panel_student_telegram_target(db, conversation, student_account)
            if platform == MessengerPlatform.TELEGRAM
            and any(role == "student" for _, role in recipients)
            else None
        )
        delivered: list[dict] = []
        errors: list[dict] = []
        for recipient, recipient_role in recipients:
            account = accounts_by_user[recipient.id]
            target = (
                student_telegram_target
                if platform == MessengerPlatform.TELEGRAM and recipient_role == "student"
                else {
                    "chat_id": account.external_chat_id or account.external_user_id,
                }
            )
            if not target:
                errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "Не удалось определить адресата в " + platform.value.upper(),
                })
                continue

            if content_type == MessageKind.TEXT:
                outgoing_text = (
                    body if sender_role == "teacher"
                    else "Сообщение от ученика " + student.full_name + ":\n" + body
                    if sender_role == "student"
                    else "Сообщение от администратора школы:\n" + body
                )
            else:
                outgoing_text = (
                    body.strip()[:1024] if sender_role == "teacher"
                    else (
                        "Сообщение от ученика " + student.full_name
                        + ((": " + body) if body else "")
                        if sender_role == "student"
                        else "От администратора школы" + ((": " + body) if body else "")
                    )
                )

            try:
                sent = await communication.send(OutboundMessage(
                    platform=platform,
                    external_chat_id=str(target["chat_id"]),
                    external_thread_id=(
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                    content_type=content_type,
                    text=outgoing_text,
                    media=media,
                    idempotency_key=(
                        f"panel-message:{row.id}:platform:{platform.value}:"
                        f"recipient:{recipient.id}"
                    ),
                ))
                delivered.append({
                    "user_id": recipient.id,
                    "external_message_id": str(sent.external_message_id),
                    "external_chat_id": str(target["chat_id"]),
                    "external_thread_id": (
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                })
            except (MessengerError, OSError, ValueError, TypeError, RuntimeError) as exc:
                error_type = getattr(exc, "provider_error_type", type(exc).__name__)
                logger.warning(
                    "Messenger delivery failed (platform=%s conversation_id=%s error_type=%s)",
                    platform.value, conversation.id, error_type,
                )
                errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "ошибка " + platform.value.upper() + " (" + error_type + ")",
                })

        results[platform.value] = {"delivered": delivered, "errors": errors}

    return results


async def store_panel_attachment(file: UploadFile, conversation_id: int):
    """Проверить и сохранить вложение."""
    if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail=ATTACHMENT_SIZE_ERROR)
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
    def copy_upload():
        with target_path.open("xb") as target:
            while chunk := file.file.read(1024 * 1024):
                if target.tell() + len(chunk) > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(status_code=413, detail=ATTACHMENT_SIZE_ERROR)
                target.write(chunk)
            return target.tell()

    try:
        size = await run_in_threadpool(copy_upload)
        if not size:
            raise HTTPException(status_code=400, detail="Файл пустой")
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise

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
    return size, original_name, relative, mime_type, kind


async def refresh_teacher_panel_after_web_delivery(bot, teacher_id: int, conversation_id: int) -> None:
    """Обновить панель преподавателя в фоне."""
    if not bot:
        return
    try:
        with SessionLocal() as db:
            teacher = db.get(User, teacher_id)
            conversation = db.get(Conversation, conversation_id)
            if not teacher or not conversation:
                return
            if not get_messenger_account(db, teacher.id, MessengerPlatform.TELEGRAM):
                return
            from app.modules.telegram.teacher import (
                clear_teacher_session,
                update_teacher_panel,
            )
            current_session = db.get(TeacherSession, teacher.id)
            if current_session and current_session.conversation_id != conversation.id:
                clear_teacher_session(db, teacher)
            await update_teacher_panel(bot, db, teacher)
    except (TelegramAPIError, SQLAlchemyError) as exc:
        logger.warning(
            "Could not refresh teacher panel after web delivery "
            "(teacher_id=%s conversation_id=%s error_type=%s)",
            teacher_id, conversation_id, type(exc).__name__,
        )
