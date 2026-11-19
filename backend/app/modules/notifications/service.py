"""Web Push delivery for authenticated UknowApp accounts."""

import asyncio
import json
import logging
import threading
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

from pywebpush import WebPushException, webpush
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.config import VAPID_PRIVATE_KEY, VAPID_SUBJECT
from ...models import PushSubscription

logger = logging.getLogger(__name__)


def schedule_push(
    db: Session,
    user_ids: Iterable[int],
    title: str,
    body: str,
    url: str = "/",
    include_admin: bool = False,
) -> None:
    """Queue push delivery without delaying message persistence or Telegram handling."""
    if not VAPID_PRIVATE_KEY:
        return
    ids = {int(user_id) for user_id in user_ids if user_id}
    conditions = [PushSubscription.user_id.in_(ids)] if ids else []
    if include_admin:
        conditions.append(PushSubscription.role == "admin")
    if not conditions:
        return
    subscriptions = db.scalars(
        select(PushSubscription).where(or_(*conditions))
    ).all()
    targets = [
        {
            "id": item.id,
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
    payload = json.dumps({
        "title": title[:120],
        "body": body[:240],
        "url": url if url.startswith("/") else "/",
        "tag": url if url.startswith("/") else "uknowapp-message",
        "conversation_id": conversation_id,
        "conversation_type": query.get("type", ["conversation"])[0],
    }, ensure_ascii=False)
    try:
        asyncio.get_running_loop().create_task(asyncio.to_thread(_deliver, targets, payload))
    except RuntimeError:
        threading.Thread(target=_deliver, args=(targets, payload), daemon=True).start()


def _deliver(targets: list[dict], payload: str) -> None:
    from .database import SessionLocal

    expired_ids = []
    for target in targets:
        try:
            webpush(
                subscription_info={
                    "endpoint": target["endpoint"],
                    "keys": target["keys"],
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=86400,
                timeout=8,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                expired_ids.append(target["id"])
            else:
                logger.warning("Web Push delivery failed (status=%s)", status)
        except Exception as exc:
            logger.warning("Web Push delivery failed (%s)", type(exc).__name__)
    if expired_ids:
        with SessionLocal() as db:
            db.query(PushSubscription).filter(
                PushSubscription.id.in_(expired_ids)
            ).delete(synchronize_session=False)
            db.commit()
