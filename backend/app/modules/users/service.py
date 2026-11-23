"""Проверки и данные пользователей для API."""

import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ADMIN_USERNAME
from app.core.security import normalize_login
from app.models import User


def user_dict(user: User, include_telegram_id: bool = True, include_additional_info: bool = False) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        **({"additional_info": user.additional_info} if include_additional_info and user.role == "student" else {}),
        "web_username": (user.web_username or user.full_name) if user.role in {"teacher", "student"} else None,
        "role": user.role,
        "telegram_id": user.telegram_id if include_telegram_id else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "has_access_code": bool(user.web_password_hash),
    }


def generate_panel_access_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # pragma: allowlist secret
    return "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(
        secrets.choice(alphabet) for _ in range(4)
    )


def validate_panel_username(db: Session, username: str, exclude_user_id: int | None = None) -> str:
    cleaned = (username or "").strip()
    if len(cleaned) < 2 or len(cleaned) > 160:
        raise HTTPException(status_code=400, detail="Логин должен содержать от 2 до 160 символов")
    if cleaned.casefold() == ADMIN_USERNAME.casefold():
        raise HTTPException(status_code=409, detail="Этот логин зарезервирован для администратора")
    statement = select(User.id).where(
        User.role.in_(["teacher", "student"]),
        User.web_login_key == normalize_login(cleaned),
    )
    if exclude_user_id is not None:
        statement = statement.where(User.id != exclude_user_id)
    if db.scalar(statement.limit(1)) is not None:
        raise HTTPException(status_code=409, detail="Этот логин уже используется другим участником")
    return cleaned
