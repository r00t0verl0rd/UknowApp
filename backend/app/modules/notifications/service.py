"""Web Push для авторизованных пользователей."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import UTC, datetime
from collections.abc import Iterable
from urllib.parse import parse_qs, urlsplit

from pywebpush import WebPushException, webpush
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core import config
from app.models import PanelSession, PushSubscription
from app.modules.notifications import vapid
from app.modules.notifications.endpoints import is_safe_push_endpoint

logger = logging.getLogger(__name__)
# Shared bounded network pool; never use the web request/event-loop thread for I/O.
_PUSH_POOL = ThreadPoolExecutor(max_workers=10, thread_name_prefix="web-push")
_RESULT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push-results")


def schedule_push(
    db: Session,
    user_ids: Iterable[int],
    title: str,
    body: str,
    url: str = "/",
    include_admin: bool = False,
    admin_body: str | None = None,
) -> None:
    """Отправлять push в фоне, не задерживая сообщения."""
    if not vapid.VAPID_PRIVATE_KEY:
        return
    ids = {int(user_id) for user_id in user_ids if user_id}
    conditions = [PushSubscription.user_id.in_(ids)] if ids else []
    if include_admin:
        conditions.append(PushSubscription.role == "admin")
    if not conditions:
        return
    subscriptions = db.scalars(
        select(PushSubscription).where(or_(*conditions),
            or_(PushSubscription.delivery_state.is_(None), PushSubscription.delivery_state != "expired"),
            or_(PushSubscription.session_hash.is_(None), PushSubscription.session_hash.in_(
                select(PanelSession.token_hash).where(PanelSession.expires_at > datetime.now(UTC))))),
    ).all()
    targets = [
        {
            "id": item.id,
            "role": item.role,
            "revision": item.revision,
            "session_hash": item.session_hash,
            "endpoint": item.endpoint,
            "keys": {"p256dh": item.p256dh, "auth": item.auth},
        }
        for item in subscriptions
    ]
    if not targets:
        return
    query = parse_qs(urlsplit(url).query)
    try:
        conversation_id = int(query.get("openConversation", ["0"])[0]) or None
    except (TypeError, ValueError):
        conversation_id = None
    data = {
        "title": title[:80],
        "body": body[:160],
        "url": url if url.startswith("/") else "/",
        "tag": url if url.startswith("/") else "uknowapp-message",
        "conversation_id": conversation_id,
        "conversation_type": query.get("type", ["conversation"])[0],
    }
    payload = json.dumps(data, ensure_ascii=False)
    admin_payload = (
        json.dumps({**data, "body": admin_body[:160]}, ensure_ascii=False)
        if admin_body is not None else None
    )
    # Fan out immediately into one shared pool, rather than blocking a worker
    # per notification while waiting for every device.
    futures = _submit(targets, payload, admin_payload)
    _RESULT_POOL.submit(_collect, futures)


def _send_one(target, payload, admin_payload):
    attempt_at = datetime.now(UTC)
    state, status = "failed", None
    try:
        if not is_safe_push_endpoint(target["endpoint"]):
            state = "invalid_endpoint"
        else:
            response = webpush(
                subscription_info={"endpoint": target["endpoint"], "keys": target["keys"]},
                data=(admin_payload if target["role"] == "admin" and admin_payload is not None else payload),
                vapid_private_key=vapid.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT},
                ttl=86400, timeout=8,
            )
            status = getattr(response, "status_code", None)
            state = "accepted" if status is None or 200 <= status < 300 else "failed"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        state = "expired" if status in {404, 410} else "failed"
    except Exception as exc:
        # One malformed subscription or provider outage cannot cancel another.
        logger.warning("Web Push attempt failed id=%s type=%s", target["id"], type(exc).__name__)
    if state != "accepted":
        logger.warning("Web Push id=%s state=%s status=%s", target["id"], state, status)
    return target, attempt_at, state, status


def _submit(targets, payload, admin_payload):
    return [_PUSH_POOL.submit(_send_one, target, payload, admin_payload) for target in targets]


def _collect(futures):
    from app.core.database import SessionLocal
    pending = set(futures)
    while pending:
        ready, pending = wait(pending, return_when=FIRST_COMPLETED)
        ready = list(ready)
        for offset in range(0, len(ready), 16):
            try:
                with SessionLocal() as db:
                    for future in ready[offset:offset+16]:
                        _record_result(db, future)
                    db.commit()
            except Exception as exc:
                logger.warning("Web Push diagnostics update failed (%s)", type(exc).__name__)


def _record_result(db, future):
    target, attempted, state, status = future.result()
    if "revision" not in target:
        return
    conditions = (PushSubscription.id == target["id"],
                  PushSubscription.endpoint == target["endpoint"],
                  PushSubscription.revision == target["revision"],
                  PushSubscription.p256dh == target["keys"]["p256dh"],
                  PushSubscription.auth == target["keys"]["auth"])
    values = {"last_attempt_at": attempted, "delivery_state": state, "last_http_status": status}
    db.execute(update(PushSubscription).where(*conditions,
        or_(PushSubscription.last_attempt_at.is_(None), PushSubscription.last_attempt_at <= attempted),
        or_(PushSubscription.delivery_state.is_(None), PushSubscription.delivery_state != "expired")
    ).values(**values))
    if state == "accepted":
        db.execute(update(PushSubscription).where(*conditions,
            or_(PushSubscription.last_success_at.is_(None), PushSubscription.last_success_at <= attempted)
        ).values(last_success_at=attempted))


def _deliver(targets: list[dict], payload: str, admin_payload: str | None = None) -> None:
    """Synchronous test/maintenance entrypoint; network attempts run in parallel."""
    _collect(_submit(targets, payload, admin_payload))
