"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy import select

from app.config import VAPID_PUBLIC_KEY
from app.models import PushSubscription
from app.schemas import LoginRequest
from app.security import (
    authenticate_panel_user,
    check_login_rate_limit,
    clear_panel_cookies,
    clear_username_failures,
    create_panel_session,
    record_failed_login,
    revoke_panel_session,
    verify_request_origin,
)
from app.modules.dependencies import Db, PanelUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Db):
    verify_request_origin(request)
    check_login_rate_limit(request, payload.username)
    identity = authenticate_panel_user(payload.username, payload.password)
    if not identity:
        record_failed_login(request, payload.username)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    clear_username_failures(request, payload.username)
    create_panel_session(db, identity, request, response)
    return {"ok": True, **identity}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Db):
    verify_request_origin(request)
    revoke_panel_session(request, db)
    clear_panel_cookies(request, response)
    return {"ok": True}


@router.get("/health")
def health():
    return {"status": "ok", "service": "uknowapp"}

@router.get("/push/public-key")
def push_public_key():
    return {"enabled": bool(VAPID_PUBLIC_KEY), "public_key": VAPID_PUBLIC_KEY or None}


@router.post("/push/subscribe")
def save_push_subscription(payload: dict, principal: PanelUser, db: Db):
    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 2048
        or not endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1"))
        or not isinstance(p256dh, str) or not 20 <= len(p256dh) <= 256
        or not isinstance(auth, str) or not 8 <= len(auth) <= 128
    ):
        raise HTTPException(status_code=400, detail="Некорректная подписка на уведомления")
    role = principal["role"]
    user_id = principal.get("user_id") if role in {"teacher", "student"} else None
    subscription = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user_id, role=role)
        db.add(subscription)
    else:
        subscription.p256dh = p256dh
        subscription.auth = auth
        subscription.user_id = user_id
        subscription.role = role
    db.commit()
    return {"ok": True}


@router.delete("/push/subscribe")
def remove_push_subscription(payload: dict, principal: PanelUser, db: Db):
    endpoint = payload.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise HTTPException(status_code=400, detail="Некорректная подписка")
    subscription = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if subscription and (
        (principal["role"] == "admin" and subscription.role == "admin")
        or (principal["role"] in {"teacher", "student"} and subscription.user_id == principal["user_id"])
    ):
        db.delete(subscription)
        db.commit()
    return {"ok": True}
