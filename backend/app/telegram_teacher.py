"""Teacher inbox, Reply Keyboard and persistent panel management."""

import asyncio
import hashlib
import json
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import KeyboardButton, Message as TgMessage, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assignment, Conversation, Message, TeacherPanel, TeacherSession, User

logger = logging.getLogger(__name__)


TEACHER_PAGE_SIZE = 6
TEACHER_KEYBOARD_VERSION = 5
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
    """Use only each student's full name as the Reply Keyboard button text."""
    return [item["student"].full_name.strip() for item in items]


def _teacher_keyboard(
    all_items: list[dict],
    visible: list[dict],
    page: int,
    total_pages: int,
) -> ReplyKeyboardMarkup:
    all_labels = _teacher_button_labels(all_items)
    labels_by_conversation = {
        item["conversation"].id: label
        for item, label in zip(all_items, all_labels)
    }
    labels = [
        labels_by_conversation[item["conversation"].id]
        for item in visible
    ]
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
    total_pages, page, visible = _teacher_page(items, page)
    lines = [
        "Учитель (Вы):",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]
    if not visible:
        lines.append("Пока нет назначенных учеников.")
    else:
        for item in visible:
            student_name = item["student"].full_name
            notice = " · " + str(item["unanswered"]) + " новых" if item["unanswered"] else ""
            lines.append("👤 " + student_name + notice)
            for row in item["unread"][-3:]:
                lines.append("   " + message_preview(row))
            if item["unanswered"] > 3:
                lines.append("   …ещё " + str(item["unanswered"] - 3) + " сообщений")
            lines.append("")
        if total_pages > 1:
            lines.append("Страница " + str(page + 1) + " из " + str(total_pages) + ".")
    return "\n".join(lines), _teacher_keyboard(items, visible, page, total_pages), page


def teacher_keyboard_actions(
    db: Session,
    teacher: User,
    page: int,
) -> tuple[dict[str, Optional[Conversation]], int, int]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    all_labels = _teacher_button_labels(items)
    labels_by_conversation = {
        item["conversation"].id: label
        for item, label in zip(items, all_labels)
    }
    actions: dict[str, Optional[Conversation]] = {}
    for item in visible:
        label = labels_by_conversation[item["conversation"].id]
        if label in actions:
            actions[label] = None
        else:
            actions[label] = item["conversation"]
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
    visible_rows = rows[-12:]
    lines = [
        "💬 " + student.full_name,
        "",
    ]
    if not visible_rows:
        lines.append("История пока пуста.")
    else:
        for row in visible_rows:
            sender_label = "Ученик" if row.sender_role == "student" else "Вы"
            lines.append(sender_label + ": " + message_preview(row))
    if len(rows) > len(visible_rows):
        lines.insert(1, "Показаны последние " + str(len(visible_rows)) + " из " + str(len(rows)) + " сообщений.")
    return "\n".join(lines)[:3900]


async def _update_teacher_panel_locked(
    bot: Bot,
    db: Session,
    teacher: User,
    force_keyboard_refresh: bool = False,
) -> bool:
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
        not force_keyboard_refresh
        and panel
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

    # Explicitly clear the previous chat-level keyboard on /start and /menu.
    # A fresh ReplyKeyboardMarkup is then sent, so Telegram clients cannot keep
    # rendering cached buttons from an earlier version of the bot.
    reset_message = None
    if force_keyboard_refresh:
        try:
            reset_message = await bot.send_message(
                chat_id=teacher.telegram_id,
                text="Обновляю список учеников…",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            logger.warning(
                "Could not remove the previous teacher keyboard (teacher_id=%s)",
                teacher.id,
                exc_info=True,
            )

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

    if reset_message:
        try:
            await bot.delete_message(
                chat_id=teacher.telegram_id,
                message_id=reset_message.message_id,
            )
        except Exception:
            logger.debug("Could not remove temporary keyboard refresh notice")

    if old_chat_id and old_message_id and old_message_id != sent.message_id:
        # Old panel versions used InlineKeyboardMarkup. Remove those buttons
        # explicitly before attempting to delete the old message.
        try:
            await bot.edit_message_reply_markup(
                chat_id=old_chat_id,
                message_id=old_message_id,
                reply_markup=None,
            )
        except Exception:
            logger.debug(
                "Could not remove old inline keyboard (teacher_id=%s message_id=%s)",
                teacher.id,
                old_message_id,
            )
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


async def update_teacher_panel(
    bot: Bot,
    db: Session,
    teacher: User,
    force_keyboard_refresh: bool = False,
) -> bool:
    lock = _teacher_panel_locks.setdefault(teacher.id, asyncio.Lock())
    async with lock:
        try:
            return await _update_teacher_panel_locked(
                bot, db, teacher, force_keyboard_refresh=force_keyboard_refresh
            )
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
    if not body:
        return False

    # A button from an older keyboard revision may still be cached by a client.
    # Consume it and explicitly replace the chat keyboard instead of forwarding it.
    if body.startswith("Написать · "):
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass
        await update_teacher_panel(bot, db, teacher, force_keyboard_refresh=True)
        return True

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    actions, page, total_pages = teacher_keyboard_actions(db, teacher, page)

    if body in actions:
        conversation = actions[body]
        if conversation is None:
            await message.answer(
                "У нескольких учеников одинаковое ФИО. Попросите администратора "
                "различить их в списке пользователей."
            )
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            except Exception:
                pass
            await update_teacher_panel(bot, db, teacher)
            return True
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
