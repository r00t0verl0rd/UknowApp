"""Telegram commands and message routing."""

import json
import logging
import re
import time
from collections import deque

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message as TgMessage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal
from .media_storage import archive_telegram_media
from .models import StudentTelegramGroup, TeacherPanel, TeacherSession
from .telegram_common import (
    CONNECTION_CODE_RE,
    claim_connection_code,
    contact_would_be_exposed,
    current_student_conversation,
    get_linked_user,
    persist_message,
)
from .telegram_teacher import (
    clear_teacher_session,
    conversation_messages,
    get_teacher_conversation,
    handle_teacher_keyboard_message,
    mark_messages_read_by_teacher,
    mark_visible_messages_read_by_teacher,
    set_teacher_session,
    unanswered_student_messages,
    update_teacher_panel,
)

logger = logging.getLogger(__name__)
router = Router()

_CONNECTION_CODE_WINDOW = 15 * 60
_CONNECTION_CODE_LIMIT = 5
_connection_code_attempts: dict[int, deque[float]] = {}
_UNLINKED_MESSAGE_WINDOW = 60
_UNLINKED_MESSAGE_LIMIT = 12
_unlinked_message_attempts: dict[int, deque[float]] = {}
_BIND_GROUP_WINDOW = 60
_BIND_GROUP_LIMIT = 5
_bind_group_attempts: dict[tuple[int, int], deque[float]] = {}


def _connection_code_attempt_allowed(telegram_id: int) -> bool:
    now = time.monotonic()
    attempts = _connection_code_attempts.setdefault(telegram_id, deque())
    while attempts and now - attempts[0] >= _CONNECTION_CODE_WINDOW:
        attempts.popleft()
    return len(attempts) < _CONNECTION_CODE_LIMIT


def _record_connection_code_attempt(telegram_id: int) -> None:
    now = time.monotonic()
    attempts = _connection_code_attempts.setdefault(telegram_id, deque())
    while attempts and now - attempts[0] >= _CONNECTION_CODE_WINDOW:
        attempts.popleft()
    attempts.append(now)
    if len(_connection_code_attempts) > 10_000:
        for user_id, bucket in list(_connection_code_attempts.items()):
            while bucket and now - bucket[0] >= _CONNECTION_CODE_WINDOW:
                bucket.popleft()
            if not bucket:
                _connection_code_attempts.pop(user_id, None)


def _unlinked_message_allowed(telegram_id: int) -> bool:
    now = time.monotonic()
    attempts = _unlinked_message_attempts.setdefault(telegram_id, deque())
    while attempts and now - attempts[0] >= _UNLINKED_MESSAGE_WINDOW:
        attempts.popleft()
    if len(attempts) >= _UNLINKED_MESSAGE_LIMIT:
        return False
    attempts.append(now)
    if len(_unlinked_message_attempts) > 10_000:
        for user_id, bucket in list(_unlinked_message_attempts.items()):
            while bucket and now - bucket[0] >= _UNLINKED_MESSAGE_WINDOW:
                bucket.popleft()
            if not bucket:
                _unlinked_message_attempts.pop(user_id, None)
    return True


def _bind_group_attempt_allowed(telegram_id: int, chat_id: int) -> bool:
    now = time.monotonic()
    key = (telegram_id, chat_id)
    attempts = _bind_group_attempts.setdefault(key, deque())
    while attempts and now - attempts[0] >= _BIND_GROUP_WINDOW:
        attempts.popleft()
    if len(attempts) >= _BIND_GROUP_LIMIT:
        return False
    attempts.append(now)
    if len(_bind_group_attempts) > 10_000:
        for cached_key, bucket in list(_bind_group_attempts.items()):
            while bucket and now - bucket[0] >= _BIND_GROUP_WINDOW:
                bucket.popleft()
            if not bucket:
                _bind_group_attempts.pop(cached_key, None)
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
                await update_teacher_panel(bot, db, user, force_keyboard_refresh=True)
            except Exception as exc:
                logger.warning(
                    "Could not open teacher panel (user_id=%s error_type=%s)",
                    user.id,
                    type(exc).__name__,
                )
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
            await update_teacher_panel(bot, db, user, force_keyboard_refresh=True)


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
        opened_conversation = None
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
                opened_conversation = conversation
            elif action == "reply" and len(parts) > 2:
                conversation = get_teacher_conversation(db, user, int(parts[2]))
                if not conversation:
                    await callback.answer("Эта переписка больше недоступна.", show_alert=True)
                    return
                set_teacher_session(db, user, conversation)
                opened_conversation = conversation
            else:
                await callback.answer("Старая кнопка больше не действует. Панель обновлена.")
                await update_teacher_panel(bot, db, user)
                return
        except (ValueError, IndexError):
            await callback.answer("Некорректная команда.", show_alert=True)
            return

        await callback.answer()
        if opened_conversation:
            await mark_visible_messages_read_by_teacher(bot, db, opened_conversation)
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
        await mark_visible_messages_read_by_teacher(bot, db, conversation)
        await update_teacher_panel(bot, db, teacher)


@router.message(Command("bind_group"))
async def bind_student_group(message: TgMessage, bot: Bot):
    """Bind the current Telegram forum topic to the linked student account."""
    if not message.from_user:
        return
    if message.chat.type != "supergroup" or not message.chat.is_forum or not message.message_thread_id:
        await message.answer(
            "Откройте тему «🤖 Бот» в супергруппе с включёнными темами и отправьте /bind_group."
        )
        return

    telegram_id = message.from_user.id
    if not _bind_group_attempt_allowed(telegram_id, message.chat.id):
        await message.answer("Слишком часто. Повторите привязку через минуту.")
        return

    # Verify the sender before making any Telegram API calls. Unlinked users
    # must not be able to use /bind_group to generate requests from our bot.
    with SessionLocal() as db:
        student = get_linked_user(db, telegram_id)
        if not student or student.role != "student":
            await message.answer("Привязать тему может только подключённый аккаунт ученика.")
            return
        conversation = current_student_conversation(db, student.id)
        if not conversation or conversation.status != "active":
            await message.answer("Сначала попросите администратора назначить вам активного учителя.")
            return

    # Telegram may deliver /bind_group while hiding ordinary group messages
    # from bots with Group Privacy Mode enabled. Verify that this bot can
    # actually receive the student's regular messages before binding the topic.
    try:
        bot_info = await bot.get_me()
        can_read_group_messages = bool(
            getattr(bot_info, "can_read_all_group_messages", False)
        )
        bot_member_status = "not_checked"
        if not can_read_group_messages:
            bot_member = await bot.get_chat_member(
                chat_id=message.chat.id,
                user_id=bot_info.id,
            )
            bot_member_status = str(bot_member.status)
        logger.warning(
            "TELEGRAM_GROUP_ACCESS_CHECK chat_id=%s thread_id=%s privacy_disabled=%s bot_member_status=%s",
            message.chat.id,
            message.message_thread_id,
            can_read_group_messages,
            bot_member_status,
        )
        if not can_read_group_messages and bot_member_status not in {"administrator", "creator"}:
            await message.answer(
                "⚠️ Тема не привязана: Telegram сейчас не передаёт боту обычные сообщения из группы.\n\n"
                "Добавьте бота в администраторы этой группы либо отключите Group Privacy "
                "в @BotFather (Bot Settings → Group Privacy), затем удалите бота из группы "
                "и добавьте снова. После этого повторите /bind_group."
            )
            return
    except Exception as exc:
        logger.warning(
            "Could not verify Telegram group message access (error_type=%s)",
            type(exc).__name__,
        )
        await message.answer(
            "Telegram не подтвердил, что бот получает обычные сообщения этой группы. "
            "Для надёжной работы сделайте бота администратором группы либо отключите "
            "Group Privacy в @BotFather, удалите бота из группы и добавьте снова. "
            "Затем повторите /bind_group."
        )
        return

    with SessionLocal() as db:
        student = get_linked_user(db, message.from_user.id)
        if not student or student.role != "student":
            await message.answer("Привязать тему может только подключённый аккаунт ученика.")
            return
        conversation = current_student_conversation(db, student.id)
        if not conversation or conversation.status != "active":
            await message.answer("Сначала попросите администратора назначить вам активного учителя.")
            return

        occupied = db.scalar(
            select(StudentTelegramGroup).where(
                StudentTelegramGroup.chat_id == message.chat.id,
                StudentTelegramGroup.thread_id == message.message_thread_id,
            )
        )
        if occupied and occupied.student_id != student.id:
            await message.answer("Эта тема уже привязана к другому ученику.")
            return

        binding = db.get(StudentTelegramGroup, student.id)
        if binding is None:
            binding = StudentTelegramGroup(
                student_id=student.id,
                chat_id=message.chat.id,
                thread_id=message.message_thread_id,
                group_title=message.chat.title,
            )
            db.add(binding)
        else:
            binding.chat_id = message.chat.id
            binding.thread_id = message.message_thread_id
            binding.group_title = message.chat.title
        db.commit()

    await message.answer(
        "✅ Тема привязана к вашему аккаунту UknowApp.\n"
        "Сообщения из этой темы и личного чата с ботом попадут в одну переписку учителя. "
        "Ответ преподавателя появится в канале последнего сообщения."
    )


@router.message()
async def route_message(message: TgMessage, bot: Bot):
    sender_chat = message.sender_chat
    logger.debug(
        "TELEGRAM_UPDATE_RECEIVED telegram_id=%s sender_chat_id=%s chat_type=%s chat_id=%s "
         "thread_id=%s content_type=%s text_length=%s",
        message.from_user.id if message.from_user else None,
        sender_chat.id if sender_chat else None,
        message.chat.type,
        message.chat.id,
        message.message_thread_id,
        message.content_type,
        len(message.text or message.caption or ""),
    )

    with SessionLocal() as db:
        sender = get_linked_user(db, message.from_user.id) if message.from_user else None
        group_binding = None

        if message.chat.type in {"group", "supergroup"}:
            if not message.message_thread_id:
                logger.info(
                    "Ignoring group message outside a bound forum topic: chat_id=%s message_id=%s",
                    message.chat.id,
                    message.message_id,
                )
                return

            # The student's Telegram ID is the primary identity. If this
            # student has not bound a topic yet, bind the first forum topic
            # where they send a message, provided it is not already owned by
            # another student. This replaces the manual /bind_group step.
            if sender and sender.role == "student":
                group_binding = db.scalar(
                    select(StudentTelegramGroup).where(
                        StudentTelegramGroup.chat_id == message.chat.id,
                        StudentTelegramGroup.thread_id == message.message_thread_id,
                        StudentTelegramGroup.student_id == sender.id,
                    )
                )

                if not group_binding and message.chat.is_forum:
                    existing_student_binding = db.get(StudentTelegramGroup, sender.id)
                    occupied_topic = db.scalar(
                        select(StudentTelegramGroup).where(
                            StudentTelegramGroup.chat_id == message.chat.id,
                            StudentTelegramGroup.thread_id == message.message_thread_id,
                        )
                    )
                    active_conversation = current_student_conversation(db, sender.id)

                    if (
                        existing_student_binding is None
                        and occupied_topic is None
                        and active_conversation
                        and active_conversation.status == "active"
                    ):
                        group_binding = StudentTelegramGroup(
                            student_id=sender.id,
                            chat_id=message.chat.id,
                            thread_id=message.message_thread_id,
                            group_title=message.chat.title,
                        )
                        db.add(group_binding)
                        try:
                            db.commit()
                            logger.warning(
                                "TELEGRAM_GROUP_AUTO_BOUND student_id=%s telegram_id=%s "
                                "chat_id=%s thread_id=%s",
                                sender.id,
                                message.from_user.id,
                                message.chat.id,
                                message.message_thread_id,
                            )
                        except IntegrityError:
                            # Another update may have attempted the same first-time
                            # binding concurrently. Re-read the row instead of losing
                            # the student's first message to a uniqueness race.
                            db.rollback()
                            group_binding = db.scalar(
                                select(StudentTelegramGroup).where(
                                    StudentTelegramGroup.chat_id == message.chat.id,
                                    StudentTelegramGroup.thread_id == message.message_thread_id,
                                    StudentTelegramGroup.student_id == sender.id,
                                )
                            )
                            if not group_binding:
                                logger.exception(
                                    "TELEGRAM_GROUP_AUTO_BIND_CONFLICT student_id=%s "
                                    "chat_id=%s thread_id=%s",
                                    sender.id,
                                    message.chat.id,
                                    message.message_thread_id,
                                )
                    elif occupied_topic and occupied_topic.student_id != sender.id:
                        logger.warning(
                            "TELEGRAM_GROUP_AUTO_BIND_DENIED topic_already_bound "
                            "student_id=%s owner_student_id=%s chat_id=%s thread_id=%s",
                            sender.id,
                            occupied_topic.student_id,
                            message.chat.id,
                            message.message_thread_id,
                        )
                    elif existing_student_binding:
                        logger.info(
                            "Student already has a forum binding; automatic rebind skipped "
                            "(student_id=%s chat_id=%s thread_id=%s)",
                            sender.id,
                            message.chat.id,
                            message.message_thread_id,
                        )

            # Anonymous group posts have no verified Telegram user identity.
            # They must not impersonate the student assigned to this topic.
            if not sender or sender.role != "student" or not group_binding:
                logger.warning(
                    "TELEGRAM_GROUP_MESSAGE_IGNORED telegram_id=%s sender_chat_id=%s "
                    "chat_id=%s thread_id=%s has_from_user=%s",
                    message.from_user.id if message.from_user else None,
                    sender_chat.id if sender_chat else None,
                    message.chat.id,
                    message.message_thread_id,
                    bool(message.from_user),
                )
                return
            # The forum topic is an additional input channel for the student.
            # It uses the same persistence, moderation and teacher-inbox path as DM.
        elif not sender and not message.from_user:
            # A private message without a Telegram user identity cannot be
            # linked to an account. In a private chat, normal user messages
            # still continue to the activation-code flow below.
            logger.warning(
                "TELEGRAM_MESSAGE_IGNORED_NO_LINKED_USER chat_id=%s sender_chat_id=%s",
                message.chat.id,
                sender_chat.id if sender_chat else None,
            )
            return
        if not sender:
            if message.from_user and not _unlinked_message_allowed(message.from_user.id):
                return
            text = (message.text or "").strip()
            normalized = re.sub(r"[\s-]", "", text).upper()
            if CONNECTION_CODE_RE.fullmatch(normalized):
                telegram_id = message.from_user.id
                if not _connection_code_attempt_allowed(telegram_id):
                    await message.answer(
                        "Слишком много попыток подключения. Попробуйте снова через 15 минут."
                    )
                    return
                try:
                    linked_user, result = claim_connection_code(db, normalized, telegram_id)
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
                    telegram_id,
                    result,
                )
                if result == "ok" and linked_user:
                    _connection_code_attempts.pop(telegram_id, None)
                    await message.answer(
                        "✅ Telegram подключён к аккаунту «" + linked_user.full_name + "»."
                    )
                    if linked_user.role == "teacher":
                        await update_teacher_panel(bot, db, linked_user)
                elif result == "expired":
                    _record_connection_code_attempt(telegram_id)
                    await message.answer("Срок действия кода истёк. Попросите администратора создать новый код.")
                elif result == "used":
                    _record_connection_code_attempt(telegram_id)
                    await message.answer("Этот код уже использован. Попросите администратора создать новый.")
                elif result == "telegram_already_linked":
                    _record_connection_code_attempt(telegram_id)
                    await message.answer("Этот Telegram-аккаунт уже привязан к другому пользователю UknowApp.")
                elif result == "account_already_linked":
                    _record_connection_code_attempt(telegram_id)
                    await message.answer("К аккаунту уже привязан другой Telegram. Обратитесь к администратору.")
                elif result == "inactive":
                    _record_connection_code_attempt(telegram_id)
                    await message.answer("Этот аккаунт UknowApp отключён. Обратитесь к администратору.")
                else:
                    _record_connection_code_attempt(telegram_id)
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

        unanswered_before_reply = (
            unanswered_student_messages(conversation_messages(db, conversation.id))
            if sender.role == "teacher" else []
        )
        if sender.role == "teacher":
            await mark_visible_messages_read_by_teacher(bot, db, conversation)
        row = persist_message(db, conversation.id, sender, message, "pending")
        metadata = json.loads(row.metadata_json or "{}")
        metadata["source_mode"] = "group_topic" if group_binding else "private"
        metadata["source_chat_id"] = message.chat.id
        metadata["source_thread_id"] = message.message_thread_id if group_binding else None
        row.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
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
                # Keep text in the persistent conversation panel, and copy each
                # recognized attachment into the teacher's private bot chat.
                # copy_message preserves the original Telegram media type and caption,
                # including photos, videos, voice notes, audio, documents, stickers,
                # animations and video notes.
                attachment_metadata = json.loads(row.metadata_json or "{}")
                if attachment_metadata.get("media"):
                    original_caption = (message.caption or "").strip()
                    label_caption = "📎 От ученика: " + sender.full_name
                    if original_caption:
                        label_caption += "\n" + original_caption
                    try:
                        copied = await bot.copy_message(
                            chat_id=recipient.telegram_id,
                            from_chat_id=message.chat.id,
                            message_id=message.message_id,
                            caption=label_caption[:1024],
                        )
                    except Exception:
                        # Some Telegram message types (for example stickers) do not
                        # accept captions. In that case send a clearly paired label.
                        notice = await bot.send_message(
                            chat_id=recipient.telegram_id,
                            text="📎 Вложение от ученика: " + sender.full_name,
                        )
                        copied = await bot.copy_message(
                            chat_id=recipient.telegram_id,
                            from_chat_id=message.chat.id,
                            message_id=message.message_id,
                        )
                        attachment_metadata["teacher_inbox_notice_message_id"] = notice.message_id

                    attachment_metadata["teacher_inbox_media_message_id"] = copied.message_id
                    row.metadata_json = json.dumps(attachment_metadata, ensure_ascii=False)

                row.delivery_status = "delivered"
                db.commit()
                if sender.role == "student":
                    teacher_session = db.get(TeacherSession, recipient.id)
                    if teacher_session and teacher_session.conversation_id != conversation.id:
                        # A new message from another student returns the teacher to
                        # the grouped inbox so a different student's attachment or
                        # text never appears to belong to the currently open chat.
                        clear_teacher_session(db, recipient)
                try:
                    await update_teacher_panel(bot, db, recipient)
                except Exception as exc:
                    logger.warning("Could not refresh teacher panel (error_type=%s)", type(exc).__name__)
            else:
                # Reply in the same channel where the student's latest
                # unanswered message arrived: forum topic or private bot chat.
                destination_chat_id = recipient.telegram_id
                destination_thread_id = None
                for pending in reversed(unanswered_before_reply):
                    pending_metadata = json.loads(pending.metadata_json or "{}")
                    if pending_metadata.get("source_mode") == "group_topic":
                        destination_chat_id = int(pending_metadata["source_chat_id"])
                        destination_thread_id = int(pending_metadata["source_thread_id"])
                        break
                    # Messages stored before topic support have no
                    # source marker; treat them as private-chat messages.
                    if pending_metadata.get("source_mode", "private") == "private":
                        destination_chat_id = recipient.telegram_id
                        destination_thread_id = None
                        break
                copy_kwargs = {
                    "chat_id": destination_chat_id,
                    "from_chat_id": message.chat.id,
                    "message_id": message.message_id,
                }
                if destination_thread_id is not None:
                    copy_kwargs["message_thread_id"] = destination_thread_id
                copied = await bot.copy_message(**copy_kwargs)
                row.destination_message_id = copied.message_id
                delivery_metadata = json.loads(row.metadata_json or "{}")
                delivery_metadata["telegram_deliveries"] = [{
                    "user_id": recipient.id,
                    "telegram_message_id": copied.message_id,
                    "chat_id": destination_chat_id,
                    "thread_id": destination_thread_id,
                }]
                row.metadata_json = json.dumps(delivery_metadata, ensure_ascii=False)
                row.delivery_status = "delivered"
                db.commit()

                # Keep the teacher's bot chat focused on the persistent panel.
                try:
                    await bot.delete_message(chat_id=sender.telegram_id, message_id=message.message_id)
                except Exception:
                    logger.info("Could not remove teacher's sent message from the bot chat")

                # A successful teacher reply closes the pending batch.
                pending_rows = unanswered_before_reply
                for pending in pending_rows:
                    pending_metadata = json.loads(pending.metadata_json or "{}")
                    # Keep new native attachment copies and their student labels
                    # in the teacher's Telegram history. Only legacy transient
                    # inbox copies stored in destination_message_id are removed.
                    inbox_message_ids = [pending.destination_message_id]
                    for inbox_message_id in inbox_message_ids:
                        if not inbox_message_id:
                            continue
                        try:
                            await bot.delete_message(
                                chat_id=sender.telegram_id,
                                message_id=int(inbox_message_id),
                            )
                        except Exception:
                            logger.info(
                                "Could not remove handled student message %s from teacher inbox (telegram_message_id=%s)",
                                pending.id,
                                inbox_message_id,
                            )
                await mark_messages_read_by_teacher(bot, db, pending_rows)
                # Keep the selected conversation active after replying.
                try:
                    await update_teacher_panel(bot, db, sender)
                except Exception as exc:
                    logger.warning("Could not refresh teacher inbox (error_type=%s)", type(exc).__name__)
        except Exception as exc:
            row.delivery_status = "failed"
            db.commit()
            logger.warning(
                "Could not forward Telegram message (conversation_id=%s error_type=%s)",
                conversation.id,
                type(exc).__name__,
            )
            if sender.role == "teacher":
                await message.answer("Не удалось доставить сообщение. Попробуйте ещё раз позже.")
            else:
                await message.answer("Не удалось отправить сообщение. Попробуйте ещё раз позже.")
