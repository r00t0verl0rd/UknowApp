"""Авторизация, защита входа и сессии."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import lazyload

from app.core import security
from app.core.database import SessionLocal
from app.models import PanelSession, PushSubscription, User
from app.core import runtime_database
from sqlalchemy.exc import SQLAlchemyError
from app.modules.auth.permissions import permits
from app.rate_limit import SlidingWindowLimiter

SESSION_COOKIE = "uknowapp_session"
SECURE_SESSION_COOKIE = "__Host-uknowapp_session"
SESSION_TTL = timedelta(days=30)
SESSION_MAX_AGE = int(SESSION_TTL.total_seconds())
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_USER_LIMIT = 8
_LOGIN_IP_LIMIT = 60
_login_rate_limiter = SlidingWindowLimiter()


def authenticate_panel_user(username: str, password: str) -> dict | None:
    if security.verify_admin(username, password):
        return {"role": "admin", "user_id": None, "full_name": "Администратор"}
    normalized_username = security.normalize_login(username)
    if not normalized_username:
        return None
    with SessionLocal() as db:
        matches = db.scalars(
            select(User).options(lazyload(User.messenger_accounts)).where(
                User.role.in_(["teacher", "student"]),
                User.web_login_key == normalized_username,
            ),
        ).all()
        if len(matches) != 1:
            return None
        user = matches[0]
        if not security.verify_web_password(password, user.web_password_hash):
            return None
        return {"role": user.role, "user_id": user.id, "full_name": user.full_name}


def _login_keys(request: Request, username: str) -> tuple[str, str]:
    ip = security._client_ip(request)
    normalized = (username or "").strip().casefold()[:160]
    return "ip:" + ip, "user:" + ip + ":" + normalized


# Ограничиваем частоту входов отдельно по IP и по паре IP/логин.
def check_login_rate_limit(request: Request, username: str) -> None:
    ip_key, user_key = _login_keys(request, username)
    retry_after = max(
        _login_rate_limiter.retry_after(ip_key, _LOGIN_IP_LIMIT, _LOGIN_WINDOW_SECONDS),
        _login_rate_limiter.retry_after(user_key, _LOGIN_USER_LIMIT, _LOGIN_WINDOW_SECONDS),
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Слишком много неудачных попыток входа. Попробуйте позже.",
            headers={"Retry-After": str(retry_after)},
        )


def record_failed_login(request: Request, username: str) -> None:
    ip_key, user_key = _login_keys(request, username)
    _login_rate_limiter.record(ip_key, _LOGIN_WINDOW_SECONDS)
    _login_rate_limiter.record(user_key, _LOGIN_WINDOW_SECONDS)


def clear_username_failures(request: Request, username: str) -> None:
    _, user_key = _login_keys(request, username)
    _login_rate_limiter.clear(user_key)


def _credential_fingerprint(db, role: str, user_id: int | None) -> str | None:
    if role == "admin":
        value = security.ADMIN_USERNAME + "\0" + security.ADMIN_PASSWORD
    elif role in {"teacher", "student"} and user_id is not None:
        user = db.get(User, user_id, options=[lazyload(User.messenger_accounts)])
        if not user or user.role != role or not user.web_password_hash:
            return None
        value = user.web_password_hash
    else:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_panel_session(
    db,
    identity: dict,
    request: Request,
    response: Response,
) -> None:
    role = identity["role"]
    user_id = identity.get("user_id")
    fingerprint = _credential_fingerprint(db, role, user_id)
    if not fingerprint:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")

    # Новый вход отзывает предыдущую браузерную сессию.
    revoke_panel_session(request, db, detach_push=False)
    now = datetime.now(UTC)
    db.query(PanelSession).filter(PanelSession.expires_at < now).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    db.add(PanelSession(
        token_hash=token_hash,
        role=role,
        user_id=user_id,
        credential_fingerprint=fingerprint,
        created_at=now,
        expires_at=now + SESSION_TTL,
    ))
    db.commit()

    secure = request.url.scheme == "https"
    cookie_name = SECURE_SESSION_COOKIE if secure else SESSION_COOKIE
    if secure:
        # При переходе на HTTPS очищаем прежнюю cookie.
        response.delete_cookie(
            key=SESSION_COOKIE,
            path="/",
            secure=False,
            httponly=True,
            samesite="strict",
        )
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _request_token(request: Request) -> str | None:
    return request.cookies.get(SECURE_SESSION_COOKIE) or request.cookies.get(SESSION_COOKIE)


def _token_digest(token: str | None) -> str | None:
    if not token or len(token) > 128:
        return None
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(token_bytes).hexdigest()


def revoke_panel_session(request: Request, db, *, detach_push: bool = True) -> None:
    # При выходе отзываем оба варианта cookie.
    revoked = False
    detach = []
    tokens = {
        request.cookies.get(SECURE_SESSION_COOKIE),
        request.cookies.get(SESSION_COOKIE),
    }
    for token in tokens:
        token_hash = _token_digest(token)
        if not token_hash:
            continue
        session = db.scalar(select(PanelSession).where(PanelSession.token_hash == token_hash))
        if session:
            if detach_push:
                detach.append(token_hash)
            db.delete(session)
            revoked = True
    if revoked:
        db.commit()
    if detach:
        try:
            with runtime_database.RuntimeSessionLocal() as runtime:
                runtime.query(PushSubscription).filter(PushSubscription.session_hash.in_(detach)).delete(synchronize_session=False)
                runtime.commit()
        except SQLAlchemyError:
            # Revoked main sessions are ineligible even if physical cleanup fails.
            pass


def clear_panel_cookies(request: Request, response: Response) -> None:
    secure = request.url.scheme == "https"
    for cookie_name in (SECURE_SESSION_COOKIE, SESSION_COOKIE):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            secure=(cookie_name == SECURE_SESSION_COOKIE) or secure,
            httponly=True,
            samesite="strict",
        )


def load_panel_identity(request: Request) -> dict | None:
    token_hash = _token_digest(_request_token(request))
    if not token_hash:
        return None
    with SessionLocal() as db:
        result = db.execute(
            select(PanelSession, User.role, User.full_name, User.web_password_hash)
            .outerjoin(User, User.id == PanelSession.user_id)
            .where(PanelSession.token_hash == token_hash)
        ).one_or_none()
        if result is None:
            return None
        session, user_role, full_name, password_hash = result

        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        valid = expires_at > datetime.now(UTC)
        if session.role == "admin":
            valid = valid and session.user_id is None
            expected_fingerprint = _credential_fingerprint(db, "admin", None)
            valid = valid and secrets.compare_digest(
                session.credential_fingerprint, expected_fingerprint or "",
            )
            identity = {"role": "admin", "user_id": None, "full_name": "Администратор"}
        elif session.role in {"teacher", "student"} and session.user_id is not None:
            expected_fingerprint = (
                hashlib.sha256(password_hash.encode("utf-8")).hexdigest()
                if user_role == session.role and password_hash else None
            )
            valid = (
                valid and expected_fingerprint is not None
                and secrets.compare_digest(session.credential_fingerprint, expected_fingerprint)
            )
            identity = (
                {"role": user_role, "user_id": session.user_id, "full_name": full_name}
                if valid else None
            )
        else:
            valid = False
            identity = None

        if not valid:
            db.delete(session)
            db.commit()
            return None
        return identity


def require_panel_user(request: Request) -> dict:
    security.verify_request_origin(request)
    identity = load_panel_identity(request)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла или недействительна. Войдите снова.",
        )
    return identity


def require_admin(request: Request) -> str:
    security.verify_request_origin(request)
    identity = load_panel_identity(request)
    if not permits(identity, "school.manage"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуются права администратора",
        )
    return security.ADMIN_USERNAME
