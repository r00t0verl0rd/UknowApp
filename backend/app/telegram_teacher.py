"""Входящие учителя, клавиатура Telegram и управление постоянной панелью диалогов."""

import asyncio
import hashlib
from collections import defaultdict
from html import escape
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from aiogram.types import (
    KeyboardButton,
    Message as TgMessage,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Assignment, Conversation, Message, TeacherPanel, TeacherSession, User

logger = logging.getLogger(__name__)


TEACHER_PAGE_SIZE = 6
TEACHER_KEYBOARD_VERSION = 8
TEACHER_BACK_LABEL = "К списку учеников"
TEACHER_REFRESH_LABEL = "↻ Обновить"
TEACHER_PREVIOUS_PAGE_LABEL = "← Предыдущая"
TEACHER_NEXT_PAGE_LABEL = "Следующая →"


def message_preview(row: Optional[Message]) -> str:
    if not row:
        return "Сообщений пока нет"
    body = " ".join((row.text or "").strip().split())
    metadata = json.loads(row.metadata_json or "{}")
    media = metadata.get("media") or {}
    media_kind = media.get("kind") or row.content_type
    labels = {
        "voice": "🎤 Голосовое сообщение",
        "video_note": "🎥 Видеокружок",
        "photo": "🖼 Фотография",
        "video": "🎬 Видео",
        "audio": "🎵 Аудио",
        "document": "📎 Документ",
        "sticker": "😊 Стикер",
        "video_sticker": "🎞 Видео-стикер",
        "animated_sticker": "✨ Анимированный стикер",
        "animation": "🎞 Анимация",
        "location": "📍 Геопозиция",
        "contact": "Контакт",
        "poll": "Опрос",
    }
    if row.content_type != "text":
        if media_kind in {"sticker", "video_sticker", "animated_sticker"}:
            label = labels[media_kind]
        else:
            label = media.get("file_name") or labels.get(media_kind, "Вложение: " + (media_kind or "файл"))
        preview = label + (": " + body if body else "")
        return preview if len(preview) <= 115 else preview[:112] + "…"
    if body:
        return body if len(body) <= 115 else body[:112] + "…"
    return "Сообщение"


def conversation_messages(db: Session, conversation_id: int) -> list[Message]:
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()


def unanswered_student_messages(rows: list[Message]) -> list[Message]:
    """Return delivered student messages that have not yet received a teacher reply."""
    last_teacher_index = -1
    for index, row in enumerate(rows):
        if row.sender_role == "teacher" and row.delivery_status == "delivered":
            last_teacher_index = index

    return [
        row
        for index, row in enumerate(rows)
        if (
            index > last_teacher_index
            and row.sender_role == "student"
            and row.delivery_status == "delivered"
        )
    ]


def pending_student_messages(rows: list[Message]) -> list[Message]:
    """Return unanswered student messages the teacher has not opened yet."""
    return [
        row
        for row in unanswered_student_messages(rows)
        if json.loads(row.metadata_json or "{}").get("teacher_read_at") is None
    ]


def mark_messages_read_by_teacher(
    db: Session,
    messages: list[Message],
) -> None:
    """Persist teacher read state for messages opened in the panel or Telegram bot."""
    if not messages:
        return

    now = datetime.now(timezone.utc).isoformat()
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
    db: Session,
    conversation: Conversation,
) -> None:
    """Mark the messages currently shown in the teacher's chat as read."""
    rows = conversation_messages(db, conversation.id)
    visible_rows = rows[-12:]
    # Opening a conversation marks every delivered student message actually
    # visible in the transcript as read, even when a teacher reply is older
    # than the 12-message preview window.
    mark_messages_read_by_teacher(
        db,
        [
            row for row in visible_rows
            if row.sender_role == "student" and row.delivery_status == "delivered"
        ],
    )


def teacher_conversations(db: Session, teacher: User) -> list[dict]:
    assignments = db.scalars(
        select(Assignment)
        .join(User, Assignment.student_id == User.id)
        .options(
            selectinload(Assignment.student),
            selectinload(Assignment.conversation),
        )
        .where(
            Assignment.teacher_id == teacher.id,
            Assignment.active.is_(True),
            User.active.is_(True),
            Conversation.status == "active",
        )
        .join(Conversation, Assignment.id == Conversation.assignment_id)
        .order_by(Assignment.created_at.desc())
    ).all()
    conversation_ids = [item.conversation.id for item in assignments]
    messages_by_conversation = defaultdict(list)
    if conversation_ids:
        rows = db.scalars(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(Message.conversation_id, Message.created_at, Message.id)
        ).all()
        for row in rows:
            messages_by_conversation[row.conversation_id].append(row)

    items = []
    for assignment in assignments:
        student = assignment.student
        conversation = assignment.conversation
        rows = messages_by_conversation[conversation.id]
        unread = pending_student_messages(rows)
        latest = rows[-1] if rows else None
        items.append({
            "student": student,
            "conversation": conversation,
            "unread": unread,
            "unanswered": len(unread),
            "preview": message_preview(unread[-1]) if unread else "",
            "latest": latest,
            "last_at": latest.created_at.isoformat() if latest else assignment.created_at.isoformat(),
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


def _teacher_keyboard(
    visible: list[dict],
    page: int,
    total_pages: int,
    selected_student_name: Optional[str] = None,
) -> ReplyKeyboardMarkup:
    labels = [item["student"].full_name.strip() for item in visible]
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
        input_field_placeholder=(
            "Написать " + selected_student_name
            if selected_student_name
            else "Сперва выберите ученика"
        )[:64],
    )


def teacher_panel_view(
    db: Session,
    teacher: User,
    page: int = 0,
    selected_student_name: Optional[str] = None,
) -> tuple[str, ReplyKeyboardMarkup, int]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    lines = [
        "<b><u>🎓 Ваша группа:</u></b>",
        "",
    ]
    if not visible:
        lines.append("Пока нет назначенных учеников.")
    else:
        for item in visible:
            student_name = escape(item["student"].full_name)
            notice = " · " + str(item["unanswered"]) + " новых" if item["unanswered"] else ""
            lines.append("🟣 " + student_name + notice)
            for row in item["unread"][-3:]:
                lines.append("   " + escape(message_preview(row)))
            if item["unanswered"] > 3:
                lines.append("   …ещё " + str(item["unanswered"] - 3) + " сообщений")
            latest = item["latest"]
            if latest and (
                not item["unread"]
                or (item["unread"] and latest.id > item["unread"][-1].id and latest.sender_role == "admin")
            ):
                preview = escape(message_preview(latest))
                if latest.sender_role == "admin":
                    preview = "Администратор: " + preview
                lines.append("   " + preview)
            lines.append("")
        if total_pages > 1:
            lines.append("Страница " + str(page + 1) + " из " + str(total_pages) + ".")
    return "\n".join(lines), _teacher_keyboard(
        items, visible, page, total_pages, selected_student_name
    ), page


def teacher_keyboard_actions(
    db: Session,
    teacher: User,
    page: int,
) -> tuple[dict[str, Optional[Conversation]], int, int, set[str]]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    labels_by_conversation = {
        item["conversation"].id: item["student"].full_name.strip()
        for item in items
    }
    actions: dict[str, Optional[Conversation]] = {}
    for item in visible:
        label = labels_by_conversation[item["conversation"].id]
        if label in actions:
            actions[label] = None
        else:
            actions[label] = item["conversation"]
    return actions, page, total_pages, set(labels_by_conversation.values())


def teacher_keyboard_signature(markup: ReplyKeyboardMarkup) -> str:
    layout = [[button.text for button in row] for row in markup.keyboard]
    payload = json.dumps(
        {
            "layout": layout,
            "input_field_placeholder": markup.input_field_placeholder,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def teacher_chat_view(
    db: Session,
    conversation: Conversation,
) -> str:
    student = conversation.assignment.student
    rows = conversation_messages(db, conversation.id)
    visible_rows = rows[-12:]
    lines = [
        "🔸 " + escape(student.full_name),
        "",
    ]
    if not visible_rows:
        lines.append("История пока пуста.")
    else:
        for row in visible_rows:
            sender_label = "Ученик" if row.sender_role == "student" else "Администратор" if row.sender_role == "admin" else "Вы"
            lines.append(sender_label + ": " + escape(message_preview(row)))
    if len(rows) > len(visible_rows):
        lines.insert(1, "Показаны последние " + str(len(visible_rows)) + " из " + str(len(rows)) + " сообщений.")
    return "\n".join(lines)[:3900]


async def _update_teacher_panel_locked(
    bot: Bot,
    db: Session,
    teacher: User,
    force_keyboard_refresh: bool = False,
) -> bool:
    """Update the panel and replace its keyboard only when its content changes."""
    if not teacher.telegram_id:
        return False

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    session = db.get(TeacherSession, teacher.id)
    conversation = get_teacher_conversation(db, teacher, session.conversation_id) if session else None
    selected_student_name = conversation.assignment.student.full_name if conversation else None
    list_text, markup, page = teacher_panel_view(
        db, teacher, page, selected_student_name
    )
    if panel and panel.page_index != page:
        panel.page_index = page
        db.commit()

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
                parse_mode="HTML",
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
                    "Teacher panel edit failed (teacher_id=%s message_id=%s error_type=%s)",
                    teacher.id, panel.message_id, type(exc).__name__,
                )
                return False
            logger.info(
                "Replacing unavailable teacher panel (teacher_id=%s message_id=%s)",
                teacher.id, panel.message_id,
            )

    old_chat_id = panel.chat_id if panel else None
    old_message_id = panel.message_id if panel else None

    # Sending the new markup directly replaces the chat-level reply keyboard.
    # Do not remove it in a separate message: some Telegram clients defer the
    # placeholder redraw until the next user message after a remove/restore pair.
    sent = await bot.send_message(
        chat_id=teacher.telegram_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML",
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
        # Remove any legacy inline buttons, then delete the previous panel.
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
        await asyncio.sleep(0.8)
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
    if not body:
        return False

    # A button from an older keyboard revision may still be cached by a client.
    # Consume it and explicitly replace the chat keyboard instead of forwarding it.
    if body.startswith("Написать · "):
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as exc:
            logger.debug("Could not delete stale teacher keyboard message (error_type=%s)", type(exc).__name__)
        await update_teacher_panel(bot, db, teacher, force_keyboard_refresh=True)
        return True

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    actions, page, total_pages, legacy_student_labels = teacher_keyboard_actions(
        db, teacher, page
    )

    # Older Telegram clients may still display the pre-emoji student buttons.
    # Consume those stale taps and refresh the menu instead of routing the name
    # as an ordinary message to the currently selected student.
    if body not in actions and body in legacy_student_labels:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as exc:
            logger.debug("Could not delete legacy teacher keyboard message (error_type=%s)", type(exc).__name__)
        await update_teacher_panel(bot, db, teacher, force_keyboard_refresh=True)
        return True

    if body in actions:
        conversation = actions[body]
        if conversation is None:
            await message.answer(
                "У нескольких учеников одинаковое ФИО. Попросите администратора "
                "различить их в списке пользователей."
            )
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            except Exception as exc:
                logger.debug("Could not delete ambiguous teacher keyboard message (error_type=%s)", type(exc).__name__)
            await update_teacher_panel(bot, db, teacher)
            return True
        valid = get_teacher_conversation(db, teacher, conversation.id)
        if valid:
            set_teacher_session(db, teacher, valid)
            mark_visible_messages_read_by_teacher(db, valid)
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
