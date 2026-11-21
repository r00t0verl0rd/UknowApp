"""Composition of feature-specific HTTP routers."""

from fastapi import APIRouter

from .modules.administration.routes import router as administration_router
from .modules.boards.routes import router as boards_router
from .modules.panel.routes import router as panel_router
from .modules.system.routes import router as system_router
from .modules.telegram.internal import router as telegram_internal_router

router = APIRouter()
router.include_router(system_router)
router.include_router(telegram_internal_router)
router.include_router(administration_router)
router.include_router(boards_router)
router.include_router(panel_router)
