"""Общие зависимости HTTP-маршрутов."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.auth.permissions import permits
from app.modules.auth.service import require_admin, require_panel_user


def get_db():
    with SessionLocal() as db:
        yield db


Admin = Annotated[str, Depends(require_admin)]
PanelUser = Annotated[dict, Depends(require_panel_user)]
Db = Annotated[Session, Depends(get_db)]

def require_permission(permission):
    def check(principal: PanelUser):
        if not permits(principal, permission):
            raise HTTPException(status_code=401, detail="Недостаточно прав")
        return principal
    return check


SchoolStructure = Annotated[dict, Depends(require_permission("school.manage"))]
UserManagement = Annotated[dict, Depends(require_permission("users.manage"))]
