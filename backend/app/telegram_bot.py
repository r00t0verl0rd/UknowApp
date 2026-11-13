import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message as TgMessage,
    ReplyKeyboardMarkup,
)
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
TEACHER_KEYBOARD_VERSION = 2
TEACHER_BACK_LABEL = "← К списку учеников"
TEACHER_REFRESH_LABEL = "↻ Обновить"
TEACHER_PREVIOUS_PAGE_LABEL = "← Предыдущая"
TEACHER_NEXT_PAGE_LABEL = "Следующая →"


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
        items.append({
            "student": student,
            "conversation": conversation,
            "unread": unread,
            "unanswered": len(unread),
            "preview": message_preview(unread[-1]) if unread else "",
            "last_at": unread[-1].created_at.isoformat() if unread else assignment.created_at.isoformat(),
        })
    # Keep all assigned students visible; students with unread messages come first.
    items.sort(key=lambda item: (item["unanswered"] > 0, item["last_at"]), reverse=True)
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


def _teacher_page(items: list[dict], page: int) -> tuple[int, int, list[dict]]:
    total_pages = max(1, (len(items) + TEACHER_PAGE_SIZE - 1) // TEACHER_PAGE_SIZE)
    current_page = max(0, min(page, total_pages - 1))
    start = current_page * TEACHER_PAGE_SIZE
    return total_pages, current_page, items[start:start + TEACHER_PAGE_SIZE]


def _teacher_button_labels(items: list[dict]) -> list[str]:
    name_counts = Counter(item["student"].full_name.strip() for item in items)
    labels = []
    for item in items:
        student = item["student"]
        name = student.full_name.strip()
        prefix = "Написать · "
        needs_id = name_counts[name] > 1 or len(prefix + name) > 64
        suffix = " · #" + str(student.id) if needs_id else ""
        max_name_length = max(1, 64 - len(prefix) - len(suffix))
        labels.append(prefix + name[:max_name_length].rstrip() + suffix)
    return labels


def _teacher_keyboard(visible: list[dict], page: int, total_pages: int) -> ReplyKeyboardMarkup:
    labels = _teacher_button_labels(visible)
    rows = []
    for index in range(0, len(labels), 2):
        row = [KeyboardButton(text=label) for label in labels[index:index + 2]]
        rows.append(row)

    if total_pages > 1:
        navigation = []
        if page > 0:
            navigation.append(KeyboardButton(text=TEACHER_PREVIOUS_PAGE_LABEL))
        if page + 1 < total_pages:
            navigation.append(KeyboardButton(text=TEACHER_NEXT_PAGE_LABEL))
        if navigation:
            rows.append(navigation)

    rows.append([
        KeyboardButton(text=TEACHER_BACK_LABEL),
        KeyboardButton(text=TEACHER_REFRESH_LABEL),
    ])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите ученика или напишите сообщение",
    )


def teacher_panel_view(
    db: Session,
    teacher: User,
    page: int = 0,
) -> tuple[str, ReplyKeyboardMarkup, int]:
    items = teacher_conversations(db, teacher)
    total_unread = sum(item["unanswered"] for item in items)
    total_pages, page, visible = _teacher_page(items, page)
    lines = [
        "👩‍🏫 Панель учителя",
        "Новых сообщений: " + str(total_unread),
        "Выберите ученика на клавиатуре ниже.",
        "",
    ]
    if not visible:
        lines.append("Пока нет назначенных учеников.")
    else:
        for item in visible:
            student_name = item["student"].full_name
            lines.append("👤 " + student_name + " · " + (
                str(item["unanswered"]) + " новых" if item["unanswered"] else "нет новых сообщений"
            ))
            for row in item["unread"][-3:]:
                lines.append("   " + message_preview(row))
            if item["unanswered"] > 3:
                lines.append("   …ещё " + str(item["unanswered"] - 3) + " сообщений")
            lines.append("")
        if total_pages > 1:
            lines.append("Страница " + str(page + 1) + " из " + str(total_pages) + ".")
    return "\n".join(lines), _teacher_keyboard(visible, page, total_pages), page


def teacher_keyboard_actions(
    db: Session,
    teacher: User,
    page: int,
) -> tuple[dict[str, Conversation], int, int]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    labels = _teacher_button_labels(visible)
    actions = {
        label: item["conversation"]
        for label, item in zip(labels, visible)
    }
    return actions, page, total_pages


def teacher_keyboard_signature(markup: ReplyKeyboardMarkup) -> str:
    layout = [[button.text for button in row] for row in markup.keyboard]
    payload = json.dumps(layout, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def teacher_chat_view(
    db: Session,
    conversation: Conversation,
) -> str:
    student = conversation.assignment.student
    rows = conversation_messages(db, conversation.id)
    unread_count = len(pending_student_messages(rows))
    visible_rows = rows[-12:]
    lines = [
        "💬 " + student.full_name,
        "Новых сообщений: " + str(unread_count),
        "Ответы будут отправлены этому ученику.",
        "Выберите другого ученика на клавиатуре или нажмите «" + TEACHER_BACK_LABEL + "».",
        "",
    ]
    if not visible_rows:
        lines.append("История пока пуста.")
    else:
        for row in visible_rows:
            sender_label = "Ученик" if row.sender_role == "student" else "Вы"
            lines.append(sender_label + ": " + message_preview(row))
    if len(rows) > len(visible_rows):
        lines.insert(4, "Показаны последние " + str(len(visible_rows)) + " из " + str(len(rows)) + " сообщений.")
    return "\n".join(lines)[:3900]


async def _update_teacher_panel_locked(bot: Bot, db: Session, teacher: User) -> bool:
    """Edit the teacher panel in place and replace its keyboard only when layout changes."""
    if not teacher.telegram_id:
        return False

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    list_text, markup, page = teacher_panel_view(db, teacher, page)
    if panel and panel.page_index != page:
        panel.page_index = page
        db.commit()

    session = db.get(TeacherSession, teacher.id)
    conversation = get_teacher_conversation(db, teacher, session.conversation_id) if session else None
    text = teacher_chat_view(db, conversation) if conversation else list_text
    signature = teacher_keyboard_signature(markup)

    if (
        panel
        and panel.keyboard_version >= TEACHER_KEYBOARD_VERSION
        and panel.keyboard_signature == signature
    ):
        try:
            # Reply keyboards belong to the chat, not to an editable message.
            # The persistent keyboard remains active while only the panel text changes.
            await bot.edit_message_text(
                chat_id=panel.chat_id,
                message_id=panel.message_id,
                text=text,
            )
            return True
        except Exception as exc:
            error_text = str(exc).lower()
            if "message is not modified" in error_text:
                return True
            permanent_panel_errors = (
                "message to edit not found",
                "message can't be edited",
                "message_id_invalid",
                "chat not found",
            )
            if not any(marker in error_text for marker in permanent_panel_errors):
                logger.warning(
                    "Teacher panel edit failed; keeping its stored message id "
                    "(teacher_id=%s message_id=%s): %s",
                    teacher.id, panel.message_id, exc,
                )
                return False
            logger.info(
                "Replacing unavailable teacher panel (teacher_id=%s message_id=%s)",
                teacher.id, panel.message_id,
            )

    old_chat_id = panel.chat_id if panel else None
    old_message_id = panel.message_id if panel else None
    sent = await bot.send_message(
        chat_id=teacher.telegram_id,
        text=text,
        reply_markup=markup,
    )

    if panel:
        panel.chat_id = teacher.telegram_id
        panel.message_id = sent.message_id
        panel.keyboard_version = TEACHER_KEYBOARD_VERSION
        panel.keyboard_signature = signature
        panel.page_index = page
    else:
        db.add(TeacherPanel(
            teacher_id=teacher.id,
            message_id=sent.message_id,
            chat_id=teacher.telegram_id,
            keyboard_version=TEACHER_KEYBOARD_VERSION,
            keyboard_signature=signature,
            page_index=page,
        ))
    db.commit()

    if old_chat_id and old_message_id and old_message_id != sent.message_id:
        try:
            await bot.delete_message(chat_id=old_chat_id, message_id=old_message_id)
        except Exception:
            logger.info(
                "Could not remove the previous teacher panel (teacher_id=%s message_id=%s)",
                teacher.id,
                old_message_id,
            )
    return True


# Telegram may process several updates for the same teacher concurrently.
# Serialize panel edits/creation so two handlers cannot create competing panels.
_teacher_panel_locks: dict[int, asyncio.Lock] = {}


async def update_teacher_panel(bot: Bot, db: Session, teacher: User) -> bool:
    lock = _teacher_panel_locks.setdefault(teacher.id, asyncio.Lock())
    async with lock:
        try:
            return await _update_teacher_panel_locked(bot, db, teacher)
        except Exception:
            db.rollback()
            raise


async def handle_teacher_keyboard_message(
    message: TgMessage,
    bot: Bot,
    db: Session,
    teacher: User,
) -> bool:
    body = (message.text or "").strip()
    keyboard_controls = {
        TEACHER_BACK_LABEL,
        TEACHER_REFRESH_LABEL,
        TEACHER_PREVIOUS_PAGE_LABEL,
        TEACHER_NEXT_PAGE_LABEL,
    }
    if not body or (body not in keyboard_controls and not body.startswith("Написать · ")):
        return False

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    actions, page, total_pages = teacher_keyboard_actions(db, teacher, page)

    if body in actions:
        conversation = actions[body]
        valid = get_teacher_conversation(db, teacher, conversation.id)
        if valid:
            set_teacher_session(db, teacher, valid)
        else:
            clear_teacher_session(db, teacher)
    elif body == TEACHER_BACK_LABEL:
        clear_teacher_session(db, teacher)
    elif body == TEACHER_REFRESH_LABEL:
        pass
    elif body == TEACHER_PREVIOUS_PAGE_LABEL:
        clear_teacher_session(db, teacher)
        if panel:
            panel.page_index = max(0, page - 1)
            db.commit()
    elif body == TEACHER_NEXT_PAGE_LABEL:
        clear_teacher_session(db, teacher)
        if panel:
            panel.page_index = min(total_pages - 1, page + 1)
            db.commit()
    elif body.startswith("Написать · "):
        # A stale button from a previous keyboard layout must never be forwarded
        # as a message to whichever student happened to be selected earlier.
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass
        await update_teacher_panel(bot, db, teacher)
        return True
    else:
        return False

    try:
        # Reply-keyboard taps arrive as ordinary user messages; remove them so
        # the teacher's chat stays focused on the persistent panel.
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception:
        logger.debug("Could not remove teacher keyboard selection message_id=%s", message.message_id)

    await update_teacher_panel(bot, db, teacher)
    return True



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
            try:
                # Open the persistent teacher panel directly; do not send a
                # separate confirmation message after /start.
                await update_teacher_panel(bot, db, user)
            except Exception:
                logger.exception("Could not open teacher panel from /start for user_id=%s", user.id)
            return

        if user.role == "student":
            conversation = current_student_conversation(db, user.id)
            if conversation and conversation.status == "active":
                teacher = conversation.assignment.teacher
                await message.answer(
                    "Вы подключены к UknowApp.\n"
                    "Ваш учитель: " + teacher.full_name + ".\n\n"
                    "Можете отправить ему сообщение прямо сюда."
                )
            else:
                await message.answer(
                    "Аккаунт подключён, но активный учитель пока не назначен. "
                    "Обратитесь к администратору."
                )
            return

        if user.role == "admin":
            await message.answer("Аккаунт администратора подключён. Управление доступно через веб-панель.")


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
async def handle_panel_callback(callback: CallbackQuery, bot: Bot):
    if not callback.from_user or not callback.data:
        return
    with SessionLocal() as db:
        user = get_linked_user(db, callback.from_user.id)
        if not user or user.role != "teacher":
            await callback.answer("Панель доступна только подключённому учителю.", show_alert=True)
            return

        parts = callback.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        try:
            if action == "home":
                clear_teacher_session(db, user)
            elif action == "teacher" and len(parts) > 3 and parts[2] == "page":
                page = max(0, int(parts[3]))
                panel = db.get(TeacherPanel, user.id)
                if panel:
                    panel.page_index = page
                    db.commit()
                clear_teacher_session(db, user)
            elif action == "chat" and len(parts) >= 3:
                conversation = get_teacher_conversation(db, user, int(parts[2]))
                if not conversation:
                    await callback.answer("Ученик больше не назначен вам.", show_alert=True)
                    return
                set_teacher_session(db, user, conversation)
            elif action == "reply" and len(parts) > 2:
                conversation = get_teacher_conversation(db, user, int(parts[2]))
                if not conversation:
                    await callback.answer("Эта переписка больше недоступна.", show_alert=True)
                    return
                set_teacher_session(db, user, conversation)
            else:
                await callback.answer("Старая кнопка больше не действует. Панель обновлена.")
                await update_teacher_panel(bot, db, user)
                return
        except (ValueError, IndexError):
            await callback.answer("Некорректная команда.", show_alert=True)
            return

        await callback.answer()
        await update_teacher_panel(bot, db, user)


@router.callback_query(F.data.startswith("reply:"))
async def choose_conversation(callback: CallbackQuery, bot: Bot):
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
        await callback.answer()
        await update_teacher_panel(bot, db, teacher)


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

        if sender.role == "teacher" and await handle_teacher_keyboard_message(message, bot, db, sender):
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
                await update_teacher_panel(bot, db, sender)
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
            if sender.role == "student":
                # Student messages are rendered from SQLite inside the single
                # persistent teacher panel; do not create extra Telegram messages.
                row.delivery_status = "delivered"
                db.commit()
                try:
                    await update_teacher_panel(bot, db, recipient)
                except Exception:
                    logger.exception("Could not refresh teacher panel for conversation_id=%s", conversation.id)
            else:
                copied = await bot.copy_message(
                    chat_id=recipient.telegram_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
                row.destination_message_id = copied.message_id
                row.delivery_status = "delivered"
                db.commit()

                # Keep the teacher's bot chat focused on the persistent panel.
                try:
                    await bot.delete_message(chat_id=sender.telegram_id, message_id=message.message_id)
                except Exception:
                    logger.info("Could not remove teacher's sent message from the bot chat")

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
                # Keep the selected conversation active after replying.
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
