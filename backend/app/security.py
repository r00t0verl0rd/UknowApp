import hashlib
import secrets
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import ADMIN_PASSWORD, ADMIN_USERNAME
from .database import SessionLocal
from .models import User

basic = HTTPBasic()


def verify_admin(username: str, password: str) -> bool:
    return (
        secrets.compare_digest(username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8"))
        and secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    )


def hash_web_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt.hex() + ":" + digest.hex()


def verify_web_password(password: str, stored: Optional[str]) -> bool:
    if not stored or ":" not in stored:
        return False
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return secrets.compare_digest(actual, expected)


def authenticate_panel_user(username: str, password: str) -> Optional[dict]:
    if verify_admin(username, password):
        return {"role": "admin", "user_id": None, "full_name": "Администратор"}
    normalized_username = (username or "").strip().casefold()
    if not normalized_username:
        return None
    with SessionLocal() as db:
        teachers = db.query(User).filter(User.role == "teacher", User.active.is_(True)).all()
        matches = [
            user for user in teachers
            if (user.web_username or user.full_name).strip().casefold() == normalized_username
        ]
        # Ambiguous logins are never allowed to authenticate the wrong account.
        if len(matches) != 1:
            return None
        user = matches[0]
        if not verify_web_password(password, user.web_password_hash):
            return None
        return {"role": "teacher", "user_id": user.id, "full_name": user.full_name}


def require_panel_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic)],
) -> dict:
    identity = authenticate_panel_user(credentials.username, credentials.password)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return identity


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic)],
) -> str:
    if not verify_admin(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуются права администратора",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
