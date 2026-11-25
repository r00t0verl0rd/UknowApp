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

from app.core.database import SessionLocal
from app.event_hub import (
    current_event_id,
    replay_chat_updates,
    subscribe_chat_updates,
    unsubscribe_chat_updates,
)
from app.models import User
from app.modules.auth.permissions import ROLE_PERMISSIONS
from app.modules.auth.service import _load_panel_identity
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.service import _panel_visible_conversation
from app.modules.personal_chat.service import _personal_conversation

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/me")
def panel_me(principal: PanelUser, db: Db):
    permissions = sorted(ROLE_PERMISSIONS[principal["role"]])
    if principal["role"] == "admin":
        return {"permissions": permissions, "role": "admin", "full_name": "Администратор"}
    user = db.get(User, principal["user_id"])
    if (
        not user
        or user.role != principal["role"]
        or user.role not in {"teacher", "student"}
    ):
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"permissions": permissions, "role": user.role, "id": user.id, "full_name": user.full_name}


def visible_payload(db, principal, payload):
    event = json.loads(payload)
    if event.get("resync"):
        return json.dumps({"resync": True})
    lookup = {"conversation": _panel_visible_conversation, "personal": _personal_conversation}.get(event.get("conversation_type"))
    if lookup:
        try:
            lookup(db, principal, event["conversation_id"])
            return payload
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    return json.dumps({"resync": True})


@router.get("/panel/events")
async def panel_events(request: Request, principal: PanelUser):
    """Передавать события и восстанавливать пропущенные."""
    queue = subscribe_chat_updates(principal)
    try:
        cursor = int(request.headers.get("last-event-id", "0") or 0)
    except ValueError:
        cursor = 0
    # Subscribe before taking the RAM checkpoint; any overlap is harmless and
    # clients ignore duplicate event IDs.
    checkpoint = current_event_id()
    replay = replay_chat_updates(None, principal, cursor)

    def filter_event(payload):
        with SessionLocal() as session:
            return visible_payload(session, principal, payload)

    async def still_authorized():
        current = await asyncio.to_thread(_load_panel_identity, request)
        return current and (current["role"], current["user_id"]) == (principal["role"], principal["user_id"])

    async def event_stream():
        try:
            yield "retry: 1500\n\n"
            if not cursor:
                yield f"id: {checkpoint}\nevent: checkpoint\ndata: {{}}\n\n"
            for event_id, payload in replay:
                if not await still_authorized():
                    return
                payload = await asyncio.to_thread(filter_event, payload)
                yield f"id: {event_id}\nevent: update\ndata: {payload}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if not await still_authorized():
                        return
                    yield ": keep-alive\n\n"
                    continue
                if not await still_authorized():
                    return
                try:
                    event_id = json.loads(payload).get("event_id")
                except (TypeError, ValueError):
                    event_id = None
                if event_id is not None:
                    yield f"id: {event_id}\n"
                payload = await asyncio.to_thread(filter_event, payload)
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
