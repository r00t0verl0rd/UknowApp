"""One application pipeline for all inbound messenger messages."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update
from app.models import (
    Assignment,
    Conversation,
    Message,
    StudentTelegramGroup,
    TeacherSession,
    User,
)
from app.modules.communication.accounts import (
    CONNECTION_CODE_RE,
    claim_messenger_connection_code,
    get_messenger_account,
    get_messenger_user,
)
from app.modules.communication.contracts import InboundMessage, MessengerError, MessengerPlatform
from app.modules.notifications.service import schedule_push
from app.rate_limit import SlidingWindowLimiter

from .moderation import contact_would_be_exposed

logger = logging.getLogger(__name__)

_CONNECTION_CODE_WINDOW = 15 * 60
_CONNECTION_CODE_LIMIT = 5
_UNLINKED_MESSAGE_WINDOW = 60
_UNLINKED_MESSAGE_LIMIT = 12
_connection_code_limiter = SlidingWindowLimiter()
_unlinked_message_limiter = SlidingWindowLimiter()


class InboundMessengerPort(Protocol):
    platform: MessengerPlatform

    async def send_text(
        self, external_chat_id: str, text: str, thread_id: str | None = None,
    ) -> str:
        ...

    async def copy_message(
        self,
        source_chat_id: str,
        source_message_id: str,
        target_chat_id: str,
        target_thread_id: str | None = None,
        caption: str | None = None,
    ) -> str:
        ...

    async def archive_media(self, inbound: InboundMessage, row: Message) -> None:
        ...

    async def delete_message(
        self, external_chat_id: str, external_message_id: str,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class InboundUiResult:
    handled: bool
    force_keyboard_refresh: bool = False


InboundUiHandler = Callable[
    [Session, InboundMessage, User, InboundMessengerPort], Awaitable[InboundUiResult],
]


@dataclass(frozen=True, slots=True)
class InboundProcessResult:
    refresh_teacher_id: int | None = None
    force_teacher_panel_refresh: bool = False


def message_metadata(message: InboundMessage) -> dict:
    result = {}
    if message.media:
        result[message.content_type.value] = {
            "file_id": message.media.provider_file_id,
            "file_unique_id": message.media.provider_unique_file_id,
            "file_name": message.media.file_name,
            "mime_type": message.media.mime_type,
        }
    if message.location:
        result["location"] = {
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
        }
    if message.poll:
        result["poll"] = {
            "question": message.poll.question,
            "options": list(message.poll.options),
        }
    if message.contact_present:
        result["contact_hidden"] = True
    return result


def persist_message(
    db: Session,
    conversation_id: int,
    sender: User,
    inbound: InboundMessage,
    status: str,
    safe_text: str | None = None,
) -> Message:
    body = safe_text if safe_text is not None else (inbound.text or inbound.caption)
    metadata = message_metadata(inbound)
    if sender.role == "student":
        metadata["teacher_read_at"] = None
    try:
        source_message_id = int(inbound.external_message_id)
    except (TypeError, ValueError):
        source_message_id = None
    row = Message(
        conversation_id=conversation_id,
        sender_id=sender.id,
        sender_role=sender.role,
        content_type=inbound.content_type.value,
        text=body[:12000],
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        delivery_status=status,
        source_message_id=source_message_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    conversation = db.get(Conversation, conversation_id)
    if conversation:
        recipients = (
            [conversation.teacher_id]
            if sender.role == "student"
            else [conversation.student_id]
        )
        schedule_push(
            db,
            recipients,
            "Новое сообщение · UknowApp",
            (sender.full_name + ": " + (body or "Новое сообщение"))[:240],
            f"/?openConversation={conversation.id}",
            include_admin=True,
        )
    publish_chat_update(conversation_id)
    return row


def current_student_conversation(db: Session, student_id: int) -> Conversation | None:
    assignment = db.scalar(
        select(Assignment)
        .where(
            Assignment.student_id == student_id,
            Assignment.active.is_(True),
        )
        .order_by(Assignment.created_at.desc()),
    )
    return assignment.conversation if assignment else None


def conversation_messages(db: Session, conversation_id: int) -> list[Message]:
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id),
    ).all()


def unanswered_student_messages(rows: list[Message]) -> list[Message]:
    last_teacher_index = -1
    for index, row in enumerate(rows):
        if row.sender_role == "teacher" and row.delivery_status == "delivered":
            last_teacher_index = index
    return [
        row
        for index, row in enumerate(rows)
        if index > last_teacher_index
        and row.sender_role == "student"
        and row.delivery_status == "delivered"
    ]


def pending_student_messages(rows: list[Message]) -> list[Message]:
    return [
        row
        for row in unanswered_student_messages(rows)
        if json.loads(row.metadata_json or "{}").get("teacher_read_at") is None
    ]


def mark_messages_read_by_teacher(db: Session, messages: list[Message]) -> None:
    if not messages:
        return
    now = datetime.now(UTC).isoformat()
    changed = False
    for row in messages:
        metadata = json.loads(row.metadata_json or "{}")
        if metadata.get("teacher_read_at") is None:
            metadata["teacher_read_at"] = now
            row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            changed = True
    if changed:
        db.commit()


def mark_visible_messages_read_by_teacher(
    db: Session, conversation: Conversation,
) -> None:
    rows = conversation_messages(db, conversation.id)
    mark_messages_read_by_teacher(
        db,
        [
            row
            for row in rows[-12:]
            if row.sender_role == "student" and row.delivery_status == "delivered"
        ],
    )


def get_teacher_conversation(
    db: Session, teacher: User | None, conversation_id: int,
) -> Conversation | None:
    conversation = db.get(Conversation, conversation_id)
    if (
        not teacher
        or teacher.role != "teacher"
        or not conversation
        or conversation.status != "active"
        or not conversation.assignment
        or not conversation.assignment.active
        or conversation.assignment.teacher_id != teacher.id
    ):
        return None
    return conversation


def set_teacher_session(db: Session, teacher: User, conversation: Conversation) -> None:
    session = db.get(TeacherSession, teacher.id)
    if session:
        session.conversation_id = conversation.id
    else:
        db.add(TeacherSession(teacher_id=teacher.id, conversation_id=conversation.id))
    db.commit()


def clear_teacher_session(db: Session, teacher: User) -> None:
    if teacher.role != "teacher":
        return
    db.query(TeacherSession).filter(
        TeacherSession.teacher_id == teacher.id,
    ).delete(synchronize_session=False)
    db.commit()


def bind_student_forum_topic(
    db: Session,
    student: User,
    chat_id: str | int,
    thread_id: str | int,
    group_title: str | None,
) -> bool:
    chat_id = int(chat_id)
    thread_id = int(thread_id)
    occupied = db.scalar(
        select(StudentTelegramGroup).where(
            StudentTelegramGroup.chat_id == chat_id,
            StudentTelegramGroup.thread_id == thread_id,
        ),
    )
    if occupied and occupied.student_id != student.id:
        return False

    binding = db.get(StudentTelegramGroup, student.id)
    if binding is None:
        binding = StudentTelegramGroup(
            student_id=student.id,
            chat_id=chat_id,
            thread_id=thread_id,
            group_title=group_title,
        )
        db.add(binding)
    else:
        binding.chat_id = chat_id
        binding.thread_id = thread_id
        binding.group_title = group_title
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def _resolve_forum_message(
    db: Session, inbound: InboundMessage, sender: User | None,
) -> StudentTelegramGroup | None:
    if (
        inbound.chat_type not in {"group", "supergroup"}
        or not inbound.external_thread_id
        or not inbound.chat_is_forum
        or not sender
        or sender.role != "student"
    ):
        return None

    chat_id = int(inbound.external_chat_id)
    thread_id = int(inbound.external_thread_id)
    binding = db.scalar(
        select(StudentTelegramGroup).where(
            StudentTelegramGroup.chat_id == chat_id,
            StudentTelegramGroup.thread_id == thread_id,
            StudentTelegramGroup.student_id == sender.id,
        ),
    )
    if binding:
        return binding

    occupied = db.scalar(
        select(StudentTelegramGroup).where(
            StudentTelegramGroup.chat_id == chat_id,
            StudentTelegramGroup.thread_id == thread_id,
        ),
    )
    if occupied and occupied.student_id != sender.id:
        logger.warning(
            "INBOUND_FORUM_ROUTE_DENIED student_id=%s owner_student_id=%s chat_id=%s thread_id=%s",
            sender.id, occupied.student_id, chat_id, thread_id,
        )
        return None

    conversation = current_student_conversation(db, sender.id)
    if occupied or not conversation or conversation.status != "active":
        return None
    if not bind_student_forum_topic(
        db, sender, chat_id, thread_id, inbound.chat_title,
    ):
        return None
    return db.get(StudentTelegramGroup, sender.id)


async def _handle_unlinked_sender(
    db: Session, inbound: InboundMessage, gateway: InboundMessengerPort,
) -> InboundProcessResult:
    external_user_id = inbound.external_user_id
    limiter_key = (inbound.platform.value, external_user_id)
    if not external_user_id or not _unlinked_message_limiter.allow_and_record(
        limiter_key, _UNLINKED_MESSAGE_LIMIT, _UNLINKED_MESSAGE_WINDOW,
    ):
        return InboundProcessResult()

    normalized = re.sub(r"[\s-]", "", inbound.text.strip()).upper()
    prompt = (
        "Аккаунт ещё не подключён. Попросите администратора сгенерировать код доступа "
        "в UknowApp, затем отправьте сюда код."
    )
    if not CONNECTION_CODE_RE.fullmatch(normalized):
        await gateway.send_text(
            inbound.external_chat_id, prompt, inbound.external_thread_id,
        )
        return InboundProcessResult()

    if not _connection_code_limiter.is_allowed(
        limiter_key, _CONNECTION_CODE_LIMIT, _CONNECTION_CODE_WINDOW,
    ):
        await gateway.send_text(
            inbound.external_chat_id,
            "Слишком много попыток подключения. Попробуйте снова через 15 минут.",
            inbound.external_thread_id,
        )
        return InboundProcessResult()

    try:
        linked_user, result = claim_messenger_connection_code(
            db,
            normalized,
            inbound.platform,
            external_user_id,
            inbound.external_chat_id,
            inbound.sender_username,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "Failed to process messenger connection code (platform=%s error_type=%s)",
            inbound.platform.value,
            type(exc).__name__,
        )
        await gateway.send_text(
            inbound.external_chat_id,
            "Не удалось обработать код из-за внутренней ошибки. "
            "Попробуйте ещё раз через минуту; администратор может посмотреть ошибку в терминале backend.",
            inbound.external_thread_id,
        )
        return InboundProcessResult()
    logger.info(
        "Messenger connection code processed: platform=%s result=%s",
        inbound.platform.value, result,
    )
    if result == "ok" and linked_user:
        _connection_code_limiter.clear(limiter_key)
        platform_label = {
            MessengerPlatform.TELEGRAM: "Telegram",
            MessengerPlatform.MAX: "MAX",
            MessengerPlatform.WHATSAPP: "WhatsApp",
        }[inbound.platform]
        if linked_user.role == "teacher":
            await gateway.send_text(
                inbound.external_chat_id,
                "✅ " + platform_label + " подключён к аккаунту «" + linked_user.full_name + "».",
                inbound.external_thread_id,
            )
            return InboundProcessResult(refresh_teacher_id=linked_user.id)

        conversation = current_student_conversation(db, linked_user.id)
        if conversation and conversation.status == "active":
            response = (
                "😊 Вы подключены к UknowApp.\n"
                "🎓 Ваш учитель: " + conversation.assignment.teacher.full_name + ".\n\n"
                "Пишите сюда и отправляйте файлы — всё попадёт вашему учителю."
            )
        else:
            response = (
                "✅ " + platform_label + " подключён к аккаунту «" + linked_user.full_name + "».\n"
                "Учитель пока не назначен. Как только администратор создаст связь, "
                "здесь можно будет начать переписку."
            )
        await gateway.send_text(inbound.external_chat_id, response, inbound.external_thread_id)
        return InboundProcessResult()

    _connection_code_limiter.record(limiter_key, _CONNECTION_CODE_WINDOW)
    if result == "identity_already_linked":
        response = "Этот аккаунт мессенджера уже привязан к другому пользователю UknowApp."
    elif result == "account_already_linked":
        response = "К аккаунту UknowApp уже привязан другой аккаунт этого мессенджера. Обратитесь к администратору."
    else:
        response = "Код не найден или был заменён. Проверьте его или запросите новый у администратора."
    await gateway.send_text(inbound.external_chat_id, response, inbound.external_thread_id)
    return InboundProcessResult()


async def _deliver_student_message_to_teacher(
    db: Session,
    inbound: InboundMessage,
    row: Message,
    conversation: Conversation,
    sender: User,
    teacher: User,
    teacher_chat_id: str,
    gateway: InboundMessengerPort,
) -> None:
    metadata = json.loads(row.metadata_json or "{}")
    if metadata.get("media"):
        caption = "📎 От ученика: " + sender.full_name
        if inbound.caption.strip():
            caption += "\n" + inbound.caption.strip()
        try:
            copied_id = await gateway.copy_message(
                inbound.external_chat_id,
                inbound.external_message_id,
                teacher_chat_id,
                caption=caption[:1024],
            )
        except MessengerError as copy_error:
            logger.info(
                "Messenger media copy with caption failed; retrying without caption "
                "(conversation_id=%s error_type=%s)",
                conversation.id, type(copy_error).__name__,
            )
            notice_id = await gateway.send_text(
                teacher_chat_id, "📎 Вложение от ученика: " + sender.full_name,
            )
            copied_id = await gateway.copy_message(
                inbound.external_chat_id,
                inbound.external_message_id,
                teacher_chat_id,
            )
            metadata["teacher_inbox_notice_message_id"] = int(notice_id)
        metadata["teacher_inbox_media_message_id"] = int(copied_id)
        row.metadata_json = json.dumps(metadata, ensure_ascii=False)

    row.delivery_status = "delivered"
    db.commit()
    publish_chat_update(conversation.id)
    teacher_session = db.get(TeacherSession, teacher.id)
    if teacher_session and teacher_session.conversation_id != conversation.id:
        clear_teacher_session(db, teacher)


async def _deliver_teacher_reply(
    db: Session,
    inbound: InboundMessage,
    row: Message,
    conversation: Conversation,
    teacher: User,
    student: User,
    student_chat_id: str,
    unanswered_before_reply: list[Message],
    gateway: InboundMessengerPort,
) -> None:
    destination_chat_id = student_chat_id
    destination_thread_id = None
    for pending in reversed(unanswered_before_reply):
        metadata = json.loads(pending.metadata_json or "{}")
        if metadata.get("source_mode") == "group_topic":
            destination_chat_id = str(metadata["source_chat_id"])
            destination_thread_id = (
                str(metadata["source_thread_id"])
                if metadata.get("source_thread_id") is not None else None
            )
            break
        if metadata.get("source_mode", "private") == "private":
            break

    if not unanswered_before_reply:
        binding = db.get(StudentTelegramGroup, student.id)
        if binding:
            destination_chat_id = str(binding.chat_id)
            destination_thread_id = str(binding.thread_id)

    copied_id = await gateway.copy_message(
        inbound.external_chat_id,
        inbound.external_message_id,
        destination_chat_id,
        target_thread_id=destination_thread_id,
    )
    row.destination_message_id = int(copied_id)
    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = [{
        "user_id": student.id,
        "telegram_message_id": row.destination_message_id,
        "chat_id": int(destination_chat_id),
        "thread_id": int(destination_thread_id) if destination_thread_id is not None else None,
    }]
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = "delivered"
    db.commit()
    publish_chat_update(conversation.id)

    if inbound.text:
        try:
            await gateway.delete_message(
                inbound.external_chat_id, inbound.external_message_id,
            )
        except MessengerError as exc:
            logger.info(
                "Could not remove teacher's sent text from the messenger chat (error_type=%s)",
                type(exc).__name__,
            )

    for pending in unanswered_before_reply:
        if not pending.destination_message_id:
            continue
        try:
            await gateway.delete_message(
                inbound.external_chat_id, str(pending.destination_message_id),
            )
        except MessengerError as exc:
            logger.info(
                "Could not remove handled student message %s "
                "(external_message_id=%s error_type=%s)",
                pending.id, pending.destination_message_id, type(exc).__name__,
            )
    mark_messages_read_by_teacher(db, unanswered_before_reply)


async def process_inbound_message(
    db: Session,
    inbound: InboundMessage,
    gateway: InboundMessengerPort,
    ui_handler: InboundUiHandler | None = None,
) -> InboundProcessResult:
    """Run identity, routing, moderation, persistence and delivery as one flow."""
    sender = get_messenger_user(db, inbound.platform, inbound.external_user_id)
    group_binding = None

    if inbound.chat_type in {"group", "supergroup"}:
        if not inbound.external_thread_id:
            logger.info(
                "Ignoring group message outside a bound topic: chat_id=%s message_id=%s",
                inbound.external_chat_id, inbound.external_message_id,
            )
            return InboundProcessResult()
        group_binding = _resolve_forum_message(db, inbound, sender)
        if not sender or sender.role != "student" or not group_binding:
            logger.warning(
                "INBOUND_GROUP_MESSAGE_IGNORED platform=%s external_user_id=%s "
                "sender_chat_id=%s chat_id=%s thread_id=%s",
                inbound.platform.value, inbound.external_user_id,
                inbound.sender_chat_id, inbound.external_chat_id,
                inbound.external_thread_id,
            )
            return InboundProcessResult()
    elif not sender and not inbound.external_user_id:
        logger.warning(
            "INBOUND_MESSAGE_IGNORED_WITHOUT_IDENTITY platform=%s chat_id=%s sender_chat_id=%s",
            inbound.platform.value, inbound.external_chat_id, inbound.sender_chat_id,
        )
        return InboundProcessResult()

    if not sender:
        return await _handle_unlinked_sender(db, inbound, gateway)

    if sender.role == "admin":
        await gateway.send_text(
            inbound.external_chat_id,
            "Администратор управляет пользователями и переписками через веб-панель.",
            inbound.external_thread_id,
        )
        return InboundProcessResult()

    if sender.role == "teacher" and ui_handler:
        ui_result = await ui_handler(db, inbound, sender, gateway)
        if ui_result.handled:
            return InboundProcessResult(
                refresh_teacher_id=sender.id,
                force_teacher_panel_refresh=ui_result.force_keyboard_refresh,
            )

    if sender.role == "student":
        conversation = current_student_conversation(db, sender.id)
        if not conversation or conversation.status != "active":
            await gateway.send_text(
                inbound.external_chat_id,
                "Пока вам не назначен активный учитель. Обратитесь к администратору.",
                inbound.external_thread_id,
            )
            return InboundProcessResult()
        recipient = conversation.assignment.teacher
    else:
        session = db.get(TeacherSession, sender.id)
        conversation = (
            get_teacher_conversation(db, sender, session.conversation_id)
            if session else None
        )
        if not conversation:
            try:
                await gateway.delete_message(
                    inbound.external_chat_id, inbound.external_message_id,
                )
            except MessengerError as exc:
                logger.debug(
                    "Could not remove teacher message sent without an active selection "
                    "(error_type=%s)", type(exc).__name__,
                )
            return InboundProcessResult(refresh_teacher_id=sender.id)
        recipient = conversation.assignment.student

    if contact_would_be_exposed(inbound):
        persist_message(
            db, conversation.id, sender, inbound, "blocked_contact",
            "[Контактные данные скрыты системой]",
        )
        await gateway.send_text(
            inbound.external_chat_id,
            "Сообщение не отправлено: в нём обнаружены контактные данные. "
            "Личные телефоны, email и адреса мессенджеров нельзя передавать через этот чат.",
            inbound.external_thread_id,
        )
        return InboundProcessResult(refresh_teacher_id=conversation.teacher_id)

    unanswered_before_reply = (
        unanswered_student_messages(conversation_messages(db, conversation.id))
        if sender.role == "teacher" else []
    )
    if sender.role == "teacher":
        mark_visible_messages_read_by_teacher(db, conversation)

    row = persist_message(db, conversation.id, sender, inbound, "pending")
    metadata = json.loads(row.metadata_json or "{}")
    metadata["source_mode"] = "group_topic" if group_binding else "private"
    try:
        metadata["source_chat_id"] = int(inbound.external_chat_id)
        metadata["source_thread_id"] = (
            int(inbound.external_thread_id) if group_binding else None
        )
    except ValueError:
        metadata["source_chat_id"] = inbound.external_chat_id
        metadata["source_thread_id"] = inbound.external_thread_id if group_binding else None
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()
    publish_chat_update(conversation.id)
    await gateway.archive_media(inbound, row)

    recipient_account = get_messenger_account(db, recipient.id, inbound.platform)
    recipient_chat_id = (
        recipient_account.external_chat_id or recipient_account.external_user_id
        if recipient_account else None
    )
    if not recipient_chat_id:
        if sender.role == "teacher":
            metadata = json.loads(row.metadata_json or "{}")
            metadata["telegram_delivery_errors"] = [{
                "name": recipient.full_name,
                "role": "student",
                "reason": "Аккаунт получателя не подключён к " + inbound.platform.value.upper(),
            }]
            row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            row.delivery_status = "delivered"
            db.commit()
            publish_chat_update(conversation.id)
            mark_messages_read_by_teacher(db, unanswered_before_reply)
            if inbound.text:
                try:
                    await gateway.delete_message(
                        inbound.external_chat_id, inbound.external_message_id,
                    )
                except MessengerError as exc:
                    logger.info(
                        "Could not remove teacher text after in-app delivery (error_type=%s)",
                        type(exc).__name__,
                    )
            return InboundProcessResult(refresh_teacher_id=sender.id)

        row.delivery_status = "failed"
        db.commit()
        publish_chat_update(conversation.id)
        await gateway.send_text(
            inbound.external_chat_id,
            "Не удалось отправить сообщение. Попробуйте позже.",
            inbound.external_thread_id,
        )
        return InboundProcessResult(refresh_teacher_id=conversation.teacher_id)

    try:
        if sender.role == "student":
            await _deliver_student_message_to_teacher(
                db, inbound, row, conversation, sender, recipient,
                recipient_chat_id, gateway,
            )
        else:
            await _deliver_teacher_reply(
                db, inbound, row, conversation, sender, recipient,
                recipient_chat_id, unanswered_before_reply, gateway,
            )
    except (MessengerError, SQLAlchemyError, ValueError, OSError) as exc:
        row.delivery_status = "failed"
        db.commit()
        publish_chat_update(conversation.id)
        logger.warning(
            "Could not forward inbound messenger message (platform=%s conversation_id=%s error_type=%s)",
            inbound.platform.value, conversation.id, type(exc).__name__,
        )
        response = (
            "Не удалось доставить сообщение. Попробуйте ещё раз позже."
            if sender.role == "teacher"
            else "Не удалось отправить сообщение. Попробуйте ещё раз позже."
        )
        await gateway.send_text(
            inbound.external_chat_id, response, inbound.external_thread_id,
        )

    return InboundProcessResult(refresh_teacher_id=conversation.teacher_id)
