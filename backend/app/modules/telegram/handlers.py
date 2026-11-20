"""Telegram commands and transport-level event routing."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage

from app.core.database import SessionLocal
from app.models import TeacherPanel, User
from app.modules.messaging.inbound import (
    bind_student_forum_topic,
    clear_teacher_session,
    current_student_conversation,
    get_teacher_conversation,
    mark_visible_messages_read_by_teacher,
    process_inbound_message,
    set_teacher_session,
)
from app.rate_limit import SlidingWindowLimiter

from .adapter import TelegramAdapter
from .common import get_linked_user
from .teacher import handle_teacher_keyboard_message, update_teacher_panel

logger = logging.getLogger(__name__)
router = Router()

_BIND_GROUP_WINDOW = 60
_BIND_GROUP_LIMIT = 5
_bind_group_limiter = SlidingWindowLimiter()


def _bind_group_attempt_allowed(telegram_id: int, chat_id: int) -> bool:
    return _bind_group_limiter.allow_and_record(
        (telegram_id, chat_id), _BIND_GROUP_LIMIT, _BIND_GROUP_WINDOW,
    )


@router.message(CommandStart())
async def start(message: TgMessage, bot: Bot):
    if not message.from_user:
        return
    with SessionLocal() as db:
        user = get_linked_user(db, message.from_user.id)
        if not user:
            await message.answer(
                "Добро пожаловать в Uknow! 🙂\n\n"
                "Для подключения попросите администратора выдать вам код доступа",
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
                    "😊 Вы подключены к UknowApp.\n"
                    "🎓 Ваш учитель: " + teacher.full_name + ".\n\n"
                    "Пишите сюда и отправляйте файлы — всё попадёт вашему учителю.",
                )
            else:
                await message.answer(
                    "Аккаунт подключён, но активный учитель пока не назначен. "
                    "Обратитесь к администратору.",
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
            mark_visible_messages_read_by_teacher(db, opened_conversation)
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
        mark_visible_messages_read_by_teacher(db, conversation)
        await update_teacher_panel(bot, db, teacher)


@router.message(Command("bind_group"))
async def bind_student_group(message: TgMessage, bot: Bot):
    """Bind the current Telegram forum topic to the linked student account."""
    if not message.from_user:
        return
    if message.chat.type != "supergroup" or not message.chat.is_forum or not message.message_thread_id:
        await message.answer(
            "Откройте тему «🤖 Бот» в супергруппе с включёнными темами и отправьте /bind_group.",
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
            getattr(bot_info, "can_read_all_group_messages", False),
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
                "и добавьте снова. После этого повторите /bind_group.",
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
            "Затем повторите /bind_group.",
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

        if not bind_student_forum_topic(
            db, student, message.chat.id, message.message_thread_id, message.chat.title,
        ):
            await message.answer("Эта тема уже привязана к другому ученику.")
            return

    await message.answer(
        "✅ Тема привязана к вашему аккаунту UknowApp.\n"
        "Сообщения из этой темы и личного чата с ботом попадут в одну переписку учителя. "
        "Ответ преподавателя появится в канале последнего сообщения.",
    )




@router.message()
async def route_message(message: TgMessage, bot: Bot):
    adapter = TelegramAdapter(bot)
    inbound = adapter.normalize_message(message)
    with SessionLocal() as db:
        result = await process_inbound_message(
            db,
            inbound,
            adapter,
            ui_handler=handle_teacher_keyboard_message,
        )
        if result.refresh_teacher_id:
            teacher = db.get(User, result.refresh_teacher_id)
            if teacher:
                try:
                    await update_teacher_panel(
                        bot,
                        db,
                        teacher,
                        force_keyboard_refresh=result.force_teacher_panel_refresh,
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not refresh teacher panel (teacher_id=%s error_type=%s)",
                        teacher.id,
                        type(exc).__name__,
                    )
