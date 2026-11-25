"""HTTP router for data administration; implementation lives in focused modules."""
from fastapi import APIRouter

from . import backup, restore, stats

router = APIRouter(prefix="/admin/data", tags=["admin-data"])
router.include_router(backup.router)
router.include_router(restore.router)
router.include_router(stats.router)
