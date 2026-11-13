"""Telegram commands and message routing."""

import json
import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message as TgMessage

from .database import SessionLocal
from .media_storage import archive_telegram_media
from .models import TeacherPanel, TeacherSession
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
    pending_student_messages,
    set_teacher_session,
    update_teacher_panel,
)

logger = logging.getLogger(__name__)
router = Router()


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
