import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import ALLOWED_ORIGINS, SEED_DEMO_DATA, TELEGRAM_BOT_TOKEN
from .database import SessionLocal, create_tables
from .models import Assignment, Conversation, User

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


async def run_telegram_bot(bot, dispatcher) -> None:
    """Run polling in the background; Telegram outages must not stop the web API."""
    retry_delay = 5
    while True:
        try:
            # This call can time out when Telegram is unreachable. It must never
            # run directly in the FastAPI startup path.
            bot_info = await bot.get_me()
            logger.warning(\n                "TELEGRAM_CONNECTED username=@%s id=%s privacy_disabled=%s",\n                bot_info.username, bot_info.id,\n                getattr(bot_info, "can_read_all_group_messages", None),\n            )
            await bot.delete_webhook(drop_pending_updates=False)
            logger.warning("TELEGRAM_POLLING_STARTED")
            await dispatcher.start_polling(bot, handle_signals=False)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Telegram bot could not connect. Retrying in %s seconds; "
                "the admin panel remains available.",
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    if SEED_DEMO_DATA:
        seed_demo_data()

    bot_task = None
    bot = None
    dispatcher = None
    if TELEGRAM_BOT_TOKEN:
        from aiogram import Bot
        from .telegram_bot import create_dispatcher

        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        dispatcher = create_dispatcher()
        bot_task = asyncio.create_task(
            run_telegram_bot(bot, dispatcher),
            name="uknowapp-telegram-polling",
        )
    else:
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
