import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message as TgMessage
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .media_storage import archive_telegram_media
from .models import Assignment, ConnectionCode, Conversation, Message, TeacherPanel, TeacherSession, User

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
    metadata = message_metadata(message)
    if sender.role == "student":
        metadata["teacher_read_at"] = None
    row = Message(
        conversation_id=conversation_id,
        sender_id=sender.id,
        sender_role=sender.role,
        content_type=content_type,
        text=body[:12000],
        metadata_json=json.dumps(metadata, ensure_ascii=False),
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



TEACHER_PAGE_SIZE = 6
CHAT_PAGE_SIZE = 8


def message_preview(row: Optional[Message]) -> str:
    if not row:
        return "Сообщений пока нет"
    body = (row.text or "").strip()
    if body:
        body = " ".join(body.split())
        return body if len(body) <= 115 else body[:112] + "…"
    labels = {
        "voice": "🎤 Голосовое сообщение",
        "video_note": "⭕ Видеокружочек",
        "photo": "🖼 Фотография",
        "video": "🎬 Видео",
        "audio": "🎵 Аудио",
        "document": "📎 Документ",
        "sticker": "Стикер",
        "animation": "GIF-анимация",
        "location": "Геопозиция",
        "contact": "Контакт",
        "poll": "Опрос",
    }
    return labels.get(row.content_type, "Вложение: " + (row.content_type or "файл"))


def conversation_messages(db: Session, conversation_id: int) -> list[Message]:
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()


async def edit_inline_message(target: TgMessage, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await target.edit_text(text, reply_markup=markup)
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.info("Could not edit Telegram panel message; sending a new one: %s", exc)
        await target.answer(text, reply_markup=markup)


def pending_student_messages(rows: list[Message]) -> list[Message]:
    """Return only delivered student messages not yet handled by the teacher.

    Older rows do not have a read marker, so the latest teacher reply is used
    as a compatibility boundary for messages created before this feature.
    """
    last_teacher_index = -1
    for index, row in enumerate(rows):
        if row.sender_role == "teacher" and row.delivery_status == "delivered":
            last_teacher_index = index

    pending = []
    for index, row in enumerate(rows):
        if index <= last_teacher_index or row.sender_role != "student" or row.delivery_status != "delivered":
            continue
        metadata = json.loads(row.metadata_json or "{}")
        if metadata.get("teacher_read_at") is None:
            pending.append(row)
    return pending


def teacher_conversations(db: Session, teacher: User) -> list[dict]:
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.teacher_id == teacher.id, Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc())
    ).all()
    items = []
    for assignment in assignments:
        student = assignment.student
        conversation = assignment.conversation
        if (
            not student or not student.active or not conversation
            or conversation.status != "active"
        ):
            continue
        rows = conversation_messages(db, conversation.id)
        unread = pending_student_messages(rows)
        if not unread:
            continue
        items.append({
            "student": student,
            "conversation": conversation,
            "unread": unread,
            "unanswered": len(unread),
            "preview": message_preview(unread[-1]),
            "last_at": unread[-1].created_at.isoformat(),
        })
    items.sort(key=lambda item: item["last_at"], reverse=True)
    return items


def get_teacher_conversation(db: Session, teacher: User, conversation_id: int) -> Optional[Conversation]:
    conversation = db.get(Conversation, conversation_id)
    if (
        not teacher or teacher.role != "teacher" or not teacher.active
        or not conversation or conversation.status != "active"
        or not conversation.assignment.active
        or conversation.assignment.teacher_id != teacher.id
        or not conversation.assignment.student.active
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
        TeacherSession.teacher_id == teacher.id
    ).delete(synchronize_session=False)
    db.commit()


def role_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↻ Обновить", callback_data="ui:home")
    ]])


def teacher_panel_view(db: Session, teacher: User, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    items = teacher_conversations(db, teacher)
    total_unread = sum(item["unanswered"] for item in items)
    total_pages = max(1, (len(items) + TEACHER_PAGE_SIZE - 1) // TEACHER_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    visible = items[page * TEACHER_PAGE_SIZE:(page + 1) * TEACHER_PAGE_SIZE]
    lines = ["👩‍🏫 Панель учителя", "Новых сообщений: " + str(total_unread), ""]
    keyboard = []
    if not visible:
        lines.append("Пока нет сообщений, ожидающих ответа.")
    else:
        for item in visible:
            student_name = item["student"].full_name
            lines.append("👤 " + student_name + " · " + str(item["unanswered"]) + " новых")
            for row in item["unread"][-3:]:
                lines.append("   " + message_preview(row))
            if item["unanswered"] > 3:
                lines.append("   …ещё " + str(item["unanswered"] - 3) + " сообщений")
            lines.append("")
            keyboard.append([InlineKeyboardButton(
                text=("Ответить · " + student_name)[:60],
                callback_data="ui:chat:" + str(item["conversation"].id),
            )])
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="← Назад", callback_data="ui:teacher:page:" + str(page - 1)))
        nav.append(InlineKeyboardButton(text=str(page + 1) + "/" + str(total_pages), callback_data="ui:teacher:page:" + str(page)))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="Вперёд →", callback_data="ui:teacher:page:" + str(page + 1)))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="↻ Обновить", callback_data="ui:home")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


async def update_teacher_panel(bot: Bot, db: Session, teacher: User) -> None:
    if not teacher.telegram_id:
        return
    text, markup = teacher_panel_view(db, teacher)
    panel = db.get(TeacherPanel, teacher.id)
    if panel:
        try:
            await bot.edit_message_text(
                chat_id=teacher.telegram_id,
                message_id=panel.message_id,
                text=text,
                reply_markup=markup,
            )
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.info("Stored teacher panel is unavailable; creating a new one: %s", exc)
    sent = await bot.send_message(
        chat_id=teacher.telegram_id,
        text=text,
        reply_markup=markup,
    )
    if panel:
        panel.message_id = sent.message_id
        panel.chat_id = teacher.telegram_id
    else:
        db.add(TeacherPanel(
            teacher_id=teacher.id,
            message_id=sent.message_id,
            chat_id=teacher.telegram_id,
        ))
    db.commit()


async def show_teacher_panel(target: TgMessage, teacher: User, db: Session, page: int = 0, edit: bool = False) -> None:
    text, markup = teacher_panel_view(db, teacher, page)
    if edit:
        await edit_inline_message(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


async def show_teacher_pending(target: TgMessage, teacher: User, db: Session, conversation: Conversation, edit: bool = False) -> None:
    rows = conversation_messages(db, conversation.id)
    unread = pending_student_messages(rows)
    student = conversation.assignment.student
    lines = ["👤 " + student.full_name, "Непрочитанные сообщения: " + str(len(unread)), ""]
    if unread:
        for row in unread:
            lines.append(message_preview(row))
            lines.append("")
    else:
        lines.append("Новых сообщений нет.")
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data="ui:reply:" + str(conversation.id))],
        [InlineKeyboardButton(text="← К списку учеников", callback_data="ui:teacher:page:0")],
    ])
    text = "\n".join(lines)[:3900]
    if edit:
        await edit_inline_message(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


async def show_role_panel(target: TgMessage, user: User, db: Session, edit: bool = False) -> None:
    if user.role == "teacher":
        await show_teacher_panel(target, user, db, page=0, edit=edit)
    elif user.role == "admin":
        text = "Администратор управляет системой через веб-панель."
        if edit:
            await edit_inline_message(target, text)
        else:
            await target.answer(text)
    # Student accounts intentionally have no bot menu: the private chat itself
    # is the conversation, with only messages from the teacher appearing here.


async def show_reply_prompt(target: TgMessage, teacher: User, conversation: Conversation) -> None:
    await target.answer(
        "Ответ выбранному ученику: " + conversation.assignment.student.full_name + ".\n"
        "Отправьте сообщение или вложение."
    )


@router.message(CommandStart())
async def start(message: TgMessage, bot: Bot):
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
        if user.role == "teacher":
            clear_teacher_session(db, user)
            await update_teacher_panel(bot, db, user)


@router.message(Command("menu"))
async def open_menu(message: TgMessage, bot: Bot):
    if not message.from_user:
        return
    with SessionLocal() as db:
        user = get_linked_user(db, message.from_user.id)
        if not user:
            await message.answer("Сначала подключите аккаунт UknowApp с помощью кода администратора.")
            return
        if user.role == "teacher":
            clear_teacher_session(db, user)
            await update_teacher_panel(bot, db, user)


@router.callback_query(F.data.startswith("ui:"))
async def handle_panel_callback(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    parts = callback.data.split(":")
    with SessionLocal() as db:
        user = get_linked_user(db, callback.from_user.id)
        if not user:
            await callback.answer("Аккаунт не подключён или отключён.", show_alert=True)
            return
        if not callback.message:
            await callback.answer()
            return

        action = parts[1] if len(parts) > 1 else ""
        try:
            if action == "home":
                clear_teacher_session(db, user)
                await callback.answer()
                await show_role_panel(callback.message, user, db, edit=True)
            elif action == "student" and len(parts) > 2 and parts[2] == "write":
                student_conversation = current_student_conversation(db, user.id) if user.role == "student" else None
                if not student_conversation or student_conversation.status != "active":
                    await callback.answer("Сейчас нет активного учителя.", show_alert=True)
                    return
                await callback.answer("Можно отправить сообщение")
                await edit_inline_message(
                    callback.message,
                    "✉️ Напишите сообщение или отправьте вложение следующим сообщением. "
                    "Оно будет доставлено вашему учителю.",
                    InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="← Главное меню", callback_data="ui:home")
                    ]]),
                )
            elif action == "teacher" and len(parts) > 3 and parts[2] == "page":
                if user.role != "teacher":
                    await callback.answer("Эта панель доступна только учителю.", show_alert=True)
                    return
                page = max(0, int(parts[3]))
                clear_teacher_session(db, user)
                await callback.answer()
                await show_teacher_panel(callback.message, user, db, page=page, edit=True)
            elif action == "chat" and len(parts) >= 3:
                if user.role != "teacher":
                    await callback.answer("Эта панель доступна только учителю.", show_alert=True)
                    return
                conversation_id = int(parts[2])
                clear_teacher_session(db, user)
                conversation = get_teacher_conversation(db, user, conversation_id)
                if not conversation:
                    await callback.answer("Ученик больше не назначен вам.", show_alert=True)
                    return
                await callback.answer()
                await show_teacher_pending(callback.message, user, db, conversation, edit=True)
            elif action == "reply" and len(parts) > 2:
                if user.role != "teacher":
                    await callback.answer("Отвечать может только учитель.", show_alert=True)
                    return
                conversation_id = int(parts[2])
                conversation = get_teacher_conversation(db, user, conversation_id)
                if not conversation:
                    await callback.answer("Эта переписка больше недоступна.", show_alert=True)
                    return
                set_teacher_session(db, user, conversation)
                await callback.answer()
                await show_reply_prompt(callback.message, user, conversation)
            else:
                await callback.answer("Неизвестная команда.", show_alert=True)
        except (ValueError, IndexError):
            await callback.answer("Некорректная команда.", show_alert=True)


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
        conversation = get_teacher_conversation(db, teacher, conversation_id) if teacher else None
        if not conversation:
            await callback.answer("У вас нет доступа к этой переписке", show_alert=True)
            return
        set_teacher_session(db, teacher, conversation)
        await callback.answer("Диалог выбран")
        if callback.message:
            await show_reply_prompt(callback.message, teacher, conversation)


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
                    await message.answer(
                        "✅ Telegram подключён к аккаунту «" + linked_user.full_name + "»."
                    )
                    if linked_user.role == "teacher":
                        await update_teacher_panel(bot, db, linked_user)
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
            if not conversation or conversation.status != "active":
                await message.answer("Пока вам не назначен активный учитель. Обратитесь к администратору.")
                return
            recipient = conversation.assignment.teacher
        else:
            session = db.get(TeacherSession, sender.id)
            conversation = get_teacher_conversation(db, sender, session.conversation_id) if session else None
            if not conversation:
                await message.answer(
                    "Сначала выберите ученика в панели учителя.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="Открыть панель учителя", callback_data="ui:home")
                    ]]),
                )
                return
            recipient = conversation.assignment.student

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

        pending_before_reply = (
            pending_student_messages(conversation_messages(db, conversation.id))
            if sender.role == "teacher" else []
        )
        row = persist_message(db, conversation.id, sender, message, "pending")
        await archive_telegram_media(bot, message, row)
        if not recipient.telegram_id or not recipient.active:
            row.delivery_status = "failed"
            db.commit()
            if sender.role == "teacher":
                await message.answer("Не удалось доставить сообщение: аккаунт ученика не подключён.")
            else:
                await message.answer("Не удалось отправить сообщение. Попробуйте позже.")
            return
        try:
            copied = await bot.copy_message(
                chat_id=recipient.telegram_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            row.destination_message_id = copied.message_id
            row.delivery_status = "delivered"
            db.commit()

            if sender.role == "student":
                # The student sees their own outgoing message in Telegram.
                # The teacher receives the copied message and an unread inbox.
                try:
                    await update_teacher_panel(bot, db, recipient)
                except Exception:
                    logger.exception("Could not refresh teacher inbox for conversation_id=%s", conversation.id)
            else:
                # A successful teacher reply closes the pending batch.
                pending_rows = pending_before_reply
                for pending in pending_rows:
                    if pending.destination_message_id:
                        try:
                            await bot.delete_message(
                                chat_id=sender.telegram_id,
                                message_id=pending.destination_message_id,
                            )
                        except Exception:
                            logger.info("Could not remove handled student message %s from teacher inbox", pending.id)
                now = datetime.now(timezone.utc).isoformat()
                for pending in pending_rows:
                    metadata = json.loads(pending.metadata_json or "{}")
                    metadata["teacher_read_at"] = now
                    pending.metadata_json = json.dumps(metadata, ensure_ascii=False)
                db.commit()
                clear_teacher_session(db, sender)
                try:
                    await update_teacher_panel(bot, db, sender)
                except Exception:
                    logger.exception("Could not refresh teacher inbox after reply for conversation_id=%s", conversation.id)
        except Exception:
            row.delivery_status = "failed"
            db.commit()
            logger.exception("Could not forward Telegram message for conversation_id=%s", conversation.id)
            if sender.role == "teacher":
                await message.answer("Не удалось доставить сообщение. Попробуйте ещё раз позже.")
            else:
                await message.answer("Не удалось отправить сообщение. Попробуйте ещё раз позже.")

def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
