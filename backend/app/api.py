"""Composition of feature-specific HTTP routers."""

from fastapi import APIRouter

from .modules.system.routes import router as system_router
from .modules.administration.routes import router as administration_router
from .modules.panel.routes import router as panel_router

router = APIRouter()
router.include_router(system_router)
router.include_router(administration_router)
router.include_router(panel_router)
