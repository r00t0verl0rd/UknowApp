"""Shared FastAPI dependencies for feature routers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.auth.service import require_admin, require_panel_user


def get_db():
    with SessionLocal() as db:
        yield db


Admin = Annotated[str, Depends(require_admin)]
PanelUser = Annotated[dict, Depends(require_panel_user)]
Db = Annotated[Session, Depends(get_db)]
