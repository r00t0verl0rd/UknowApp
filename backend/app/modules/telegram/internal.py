"""Private primary-server inbox for the remote Telegram gateway.

No public login/session cookies are accepted here. The gateway has a separate
random credential and requests are bounded before JSON parsing. An accepted
update is committed to SQLite before the gateway receives HTTP 202.
"""
import asyncio
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Dispatcher
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.core.config import TELEGRAM_GATEWAY_TOKEN
from app.core.database import SessionLocal
from .inbox import TelegramUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/internal/telegram")
MAX_UPDATE_SIZE = 2 * 1024 * 1024


@router.post("/updates", status_code=202)
async def accept_update(request: Request):
    if not TELEGRAM_GATEWAY_TOKEN or len(TELEGRAM_GATEWAY_TOKEN) < 32:
        raise HTTPException(503, "Telegram gateway is not configured")
    provided = request.headers.get("x-uknow-gateway-key", "")
    if not hmac.compare_digest(provided, TELEGRAM_GATEWAY_TOKEN):
        raise HTTPException(401, "Unauthorized")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPDATE_SIZE:
            raise HTTPException(413, "Update too large")
    try:
        payload = json.loads(body)
        update_id = payload["update_id"]
        if not isinstance(update_id, int) or isinstance(update_id, bool) or not isinstance(payload, dict):
            raise ValueError("Invalid Telegram update")
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid Telegram update") from None

    with SessionLocal() as db:
        if db.get(TelegramUpdate, update_id) is None:
            db.add(TelegramUpdate(update_id=update_id, payload=body.decode("utf-8")))
            db.commit()
    return {"accepted": True, "update_id": update_id}


async def process_update_inbox(bot, dispatcher: Dispatcher, stop: asyncio.Event) -> None:
    """Serial processing preserves message order and protects SQLite writes.

    A crash between Telegram side effects and marking the update complete can
    repeat that update. Message persistence already deduplicates by source ID;
    other side effects should be treated as at-least-once during migration.
    """
    while not stop.is_set():
        with SessionLocal() as db:
            now = datetime.now(UTC).replace(tzinfo=None)
            pending = db.scalar(
                select(TelegramUpdate)
                .where(TelegramUpdate.state == "pending")
                .order_by(TelegramUpdate.update_id)
                .limit(1)
            )
            # Do not process later updates ahead of an earlier failing update:
            # teacher selection and replies depend on message order.
            if pending and pending.next_attempt_at is not None:
                retry_at = pending.next_attempt_at.replace(tzinfo=None)
                if retry_at > now:
                    pending = None
            update_id = pending.update_id if pending else None
            payload = pending.payload if pending else None

        if update_id is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass
            continue

        try:
            await dispatcher.feed_raw_update(bot, json.loads(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Telegram inbound update failed (update_id=%s type=%s)", update_id, type(exc).__name__)
            with SessionLocal() as db:
                item = db.get(TelegramUpdate, update_id)
                if item:
                    item.attempts += 1
                    item.next_attempt_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=min(300, 2 ** min(item.attempts, 8)))
                    db.commit()
        else:
            with SessionLocal() as db:
                item = db.get(TelegramUpdate, update_id)
                if item:
                    item.state = "done"
                    item.payload = "{}"
                    item.next_attempt_at = None
                    db.commit()
