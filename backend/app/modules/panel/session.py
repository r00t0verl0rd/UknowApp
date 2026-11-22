"""Сессия и поток событий веб-панели."""

import asyncio
import json
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse

from app.event_hub import (
    replay_chat_updates,
    subscribe_chat_updates,
    unsubscribe_chat_updates,
)
from app.models import (
    User,
)
from app.modules.dependencies import Db, PanelUser

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/me")
def panel_me(principal: PanelUser, db: Db):
    if principal["role"] == "admin":
        return {"role": "admin", "full_name": "Администратор"}
    user = db.get(User, principal["user_id"])
    if (
        not user
        or user.role != principal["role"]
        or user.role not in {"teacher", "student"}
    ):
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"role": user.role, "id": user.id, "full_name": user.full_name}


@router.get("/panel/events")
async def panel_events(request: Request, principal: PanelUser, db: Db):
    """Передавать события и восстанавливать пропущенные."""
    queue = subscribe_chat_updates(principal)
    try:
        cursor = int(request.headers.get("last-event-id", "0") or 0)
    except ValueError:
        cursor = 0
    replay = replay_chat_updates(db, principal, cursor) if cursor else []
    # Не удерживаем соединение с БД во время SSE-подписки.
    db.rollback()

    async def event_stream():
        try:
            yield "retry: 1500\n\n"
            for event_id, payload in replay:
                yield f"id: {event_id}\nevent: update\ndata: {payload}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                try:
                    event_id = json.loads(payload).get("event_id")
                except (TypeError, ValueError):
                    event_id = None
                if event_id is not None:
                    yield f"id: {event_id}\n"
                yield "event: update\ndata: " + payload + "\n\n"
        finally:
            unsubscribe_chat_updates(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
