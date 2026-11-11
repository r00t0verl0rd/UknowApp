import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import ADMIN_PASSWORD, ADMIN_USERNAME

basic = HTTPBasic()


def verify_admin(username: str, password: str) -> bool:
    return secrets.compare_digest(username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8")) and secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic)],
) -> str:
    if not verify_admin(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
