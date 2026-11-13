import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message as TgMessage
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .media_storage import archive_telegram_media
from .models import Assignment, ConnectionCode, Conversation, Message, TeacherSession, User

router = Router()
logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{4,}")
TG_LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_]+", re.I)
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")


def contact_would_be_exposed(message: TgMessage) -> bool:
    if message.contact:
        return True
    body = message.text or message.caption or ""
    if EMAIL_RE.search(body) or USERNAME_RE.search(body) or TG_LINK_RE.search(body):
        return True
    for match in PHONE_RE.findall(body):
        if sum(char.isdigit() for char in match) >= 8:
            return True
    return False


def message_metadata(message: TgMessage) -> dict:
    result = {}
    media_fields = ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation")
    for field in media_fields:
        item = getattr(message, field, None)
        if not item:
            continue
        if isinstance(item, list):
            item = item[-1]
        result[field] = {
            "file_id": getattr(item, "file_id", None),
            "file_unique_id": getattr(item, "file_unique_id", None),
            "file_name": getattr(item, "file_name", None),
            "mime_type": getattr(item, "mime_type", None),
        }
        break
    if message.location:
        result["location"] = {"latitude": message.location.latitude, "longitude": message.location.longitude}
    if message.poll:
        result["poll"] = {"question": message.poll.question, "options": [option.text for option in message.poll.options]}
    if message.contact:
        result["contact_hidden"] = True
    return result


def persist_message(
    db: Session,
    conversation_id: int,
    sender: User,
    message: TgMessage,
    status: str,
    safe_text: Optional[str] = None,
) -> Message:
    body = safe_text if safe_text is not None else (message.text or message.caption or "")
    content_type = message.content_type.value if hasattr(message.content_type, "value") else str(message.content_type)
    row = Message(
        conversation_id=conversation_id,
        sender_id=sender.id,
        sender_role=sender.role,
        content_type=content_type,
        text=body[:12000],
        metadata_json=json.dumps(message_metadata(message), ensure_ascii=False),
        delivery_status=status,
        source_message_id=message.message_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


CONNECTION_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


def claim_connection_code(
    db: Session,
    raw_code: str,
    telegram_id: int,
) -> tuple[Optional[User], str]:
    normalized = re.sub(r"[\s-]", "", raw_code).upper()
    if not CONNECTION_CODE_RE.fullmatch(normalized):
        return None, "invalid_format"

    code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    connection_code = db.scalar(
        select(ConnectionCode).where(ConnectionCode.code_hash == code_hash)
    )
    if not connection_code:
        return None, "invalid"
    if connection_code.used_at is not None:
        return None, "used"

    now = datetime.now(timezone.utc)
    expires_at = connection_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        connection_code.used_at = now
        db.commit()
        return None, "expired"

    user = db.get(User, connection_code.user_id)
    if not user or not user.active or user.role not in {"teacher", "student"}:
        connection_code.used_at = now
        db.commit()
        return None, "inactive"

    existing_user = db.scalar(
        select(User).where(User.telegram_id == telegram_id)
    )
    if existing_user and existing_user.id != user.id:
        return None, "telegram_already_linked"
    if user.telegram_id and user.telegram_id != telegram_id:
        return None, "account_already_linked"

    # Atomically mark the code as used and bind the Telegram ID in one transaction.
    result = db.execute(
        update(ConnectionCode)
        .where(
            ConnectionCode.id == connection_code.id,
            ConnectionCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        return None, "used"

    user.telegram_id = telegram_id
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        return None, "telegram_already_linked"
    return user, "ok"


def get_linked_user(db: Session, telegram_id: int) -> Optional[User]:
    return db.scalar(select(User).where(User.telegram_id == telegram_id, User.active.is_(True)))


def current_student_conversation(db: Session, student_id: int) -> Optional[Conversation]:
    assignment = db.scalar(
        select(Assignment).where(Assignment.student_id == student_id, Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc())
    )
    if not assignment or not assignment.teacher.active:
        return None
    return assignment.conversation


@router.message(CommandStart())
async def start(message: TgMessage):
    if not message.from_user:
        return
    with SessionLocal() as db:
        user = get_linked_user(db, message.from_user.id)
        if not user:
            await message.answer(
                "Добро пожаловать в UknowApp!\n\n"
                "Для подключения попросите администратора сгенерировать для вас одноразовый код.\n"
                "Затем отправьте этот код сюда отдельным сообщением. Код действует 15 минут."
            )
            return
        if user.role == "student":
            await message.answer("Здравствуйте! Напишите сообщение здесь — оно попадёт вашему учителю через бота.")
        elif user.role == "teacher":
            await message.answer(
                "Здравствуйте! Сообщения учеников будут приходить сюда. Нажмите «Ответить» под нужным сообщением, "
                "затем отправляйте ответ в этот чат с ботом."
            )
        else:
            await message.answer("Этот Telegram-аккаунт имеет роль администратора.")


@router.callback_query(F.data.startswith("reply:"))
async def choose_conversation(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    try:
        conversation_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная переписка", show_alert=True)
        return

    with SessionLocal() as db:
        teacher = get_linked_user(db, callback.from_user.id)
        conversation = db.get(Conversation, conversation_id)
        if (
            not teacher or teacher.role != "teacher" or not conversation
            or conversation.status != "active"
            or conversation.assignment.teacher_id != teacher.id
            or not conversation.assignment.active
        ):
            await callback.answer("У вас нет доступа к этой переписке", show_alert=True)
            return
        session = db.get(TeacherSession, teacher.id)
        if session:
            session.conversation_id = conversation.id
        else:
            db.add(TeacherSession(teacher_id=teacher.id, conversation_id=conversation.id))
        db.commit()
    await callback.answer("Диалог выбран")
    if callback.message:
        await callback.message.answer("Выбран диалог с учеником. Следующее сообщение будет отправлено ему.")


@router.message()
async def route_message(message: TgMessage, bot: Bot):
    if not message.from_user:
        return
    logger.info(
        "Received Telegram message: telegram_id=%s content_type=%s text_length=%s",
        message.from_user.id,
        message.content_type,
        len(message.text or message.caption or ""),
    )
    with SessionLocal() as db:
        sender = get_linked_user(db, message.from_user.id)
        if not sender:
            text = (message.text or "").strip()
            normalized = re.sub(r"[\s-]", "", text).upper()
            if CONNECTION_CODE_RE.fullmatch(normalized):
                try:
                    linked_user, result = claim_connection_code(db, normalized, message.from_user.id)
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Failed to process Telegram connection code for telegram_id=%s",
                        message.from_user.id,
                    )
                    await message.answer(
                        "Не удалось обработать код из-за внутренней ошибки. "
                        "Попробуйте ещё раз через минуту; администратор может посмотреть ошибку в терминале backend."
                    )
                    return
                logger.info(
                    "Telegram connection code processed: telegram_id=%s result=%s",
                    message.from_user.id,
                    result,
                )
                if result == "ok" and linked_user:
                    if linked_user.role == "student":
                        next_step = "Теперь отправьте сообщение — оно попадёт назначенному учителю."
                    else:
                        next_step = (
                            "Когда ученик напишет вам, нажмите «Ответить» под его сообщением, "
                            "чтобы выбрать переписку."
                        )
                    await message.answer(
                        "Готово! Telegram подключён к аккаунту «"
                        + linked_user.full_name
                        + "» ("
                        + ("ученик" if linked_user.role == "student" else "учитель")
                        + ").\n\n"
                        + next_step
                    )
                elif result == "expired":
                    await message.answer("Срок действия кода истёк. Попросите администратора создать новый код.")
                elif result == "used":
                    await message.answer("Этот код уже использован. Попросите администратора создать новый.")
                elif result == "telegram_already_linked":
                    await message.answer("Этот Telegram-аккаунт уже привязан к другому пользователю UknowApp.")
                elif result == "account_already_linked":
                    await message.answer("К аккаунту уже привязан другой Telegram. Обратитесь к администратору.")
                elif result == "inactive":
                    await message.answer("Этот аккаунт UknowApp отключён. Обратитесь к администратору.")
                else:
                    await message.answer("Код не найден или был заменён. Проверьте его или запросите новый у администратора.")
            else:
                await message.answer(
                    "Аккаунт ещё не подключён. Попросите администратора сгенерировать код в UknowApp, "
                    "затем отправьте сюда 8 символов кода (можно с дефисом)."
                )
            return
        if sender.role == "admin":
            await message.answer("Администратор управляет пользователями и переписками через веб-панель.")
            return

        if sender.role == "student":
            conversation = current_student_conversation(db, sender.id)
            if not conversation:
                await message.answer("Пока вам не назначен учитель. Обратитесь к администратору.")
                return
            recipient = conversation.assignment.teacher
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Ответить", callback_data="reply:" + str(conversation.id))
            ]])
        else:
            session = db.get(TeacherSession, sender.id)
            conversation = db.get(Conversation, session.conversation_id) if session else None
            if (
                not conversation or conversation.status != "active"
                or not conversation.assignment.active
                or conversation.assignment.teacher_id != sender.id
            ):
                await message.answer("Сначала выберите переписку: нажмите «Ответить» под сообщением ученика.")
                return
            recipient = conversation.assignment.student
            reply_markup = None

        if contact_would_be_exposed(message):
            persist_message(
                db, conversation.id, sender, message, "blocked_contact",
                "[Контактные данные скрыты системой]",
            )
            await message.answer(
                "Сообщение не отправлено: в нём обнаружены контактные данные. "
                "Личные телефоны, email и Telegram-адреса нельзя передавать через этот чат."
            )
            return

        row = persist_message(db, conversation.id, sender, message, "pending")
        await archive_telegram_media(bot, message, row)
        if not recipient.telegram_id or not recipient.active:
            row.delivery_status = "failed"
            db.commit()
            await message.answer("Не удалось доставить сообщение: аккаунт собеседника не подключён.")
            return
        try:
            copied = await bot.copy_message(
                chat_id=recipient.telegram_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=reply_markup,
            )
            row.destination_message_id = copied.message_id
            row.delivery_status = "delivered"
            db.commit()
            if sender.role == "student":
                await message.answer("Сообщение доставлено учителю.")
        except Exception:
            row.delivery_status = "failed"
            db.commit()
            await message.answer("Не удалось доставить сообщение. Попробуйте ещё раз позже.")


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
