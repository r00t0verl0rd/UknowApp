import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select

from app.models import PanelSession, User
from app.rate_limit import SlidingWindowLimiter

from .config import ADMIN_PASSWORD, ADMIN_USERNAME, ALLOWED_ORIGINS, TRUSTED_PROXY_IPS
from .database import SessionLocal

SESSION_COOKIE = "uknowapp_session"
SECURE_SESSION_COOKIE = "__Host-uknowapp_session"
SESSION_TTL = timedelta(days=30)
SESSION_MAX_AGE = int(SESSION_TTL.total_seconds())
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_USER_LIMIT = 8
_LOGIN_IP_LIMIT = 60
_login_rate_limiter = SlidingWindowLimiter()


def verify_admin(username: str, password: str) -> bool:
    # Never allow the documented fallback credentials to authenticate an admin.
    if ADMIN_PASSWORD in {"change-me-now", "replace-with-a-long-random-password"}:
        return False
    return (
        secrets.compare_digest(username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8"))
        and secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    )


# Храним только PBKDF2-хеш с уникальной солью, а не исходный код доступа.
def hash_web_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt.hex() + ":" + digest.hex()


# Сравниваем вычисленный хеш с сохранённым значением без утечки через время сравнения.
def verify_web_password(password: str, stored: str | None) -> bool:
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


def authenticate_panel_user(username: str, password: str) -> dict | None:
    if verify_admin(username, password):
        return {"role": "admin", "user_id": None, "full_name": "Администратор"}
    normalized_username = (username or "").strip().casefold()
    if not normalized_username:
        return None
    with SessionLocal() as db:
        users = db.scalars(
            select(User).where(User.role.in_(["teacher", "student"])),
        ).all()
        matches = [
            user for user in users
            if (user.web_username or user.full_name).strip().casefold() == normalized_username
        ]
        if len(matches) != 1:
            return None
        user = matches[0]
        if not verify_web_password(password, user.web_password_hash):
            return None
        return {"role": user.role, "user_id": user.id, "full_name": user.full_name}


def verify_request_origin(request: Request) -> None:
    """Reject cross-origin state-changing browser requests (CSRF defence)."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        # Non-browser clients do not send Origin; cookie-based browser requests do.
        return
    origin = origin.strip().rstrip("/")
    current_origin = (str(request.base_url).rstrip("/"))
    allowed = {item.strip().rstrip("/") for item in ALLOWED_ORIGINS if item.strip()}
    allowed.add(current_origin)
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Запрос с этого источника запрещён")


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer not in TRUSTED_PROXY_IPS:
        return peer

    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    try:
        return str(ipaddress.ip_address(forwarded.strip()))
    except ValueError:
        return peer


def _login_keys(request: Request, username: str) -> tuple[str, str]:
    ip = _client_ip(request)
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
        value = ADMIN_USERNAME + "\0" + ADMIN_PASSWORD
    elif role in {"teacher", "student"} and user_id is not None:
        user = db.get(User, user_id)
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

    # A new login replaces the browser's previous session, limiting the
    # lifetime of any older token that may have been copied or exposed.
    revoke_panel_session(request, db)
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
        # Remove a legacy development cookie when the site first moves to HTTPS.
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


def revoke_panel_session(request: Request, db) -> None:
    # Revoke either cookie variant if a browser is transitioning from local HTTP
    # development to HTTPS on the same host.
    revoked = False
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
            db.delete(session)
            revoked = True
    if revoked:
        db.commit()


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


def _load_panel_identity(request: Request) -> dict | None:
    token_hash = _token_digest(_request_token(request))
    if not token_hash:
        return None
    with SessionLocal() as db:
        session = db.scalar(select(PanelSession).where(PanelSession.token_hash == token_hash))
        if not session:
            return None

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
            user = db.get(User, session.user_id)
            expected_fingerprint = _credential_fingerprint(db, session.role, session.user_id)
            valid = (
                valid
                and user is not None
                and user.role == session.role
                and expected_fingerprint is not None
                and secrets.compare_digest(
                    session.credential_fingerprint, expected_fingerprint or "",
                )
            )
            identity = (
                {"role": user.role, "user_id": user.id, "full_name": user.full_name}
                if valid and user else None
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
    verify_request_origin(request)
    identity = _load_panel_identity(request)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла или недействительна. Войдите снова.",
        )
    return identity


def require_admin(request: Request) -> str:
    verify_request_origin(request)
    identity = _load_panel_identity(request)
    if not identity or identity.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуются права администратора",
        )
    return ADMIN_USERNAME
