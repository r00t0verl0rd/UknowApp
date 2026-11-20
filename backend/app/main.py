import asyncio
import fcntl
import hashlib
import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress

from aiogram.exceptions import TelegramAPIError, TelegramConflictError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .core.config import (
    ALLOWED_ORIGINS,
    SEED_DEMO_DATA,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY_URL,
)
from .core.database import SessionLocal, create_tables
from .models import Assignment, Conversation, User
from .modules.communication.service import CommunicationService
from .modules.telegram.adapter import TelegramAdapter
from .modules.telegram.transport import create_telegram_bot

logger = logging.getLogger(__name__)


def seed_demo_data() -> None:
    with SessionLocal() as db:
        if db.query(User).count():
            return
        teacher = User(full_name="Анна Смирнова", role="teacher")
        student = User(full_name="Илья Петров", role="student")
        db.add_all([teacher, student])
        db.flush()
        assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
        db.add(assignment)
        db.flush()
        db.add(Conversation(assignment_id=assignment.id, status="active"))
        db.commit()


# Telegram работает в фоновой задаче: временная недоступность Telegram не должна останавливать API.
async def run_telegram_bot(bot, dispatcher, app) -> None:
    """Run polling in the background; Telegram outages must not stop the web API."""
    retry_delay = 5
    while True:
        try:
            # This call can time out when Telegram is unreachable. It must never
            # run directly in the FastAPI startup path.
            bot_info = await bot.get_me()
            app.state.telegram_status = "connected"
            logger.warning(
                "TELEGRAM_CONNECTED username=@%s id=%s privacy_disabled=%s",
                bot_info.username, bot_info.id,
                getattr(bot_info, "can_read_all_group_messages", None),
            )
            await bot.delete_webhook(drop_pending_updates=False)
            logger.warning("TELEGRAM_POLLING_STARTED")
            polling_started_at = asyncio.get_running_loop().time()
            await dispatcher.start_polling(bot, handle_signals=False)
            # start_polling normally runs until shutdown. If it returns while
            # the application is still alive, treat that as an unexpected stop
            # and bring polling back instead of silently leaving the bot offline.
            logger.error("TELEGRAM_POLLING_STOPPED_UNEXPECTEDLY")
            if asyncio.get_running_loop().time() - polling_started_at >= 60:
                retry_delay = 5
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        except asyncio.CancelledError:
            raise
        except TelegramConflictError:
            app.state.telegram_status = "conflict"
            # A Telegram conflict means another process is polling this bot.
            # Retrying forever only creates noisy logs and repeated takeovers.
            logger.critical(
                "TELEGRAM_POLLING_CONFLICT: another process is already calling getUpdates "
                "for this bot. Polling has been stopped; close the other bot instance "
                "and restart UknowApp.",
            )
            return
        except TelegramAPIError as exc:
            app.state.telegram_status = "unavailable"
            # Telegram Bot API request URLs may contain the bot token.
            # Log the exception type only; never print request URLs or headers.
            logger.error(
                "Telegram bot could not connect (error_type=%s). Retrying in %s seconds; "
                "the admin panel remains available.",
                type(exc).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


# Подготавливаем БД и запускаем один экземпляр фонового Telegram polling на время жизни API.
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    if SEED_DEMO_DATA:
        seed_demo_data()

    app.state.telegram_status = "disabled"
    bot_task = None
    bot = None
    dispatcher = None
    polling_lock_fd = None
    if TELEGRAM_BOT_TOKEN:
        from .telegram_bot import create_dispatcher

        bot = create_telegram_bot(TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY_URL)
        app.state.telegram_status = "connecting"
        app.state.telegram_bot = bot
        app.state.communication = CommunicationService([TelegramAdapter(bot)])

        # A non-blocking OS lock prevents two local Uvicorn processes (including
        # accidental duplicate launches) from polling the same Telegram bot.
        token_fingerprint = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).hexdigest()[:20]
        lock_path = os.path.join(tempfile.gettempdir(), f"uknowapp-telegram-{token_fingerprint}.lock")
        polling_lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(polling_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(polling_lock_fd)
            polling_lock_fd = None
            app.state.telegram_status = "another_instance"
            logger.warning(
                "TELEGRAM_POLLING_SKIPPED: another local UknowApp process already owns "
                "the polling lock. This process will keep the web API available without polling.",
            )
        else:
            dispatcher = create_dispatcher()
            bot_task = asyncio.create_task(
                run_telegram_bot(bot, dispatcher, app),
                name="uknowapp-telegram-polling",
            )
    else:
        app.state.telegram_bot = None
        app.state.communication = CommunicationService()
        logger.error("TELEGRAM_BOT_TOKEN_EMPTY: Telegram bot is disabled; admin API remains available.")
    try:
        yield
    finally:
        if dispatcher:
            with suppress(Exception):
                await dispatcher.stop_polling()
        if bot_task:
            bot_task.cancel()
            with suppress(asyncio.CancelledError):
                await bot_task
        if bot:
            await bot.session.close()
        if polling_lock_fd is not None:
            with suppress(OSError):
                fcntl.flock(polling_lock_fd, fcntl.LOCK_UN)
            with suppress(OSError):
                os.close(polling_lock_fd)


app = FastAPI(
    title="UknowApp API",
    description="Школьная система приватной переписки ученика и учителя через Telegram-бота.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
