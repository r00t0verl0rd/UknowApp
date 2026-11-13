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
        await edit_inline_message(target, text, markup)
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.info("Could not edit Telegram panel message; sending a new one: %s", exc)
        await target.answer(text, reply_markup=markup)


def conversation_status(rows: list[Message]) -> dict:
    unanswered = 0
    latest_student = None
    latest_teacher = None
    for row in rows:
        if row.delivery_status != "delivered":
            continue
        if row.sender_role == "student":
            unanswered += 1
            latest_student = row
        elif row.sender_role == "teacher":
            unanswered = 0
            latest_teacher = row
    return {
        "unanswered": unanswered,
        "latest_student": latest_student,
        "latest_teacher": latest_teacher,
    }


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
        status = conversation_status(rows)
        last_student = status["latest_student"]
        items.append({
            "student": student,
            "conversation": conversation,
            "rows": rows,
            "unanswered": status["unanswered"],
            "latest_student": last_student,
            "preview": message_preview(last_student),
            "last_at": last_student.created_at.isoformat() if last_student else "",
        })
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


def role_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↻ Обновить", callback_data="ui:home")
    ]])


async def show_student_panel(target: TgMessage, student: User, db: Session, edit: bool = False) -> None:
    conversation = current_student_conversation(db, student.id)
    if not conversation or conversation.status != "active":
        text = (
            "👋 Здравствуйте, " + student.full_name + "!\n\n"
            "Пока вам не назначен учитель. Когда администратор создаст связь, "
            "здесь появится его имя и кнопка для отправки сообщения."
        )
        markup = role_panel_keyboard()
    else:
        teacher = conversation.assignment.teacher
        rows = conversation_messages(db, conversation.id)
        latest_teacher = next((row for row in reversed(rows) if row.sender_role == "teacher" and row.delivery_status == "delivered"), None)
        text = (
            "👋 Личный кабинет ученика\n\n"
            "Здравствуйте, " + student.full_name + "!\n\n"
            "👩‍🏫 Ваш учитель:\n" + teacher.full_name + "\n\n"
            "Последний ответ учителя:\n" + message_preview(latest_teacher) + "\n\n"
            "Нажмите кнопку ниже и отправьте сообщение — оно попадёт вашему учителю."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Написать учителю", callback_data="ui:student:write")],
            [InlineKeyboardButton(text="↻ Обновить", callback_data="ui:home")],
        ])
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def show_teacher_panel(target: TgMessage, teacher: User, db: Session, page: int = 0, edit: bool = False) -> None:
    items = teacher_conversations(db, teacher)
    total_unanswered = sum(item["unanswered"] for item in items)
    total_pages = max(1, (len(items) + TEACHER_PAGE_SIZE - 1) // TEACHER_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * TEACHER_PAGE_SIZE
    visible = items[start:start + TEACHER_PAGE_SIZE]

    lines = [
        "👩‍🏫 Панель учителя",
        "",
        "Здравствуйте, " + teacher.full_name + "!",
        "Учеников: " + str(len(items)),
        "Сообщений ждут ответа: " + str(total_unanswered),
        "",
    ]
    keyboard = []
    if not items:
        lines.append("Пока нет активных учеников. Они появятся здесь после назначения администратором.")
    else:
        lines.append("Входящие сообщения:")
        for item in visible:
            student_name = item["student"].full_name
            count = item["unanswered"]
            if count:
                lines.append("🔴 " + student_name + " — " + str(count) + " без ответа")
            else:
                lines.append("🟢 " + student_name + " — нет ожидающих ответов")
            lines.append("   " + item["preview"])
            label = ("🔴 " if count else "🟢 ") + student_name
            if count:
                label += " · " + str(count)
            keyboard.append([
                InlineKeyboardButton(
                    text=label[:60],
                    callback_data="ui:chat:" + str(item["conversation"].id) + ":0",
                )
            ])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="← Назад", callback_data="ui:teacher:page:" + str(page - 1)))
        nav.append(InlineKeyboardButton(text=str(page + 1) + "/" + str(total_pages), callback_data="ui:home"))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="Вперёд →", callback_data="ui:teacher:page:" + str(page + 1)))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="↻ Обновить список", callback_data="ui:home")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    text = "\n".join(lines)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def show_teacher_chat(target: TgMessage, teacher: User, db: Session, conversation: Conversation, page: int = 0, edit: bool = False) -> None:
    rows = conversation_messages(db, conversation.id)
    student = conversation.assignment.student
    status = conversation_status(rows)
    total_pages = max(1, (len(rows) + CHAT_PAGE_SIZE - 1) // CHAT_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    end = max(0, len(rows) - page * CHAT_PAGE_SIZE)
    start = max(0, end - CHAT_PAGE_SIZE)
    visible = rows[start:end]

    lines = [
        "💬 Диалог с учеником",
        student.full_name,
        "Ожидают ответа: " + str(status["unanswered"]),
        "",
    ]
    pending_ids = set()
    for row in rows:
        if row.delivery_status != "delivered":
            continue
        if row.sender_role == "student":
            pending_ids.add(row.id)
        elif row.sender_role == "teacher":
            pending_ids.clear()

    if not rows:
        lines.append("Сообщений пока нет.")
    else:
        for row in visible:
            sender_name = student.full_name if row.sender_role == "student" else "Вы"
            if row.sender_role == "student":
                marker = " · 🔴 без ответа" if row.id in pending_ids else " · ✅ отвечено"
                lines.append("📨 " + sender_name + marker + ":")
            else:
                lines.append("↩️ " + sender_name + ":")
            lines.append(message_preview(row))
            lines.append("")
        if page == 0 and len(rows) > CHAT_PAGE_SIZE:
            lines.append("Показаны последние сообщения.")
    keyboard = [[
        InlineKeyboardButton(text="✉️ Ответить", callback_data="ui:reply:" + str(conversation.id)),
        InlineKeyboardButton(text="← К ученикам", callback_data="ui:teacher:page:0"),
    ]]
    if total_pages > 1:
        nav = []
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="← Старее", callback_data="ui:chat:" + str(conversation.id) + ":" + str(page + 1)))
        if page > 0:
            nav.append(InlineKeyboardButton(text="Новее →", callback_data="ui:chat:" + str(conversation.id) + ":" + str(page - 1)))
        keyboard.insert(0, nav)
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    text = "\n".join(lines)[:3900]
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def show_role_panel(target: TgMessage, user: User, db: Session, edit: bool = False) -> None:
    if user.role == "student":
        await show_student_panel(target, user, db, edit=edit)
    elif user.role == "teacher":
        await show_teacher_panel(target, user, db, page=0, edit=edit)
    else:
        text = "UknowApp: управление пользователями и переписками доступно в веб-панели администратора."
        if edit:
            await edit_inline_message(target, text)
        else:
            await target.answer(text)


def notification_keyboard(conversation_id: int, student_name: str) -> InlineKeyboardMarkup:
    short_name = student_name if len(student_name) <= 22 else student_name[:21] + "…"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Ответить · " + short_name, callback_data="reply:" + str(conversation_id)),
            InlineKeyboardButton(text="Открыть диалог", callback_data="ui:chat:" + str(conversation_id) + ":0"),
        ],
        [InlineKeyboardButton(text="Панель учителя", callback_data="ui:home")],
    ])


async def show_reply_prompt(target: TgMessage, teacher: User, conversation: Conversation) -> None:
    student_name = conversation.assignment.student.full_name
    await target.answer(
        "Вы выбрали ученика: " + student_name + "\n\n"
        "Отправьте следующее сообщение или вложение — я доставлю его этому ученику.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="← Панель учителя", callback_data="ui:home"),
            InlineKeyboardButton(text="Открыть диалог", callback_data="ui:chat:" + str(conversation.id) + ":0"),
        ]]),
    )


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
        await show_role_panel(message, user, db)


@router.message(Command("menu"))
async def open_menu(message: TgMessage):
    if not message.from_user:
        return
    with SessionLocal() as db:
        user = get_linked_user(db, message.from_user.id)
        if not user:
            await message.answer("Сначала подключите аккаунт UknowApp с помощью кода администратора.")
            return
        await show_role_panel(message, user, db)


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
                await callback.answer()
                await show_role_panel(callback.message, user, db, edit=True)
            elif action == "student" and len(parts) > 2 and parts[2] == "write":
                if user.role != "student" or not current_student_conversation(db, user.id):
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
                await callback.answer()
                await show_teacher_panel(callback.message, user, db, page=page, edit=True)
            elif action == "chat" and len(parts) > 3:
                if user.role != "teacher":
                    await callback.answer("Просмотр доступен только учителю.", show_alert=True)
                    return
                conversation_id = int(parts[2])
                page = max(0, int(parts[3]))
                conversation = get_teacher_conversation(db, user, conversation_id)
                if not conversation:
                    await callback.answer("Эта переписка больше недоступна.", show_alert=True)
                    return
                await callback.answer()
                await show_teacher_chat(callback.message, user, db, conversation, page=page, edit=True)
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
                await callback.answer("Режим ответа включён")
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
                    await show_role_panel(message, linked_user, db)
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
                await message.answer(
                    "Пока вам не назначен активный учитель. Обратитесь к администратору.",
                    reply_markup=role_panel_keyboard(),
                )
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
            )
            row.destination_message_id = copied.message_id
            row.delivery_status = "delivered"
            db.commit()
            if sender.role == "student":
                # Keep the copied content intact, then show the sender's name and inline actions.
                try:
                    await bot.send_message(
                        chat_id=recipient.telegram_id,
                        text="📨 Новое сообщение от: " + sender.full_name,
                        reply_markup=notification_keyboard(conversation.id, sender.full_name),
                    )
                except Exception:
                    logger.exception("Could not send inline teacher notification for conversation_id=%s", conversation.id)
                await message.answer(
                    "✅ Сообщение доставлено учителю.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✉️ Написать ещё", callback_data="ui:student:write")],
                        [InlineKeyboardButton(text="Главное меню", callback_data="ui:home")],
                    ]),
                )
            else:
                await message.answer(
                    "✅ Ответ доставлен ученику " + recipient.full_name + ".",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Открыть диалог", callback_data="ui:chat:" + str(conversation.id) + ":0")],
                        [InlineKeyboardButton(text="Панель учителя", callback_data="ui:home")],
                    ]),
                )
        except Exception:
            row.delivery_status = "failed"
            db.commit()
            await message.answer("Не удалось доставить сообщение. Попробуйте ещё раз позже.")


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
