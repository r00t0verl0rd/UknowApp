"""HTTP API веб-панели и обмена сообщениями: сборка маршрутов из тематических модулей."""

from fastapi import APIRouter

from . import conversations, outbound, personal, session, sync

router = APIRouter(prefix="/api")
for _module in (session, conversations, personal, sync, outbound):
    router.include_router(_module.router)
