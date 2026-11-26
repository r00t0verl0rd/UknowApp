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
from sqlalchemy import select

from app.core.database import SessionLocal
from app.event_hub import (
    current_event_id,
    replay_ram_updates,
    subscribe_chat_updates,
    unsubscribe_chat_updates,
)
from app.infrastructure.storage.media import panel_attachment_limit
from app.models import Message, PersonalMessage
from app.modules.auth.permissions import ROLE_PERMISSIONS
from app.modules.auth.service import load_panel_identity
from app.modules.dependencies import PanelUser
from app.modules.messaging.service import panel_message_dict, panel_visible_conversation
from app.modules.personal_chat.operations import personal_message_dict
from app.modules.personal_chat.service import personal_conversation

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/me")
def panel_me(principal: PanelUser):
    permissions = sorted(ROLE_PERMISSIONS[principal["role"]])
    max_attachment_bytes = panel_attachment_limit()
    if principal["role"] == "admin":
        return {"permissions": permissions, "role": "admin", "full_name": "Администратор",
                "max_attachment_bytes": max_attachment_bytes}
    # Authentication already checked the current role, password fingerprint and name.
    return {"permissions": permissions, "role": principal["role"],
            "id": principal["user_id"], "full_name": principal["full_name"],
            "max_attachment_bytes": max_attachment_bytes}


def visible_payload(db, principal, payload):
    event = json.loads(payload)
    if event.get("resync"):
        return json.dumps({"resync": True})
    lookup = {"conversation": panel_visible_conversation, "personal": personal_conversation}.get(event.get("conversation_type"))
    if lookup:
        try:
            lookup(db, principal, event["conversation_id"])
            # Hydrate only after checking this subscriber's current access.
            # RAM keeps small hints, not another copy of chat history.
            if event.get("action") == "upsert" and event.get("message_id"):
                model = PersonalMessage if event["conversation_type"] == "personal" else Message
                row = db.get(model, event["message_id"])
                if row is not None and row.conversation_id == event["conversation_id"]:
                    event["message"] = (
                        personal_message_dict(row, principal) if model is PersonalMessage else
                        panel_message_dict(row, expose_internal_metadata=principal["role"] == "admin",
                                           principal=principal)
                    )
                    # Global message IDs need not be consecutive within a chat.
                    # This indexed predecessor detects missing updates without
                    # requiring a full history request for each new message.
                    event["previous_message_id"] = db.scalar(
                        select(model.id).where(model.conversation_id == row.conversation_id,
                                               model.id < row.id)
                        .order_by(model.id.desc()).limit(1)
                    )
                    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))
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
    replay = replay_ram_updates(principal, cursor)

    def authorized_payload(payload=None):
        current = load_panel_identity(request)
        if not current or (current["role"], current["user_id"]) != (principal["role"], principal["user_id"]):
            return None
        if payload is None:
            return True
        if json.loads(payload).get("resync"):
            return json.dumps({"resync": True})
        with SessionLocal() as session:
            return visible_payload(session, principal, payload)

    async def event_stream():
        try:
            yield "retry: 1500\n\n"
            if not cursor:
                yield f"id: {checkpoint}\nevent: checkpoint\ndata: {{}}\n\n"
            for event_id, payload in replay:
                payload = await asyncio.to_thread(authorized_payload, payload)
                if payload is None:
                    return
                yield f"id: {event_id}\nevent: update\ndata: {payload}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if not await asyncio.to_thread(authorized_payload):
                        return
                    # A named heartbeat is observable by the client watchdog.
                    # It has no ID and cannot advance the replay cursor.
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                try:
                    event_id = json.loads(payload).get("event_id")
                except (TypeError, ValueError):
                    event_id = None
                payload = await asyncio.to_thread(authorized_payload, payload)
                if payload is None:
                    return
                # Send each complete SSE frame in a single transport write.
                prefix = f"id: {event_id}\n" if event_id is not None else ""
                yield prefix + "event: update\ndata: " + payload + "\n\n"
        finally:
            unsubscribe_chat_updates(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
