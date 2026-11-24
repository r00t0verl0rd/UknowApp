"""Входящие учителя, клавиатура Telegram и управление постоянной панелью диалогов."""

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Assignment,
    Conversation,
    Message,
    TeacherPanel,
    TeacherSession,
    User,
)
from app.modules.communication.accounts import get_messenger_account
from app.modules.communication.contracts import MessengerError, MessengerPlatform
from app.modules.messaging.inbound import (
    InboundUiResult,
    clear_teacher_session,
    get_teacher_conversation,
    mark_visible_messages_read_by_teacher,
    recent_conversation_messages,
    set_teacher_session,
)

logger = logging.getLogger(__name__)


TEACHER_PAGE_SIZE = 6
TEACHER_KEYBOARD_VERSION = 8
TEACHER_BACK_LABEL = "К списку учеников"
TEACHER_REFRESH_LABEL = "↻ Обновить"
TEACHER_PREVIOUS_PAGE_LABEL = "← Предыдущая"
TEACHER_NEXT_PAGE_LABEL = "Следующая →"


def message_preview(row: Message | None) -> str:
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
            Conversation.status == "active",
        )
        .join(Conversation, Assignment.id == Conversation.assignment_id)
        .order_by(Assignment.created_at.desc()),
    ).all()
    conversation_ids = [item.conversation.id for item in assignments]
    latest_by_conversation: dict[int, Message | None] = {}
    unread_by_conversation: dict[int, list[Message]] = defaultdict(list)

    if conversation_ids:
        # Используем индекс, не загружая все сообщения учеников.
        latest_id = (
            select(Message.id)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        last_teacher_id = (
            select(Message.id)
            .where(
                Message.conversation_id == Conversation.id,
                Message.sender_role == "teacher",
                Message.delivery_status != "blocked_contact",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        latest_ids = db.execute(
            select(Conversation.id, latest_id, last_teacher_id)
            .where(Conversation.id.in_(conversation_ids)),
        ).all()
        needed_ids = {
            message_id
            for _, most_recent_id, teacher_reply_id in latest_ids
            for message_id in (most_recent_id, teacher_reply_id)
            if message_id is not None
        }
        messages_by_id = {
            row.id: row
            for row in db.scalars(
                select(Message).where(Message.id.in_(needed_ids)),
            ).all()
        }
        unread_ranges = []
        for conversation_id, most_recent_id, teacher_reply_id in latest_ids:
            latest_by_conversation[conversation_id] = messages_by_id.get(most_recent_id)
            condition = Message.conversation_id == conversation_id
            last_reply = messages_by_id.get(teacher_reply_id)
            if last_reply is not None:
                condition = and_(
                    condition,
                    tuple_(Message.created_at, Message.id)
                    > (last_reply.created_at, last_reply.id),
                )
            unread_ranges.append(condition)

        # Неотвеченные сообщения начинаются после ответа учителя.
        for row in db.scalars(
            select(Message)
            .where(
                or_(*unread_ranges),
                Message.sender_role == "student",
                Message.delivery_status != "blocked_contact",
            )
            .order_by(Message.conversation_id, Message.created_at, Message.id),
        ).all():
            if json.loads(row.metadata_json or "{}").get("teacher_read_at") is None:
                unread_by_conversation[row.conversation_id].append(row)

    items = []
    for assignment in assignments:
        student = assignment.student
        conversation = assignment.conversation
        unread = unread_by_conversation[conversation.id]
        latest = latest_by_conversation.get(conversation.id)
        items.append({
            "student": student,
            "conversation": conversation,
            "unread": unread,
            "unanswered": len(unread),
            "preview": message_preview(unread[-1]) if unread else "",
            "latest": latest,
            "last_at": latest.created_at.isoformat() if latest else assignment.created_at.isoformat(),
        })
    # Показываем всех учеников; непрочитанные идут первыми.
    items.sort(key=lambda item: (item["unanswered"] > 0, item["last_at"]), reverse=True)
    return items

def _teacher_page(items: list[dict], page: int) -> tuple[int, int, list[dict]]:
    total_pages = max(1, (len(items) + TEACHER_PAGE_SIZE - 1) // TEACHER_PAGE_SIZE)
    current_page = max(0, min(page, total_pages - 1))
    start = current_page * TEACHER_PAGE_SIZE
    return total_pages, current_page, items[start:start + TEACHER_PAGE_SIZE]


def _teacher_keyboard(
    visible: list[dict],
    page: int,
    total_pages: int,
    selected_student_name: str | None = None,
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
    selected_student_name: str | None = None,
) -> tuple[str, ReplyKeyboardMarkup, int]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    lines = [
        "<b>▫️ <u>Ваша группа:</u></b>",
        "",
    ]
    if not visible:
        lines.append("Пока нет назначенных учеников.")
    else:
        for item in visible:
            student_name = escape(item["student"].full_name)
            notice = " · " + str(item["unanswered"]) + " новых" if item["unanswered"] else ""
            lines.append("🔸 " + student_name + notice)
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
        visible, page, total_pages, selected_student_name,
    ), page


def teacher_keyboard_actions(
    db: Session,
    teacher: User,
    page: int,
) -> tuple[dict[str, Conversation | None], int, int, set[str]]:
    items = teacher_conversations(db, teacher)
    total_pages, page, visible = _teacher_page(items, page)
    labels_by_conversation = {
        item["conversation"].id: item["student"].full_name.strip()
        for item in items
    }
    actions: dict[str, Conversation | None] = {}
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
    # Дополнительная строка показывает, нужен ли подсчёт.
    rows = recent_conversation_messages(db, conversation.id, limit=13)
    visible_rows = rows[-12:]
    lines = [
        "🔸 " + escape(student.full_name),
        "",
    ]
    if not visible_rows:
        lines.append("История пока пуста.")
    else:
        for row in visible_rows:
            sender_label = (
                student.full_name if row.sender_role == "student"
                else "Администратор" if row.sender_role == "admin"
                else "Вы"
            )
            lines.append(escape(sender_label) + ": " + escape(message_preview(row)))
    if len(rows) > len(visible_rows):
        total_messages = db.scalar(
            select(func.count(Message.id))
            .where(Message.conversation_id == conversation.id),
        )
        lines.insert(1, "Показаны последние " + str(len(visible_rows)) + " из " + str(total_messages) + " сообщений.")
    return "\n".join(lines)[:3900]

async def _update_teacher_panel_locked(
    bot: Bot,
    db: Session,
    teacher: User,
    force_keyboard_refresh: bool = False,
    background_refresh: bool = False,
) -> bool:
    """Обновить панель и клавиатуру только при изменениях."""
    telegram_account = get_messenger_account(db, teacher.id, MessengerPlatform.TELEGRAM)
    if not telegram_account:
        return False
    try:
        telegram_chat_id = int(
            telegram_account.external_chat_id or telegram_account.external_user_id,
        )
    except (TypeError, ValueError):
        logger.warning("Teacher has an invalid Telegram chat destination (teacher_id=%s)", teacher.id)
        return False

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    session = db.get(TeacherSession, teacher.id)
    conversation = get_teacher_conversation(db, teacher, session.conversation_id) if session else None
    selected_student_name = conversation.assignment.student.full_name if conversation else None
    list_text, markup, page = teacher_panel_view(
        db, teacher, page, selected_student_name,
    )
    if panel and panel.page_index != page:
        panel.page_index = page
        db.commit()

    text = teacher_chat_view(db, conversation) if conversation else list_text
    signature = teacher_keyboard_signature(markup)

    if background_refresh:
        # The message already reached the teacher as a native Telegram send.
        # Even with a changed keyboard signature, edits must not post an
        # additional panel message (Telegram would notify twice).
        # Keep the keyboard signature unchanged until the teacher uses it.
        if not panel or panel.chat_id != telegram_chat_id:
            return False
        try:
            await bot.edit_message_text(
                chat_id=panel.chat_id,
                message_id=panel.message_id,
                text=text,
                parse_mode="HTML",
            )
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return True
            logger.warning(
                "Teacher background panel edit failed (teacher_id=%s message_id=%s error_type=%s)",
                teacher.id, panel.message_id, type(exc).__name__,
            )
            return False

    if (
        not force_keyboard_refresh
        and panel
        and panel.keyboard_version >= TEACHER_KEYBOARD_VERSION
        and panel.keyboard_signature == signature
        and panel.chat_id == telegram_chat_id
    ):
        try:
            # Клавиатура привязана к чату, а не к сообщению.
            await bot.edit_message_text(
                chat_id=panel.chat_id,
                message_id=panel.message_id,
                text=text,
                parse_mode="HTML",
            )
            return True
        except TelegramBadRequest as exc:
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
    old_keyboard_version = panel.keyboard_version if panel else None

    # Новая клавиатура заменяет старую без промежуточного удаления.
    sent = await bot.send_message(
        chat_id=telegram_chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML",
    )

    if panel:
        panel.chat_id = telegram_chat_id
        panel.message_id = sent.message_id
        panel.keyboard_version = TEACHER_KEYBOARD_VERSION
        panel.keyboard_signature = signature
        panel.page_index = page
    else:
        db.add(TeacherPanel(
            teacher_id=teacher.id,
            message_id=sent.message_id,
            chat_id=telegram_chat_id,
            keyboard_version=TEACHER_KEYBOARD_VERSION,
            keyboard_signature=signature,
            page_index=page,
        ))
    db.commit()

    if old_chat_id and old_message_id and old_message_id != sent.message_id:
        # Текущая панель использует клавиатуру чата.
        if old_keyboard_version < TEACHER_KEYBOARD_VERSION:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=old_chat_id,
                    message_id=old_message_id,
                    reply_markup=None,
                )
            except TelegramAPIError:
                logger.debug(
                    "Could not remove old inline keyboard (teacher_id=%s message_id=%s)",
                    teacher.id,
                    old_message_id,
                )
        try:
            await bot.delete_message(chat_id=old_chat_id, message_id=old_message_id)
        except TelegramAPIError:
            logger.info(
                "Could not remove the previous teacher panel (teacher_id=%s message_id=%s)",
                teacher.id,
                old_message_id,
            )
    return True


# Обновляем панель последовательно, без гонки обработчиков.
_teacher_panel_locks: dict[int, asyncio.Lock] = {}


async def update_teacher_panel(
    bot: Bot,
    db: Session,
    teacher: User,
    force_keyboard_refresh: bool = False,
    background_refresh: bool = False,
) -> bool:
    lock = _teacher_panel_locks.setdefault(teacher.id, asyncio.Lock())
    async with lock:
        try:
            return await _update_teacher_panel_locked(
                bot, db, teacher, force_keyboard_refresh=force_keyboard_refresh,
                background_refresh=background_refresh,
            )
        except Exception:
            db.rollback()
            raise


async def handle_teacher_keyboard_message(
    db: Session,
    inbound,
    teacher: User,
    gateway,
) -> InboundUiResult:
    """Обработать нажатие кнопки клавиатуры Telegram."""
    body = inbound.text.strip()
    if not body:
        return InboundUiResult(False)

    async def remove_action_message() -> None:
        try:
            await gateway.delete_message(
                inbound.external_chat_id, inbound.external_message_id,
            )
        except MessengerError as exc:
            logger.debug(
                "Could not remove teacher keyboard action (error_type=%s)",
                exc.provider_error_type,
            )

    if body.startswith("Написать · "):
        await remove_action_message()
        return InboundUiResult(True, force_keyboard_refresh=True)

    # Навигация не требует загрузки истории и счётчиков.
    if body in {TEACHER_BACK_LABEL, TEACHER_REFRESH_LABEL}:
        if body == TEACHER_BACK_LABEL:
            clear_teacher_session(db, teacher)
        await remove_action_message()
        return InboundUiResult(True)

    panel = db.get(TeacherPanel, teacher.id)
    page = panel.page_index if panel else 0
    if body in {TEACHER_PREVIOUS_PAGE_LABEL, TEACHER_NEXT_PAGE_LABEL}:
        clear_teacher_session(db, teacher)
        if panel:
            assigned_count = db.scalar(
                select(func.count(Assignment.id))
                .join(Conversation, Assignment.id == Conversation.assignment_id)
                .where(
                    Assignment.teacher_id == teacher.id,
                    Assignment.active.is_(True),
                    Conversation.status == "active",
                ),
            )
            total_pages = max(1, (assigned_count + TEACHER_PAGE_SIZE - 1) // TEACHER_PAGE_SIZE)
            current_page = max(0, min(page, total_pages - 1))
            panel.page_index = (
                max(0, current_page - 1)
                if body == TEACHER_PREVIOUS_PAGE_LABEL
                else min(total_pages - 1, current_page + 1)
            )
            db.commit()
        await remove_action_message()
        return InboundUiResult(True)

    # Обычные ответы не должны пересобирать весь список учеников.
    is_student_label = db.scalar(
        select(User.id)
        .join(Assignment, Assignment.student_id == User.id)
        .join(Conversation, Assignment.id == Conversation.assignment_id)
        .where(
            Assignment.teacher_id == teacher.id,
            Assignment.active.is_(True),
            Conversation.status == "active",
            func.trim(User.full_name) == body,
        )
        .limit(1),
    )
    if is_student_label is None:
        return InboundUiResult(False)

    actions, page, total_pages, legacy_student_labels = teacher_keyboard_actions(
        db, teacher, page,
    )

    if body not in actions and body in legacy_student_labels:
        await remove_action_message()
        return InboundUiResult(True, force_keyboard_refresh=True)

    if body in actions:
        conversation = actions[body]
        if conversation is None:
            await gateway.send_text(
                inbound.external_chat_id,
                "У нескольких учеников одинаковое ФИО. Попросите администратора "
                "различить их в списке пользователей.",
                inbound.external_thread_id,
            )
            await remove_action_message()
            return InboundUiResult(True)
        valid = get_teacher_conversation(db, teacher, conversation.id)
        if valid:
            set_teacher_session(db, teacher, valid)
            mark_visible_messages_read_by_teacher(db, valid)
        else:
            clear_teacher_session(db, teacher)
    else:
        return InboundUiResult(False)

    await remove_action_message()
    return InboundUiResult(True)
