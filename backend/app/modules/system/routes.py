"""HTTP API веб-панели и обмена сообщениями."""

import logging
from uuid import uuid4
from urllib.parse import urlsplit
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.security import verify_request_origin
from app.models import PanelSession, PushSubscription
from app.core import runtime_database
from app.modules.auth.service import (
    _request_token,
    _token_digest,
    authenticate_panel_user,
    check_login_rate_limit,
    clear_panel_cookies,
    clear_username_failures,
    create_panel_session,
    record_failed_login,
    revoke_panel_session,
)
from app.modules.dependencies import Admin, Db, PanelUser
from app.modules.notifications import vapid
from app.modules.notifications.endpoints import is_safe_push_endpoint
from app.request_validation import login_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.post("/auth/login")
def login(payload: dict, request: Request, response: Response, db: Db):
    payload = login_payload(payload)
    verify_request_origin(request)
    check_login_rate_limit(request, payload["username"])
    identity = authenticate_panel_user(payload["username"], payload["password"])
    if not identity:
        record_failed_login(request, payload["username"])
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    clear_username_failures(request, payload["username"])
    create_panel_session(db, identity, request, response)
    return {"ok": True, **identity}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Db):
    verify_request_origin(request)
    revoke_panel_session(request, db)
    clear_panel_cookies(request, response)
    return {"ok": True}


@router.get("/health")
def health(request: Request, db: Db):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error("Database health check failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    gateway = getattr(request.app.state, "bots_gateway", None)
    broker_status = ("disabled" if not gateway or not gateway.platforms else
                     "connected" if gateway.ready and gateway.nc and gateway.nc.is_connected else "unavailable")
    runtime_status = getattr(request.app.state, "runtime_status", "unknown")
    return {"status": "ok" if broker_status != "unavailable" and runtime_status != "unavailable" else "degraded",
            "service": "uknowapp", "components": {"database": "ok", "bots_gateway": broker_status,
                                                  "runtime_database": runtime_status}}

@router.get("/push/public-key")
def push_public_key():
    return {"enabled": bool(vapid.VAPID_PUBLIC_KEY), "public_key": vapid.VAPID_PUBLIC_KEY or None}


@router.post("/push/subscribe")
def save_push_subscription(payload: dict, request: Request, principal: PanelUser, db: Db):
    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    if not isinstance(keys, dict):
        raise HTTPException(400, "Некорректная подписка на уведомления")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 2048
        or not is_safe_push_endpoint(endpoint)
        or not isinstance(p256dh, str) or not 20 <= len(p256dh) <= 256
        or not isinstance(auth, str) or not 8 <= len(auth) <= 128
    ):
        raise HTTPException(status_code=400, detail="Некорректная подписка на уведомления")
    role = principal["role"]
    user_id = principal.get("user_id") if role in {"teacher", "student"} else None
    session_hash = _token_digest(_request_token(request))
    # Recheck the actual session before writing; a concurrent logout must not
    # silently attach a device to a different user's session.
    session = db.scalar(select(PanelSession).where(PanelSession.token_hash == session_hash))
    if not session or session.role != role or session.user_id != user_id:
        raise HTTPException(401, "Сессия истекла или недействительна. Войдите снова.")
    try:
        with runtime_database.RuntimeSessionLocal() as runtime:
            for attempt in range(2):
                subscription = runtime.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
                if subscription and subscription.delivery_state == "expired" and subscription.p256dh == p256dh and subscription.auth == auth:
                    # A 404/410 from the provider requires a new browser subscription,
                    # not just another INSERT of the same dead endpoint.
                    raise HTTPException(410, "Подписка устарела. Необходимо обновить её.")
                if subscription is None:
                    subscription = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user_id, role=role)
                    runtime.add(subscription)
                changed = (subscription.p256dh != p256dh or subscription.auth != auth or
                           subscription.user_id != user_id or subscription.role != role or
                           subscription.session_hash != session_hash or not subscription.revision)
                if changed:
                    subscription.revision = uuid4().hex
                    subscription.delivery_state = None
                    subscription.last_http_status = None
                    subscription.last_attempt_at = None
                    subscription.last_success_at = None
                subscription.p256dh = p256dh
                subscription.auth = auth
                subscription.user_id = user_id
                subscription.role = role
                subscription.session_hash = session_hash
                subscription.synced_at = datetime.now(UTC)
                try:
                    runtime.commit()
                    break
                except IntegrityError:
                    runtime.rollback()
                    if attempt:
                        raise
            return {"ok": True}

    except SQLAlchemyError as exc:
        raise HTTPException(503, "Push registry unavailable") from exc


@router.delete("/push/subscribe")
def remove_push_subscription(payload: dict, request: Request, principal: PanelUser, db: Db):
    endpoint = payload.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise HTTPException(status_code=400, detail="Некорректная подписка")
    with runtime_database.RuntimeSessionLocal() as runtime:
        subscription = runtime.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        session_hash = _token_digest(_request_token(request))
        if subscription and (subscription.session_hash is None or subscription.session_hash == session_hash) and (
            (principal["role"] == "admin" and subscription.role == "admin")
            or (principal["role"] in {"teacher", "student"} and subscription.user_id == principal["user_id"])
        ):
            runtime.delete(subscription)
            runtime.commit()
        return {"ok": True}


@router.get("/admin/push/diagnostics")
def push_diagnostics(_: Admin, db: Db):
    try:
        with runtime_database.RuntimeSessionLocal() as runtime:
            rows = runtime.scalars(select(PushSubscription).order_by(PushSubscription.id)).all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Push registry unavailable") from exc
    now = datetime.now(UTC)
    active_sessions = set(db.scalars(select(PanelSession.token_hash).where(PanelSession.expires_at > now,
        PanelSession.token_hash.in_({row.session_hash for row in rows if row.session_hash}))).all())
    def device(row):
        session_active = row.session_hash in active_sessions if row.session_hash else None
        return {"id": row.id, "role": row.role, "user_id": row.user_id,
                "provider": urlsplit(row.endpoint).hostname,
                "created_at": row.created_at, "synced_at": row.synced_at,
                "last_attempt_at": row.last_attempt_at, "last_success_at": row.last_success_at,
                "state": row.delivery_state or "registered", "http_status": row.last_http_status,
                "session_active": session_active,
                "eligible": row.delivery_state != "expired" and session_active is True}
    devices = [device(row) for row in rows]
    return {"enabled": bool(vapid.VAPID_PRIVATE_KEY and vapid.VAPID_PUBLIC_KEY),
            "registered": len(devices), "eligible": sum(d["eligible"] for d in devices),
            "admin_devices": sum(d["role"] == "admin" for d in devices),
            "admin_eligible": sum(d["role"] == "admin" and d["eligible"] for d in devices),
            "devices": devices}


@router.get("/admin/bots/diagnostics")
def bots_diagnostics(request: Request, _: Admin):
    gateway = getattr(request.app.state, "bots_gateway", None)
    connectors = {}
    if gateway:
        for platform in gateway.platforms:
            data = dict(gateway.connectors.get(platform, {}))
            age = (datetime.now(UTC) - datetime.fromisoformat(data["seen"])).total_seconds() if data.get("seen") else None
            connectors[platform] = {**data, "online": age is not None and age <= 45,
                                    "age_seconds": round(age) if age is not None else None}
    return {"broker_connected": bool(gateway and gateway.ready and gateway.nc and gateway.nc.is_connected),
            "platforms": gateway.diagnostics if gateway else {},
            "connectors": connectors}
