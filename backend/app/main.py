import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from .api import router
from .bots_gateway.gateway import BotsGateway, router as bots_gateway_router
from .core.config import (
    ALLOWED_ORIGINS,
    SEED_DEMO_DATA,
)
from .core.database import Base, SessionLocal, engine
from .migrations import initialize_database
from .migrations.runtime_split import initialize_runtime_storage
from .models import Assignment, Conversation, User
from .modules.administration.data import (
    apply_pending_data_restore,
    finish_startup_restore,
)
from .modules.notifications.vapid import reload_vapid_keys
from .modules.panel.personal import retry_personal_media_cleanup

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
        db.add(Conversation(assignment=assignment, teacher=teacher, student=student, status="active"))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    restoring = await asyncio.to_thread(apply_pending_data_restore)
    async with AsyncExitStack() as stack:
        try:
            await stack.enter_async_context(_start_services(app, restoring))
        except Exception:
            if not restoring:
                raise
            logger.exception("Ошибка запуска после восстановления; возвращаем исходные данные")
            await asyncio.to_thread(finish_startup_restore, False)
            await stack.enter_async_context(_start_services(app, False))
        else:
            if restoring:
                await asyncio.to_thread(finish_startup_restore, True)
        yield


async def _retry_media_cleanup():
    while True:
        try:
            await asyncio.to_thread(retry_personal_media_cleanup)
        except (SQLAlchemyError, OSError):
            logger.exception("Personal media cleanup worker will retry")
        await asyncio.sleep(30)


def _initialize_core(restoring):
    reload_vapid_keys()
    initialize_database()
    # Auxiliary storage must not prevent school API startup.
    try:
        initialize_runtime_storage()
    except (SQLAlchemyError, OSError):
        logger.exception("Runtime DB unavailable; school data remains available")
    if restoring:
        # Compile a real projection for each ORM table after all migrations.
        with engine.connect() as connection:
            for table in Base.metadata.sorted_tables:
                connection.execute(table.select().limit(0)).close()
    if SEED_DEMO_DATA:
        seed_demo_data()

@asynccontextmanager
async def _start_services(app: FastAPI, restoring: bool):
    await asyncio.to_thread(_initialize_core, restoring)
    gateway = BotsGateway()
    app.state.bots_gateway = gateway
    cleanup_task = asyncio.create_task(_retry_media_cleanup())
    try:
        await gateway.start()
        yield
    finally:
        await gateway.close()
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(
    title="UknowApp API",
    description="Школьная система переписки: UknowApp — источник истины, внешние мессенджеры — подключаемые каналы.",
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

app.include_router(bots_gateway_router)
