import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import SEED_DEMO_DATA, TELEGRAM_BOT_TOKEN
from .database import SessionLocal, create_tables
from .models import Assignment, Conversation, User


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
            dispatcher.start_polling(bot, handle_signals=False),
            name="uknowapp-telegram-polling",
        )
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
