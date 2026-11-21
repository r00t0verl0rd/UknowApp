"""Authenticated, low-latency SSE fan-out for conversation events."""

import asyncio
import json
from itertools import count
from threading import Lock
from typing import Any

_subscribers: dict[asyncio.Queue[str], tuple[asyncio.AbstractEventLoop, dict | None]] = {}
_subscribers_lock = Lock()
_event_ids = count(1)
_QUEUE_SIZE = 64


def subscribe_chat_updates(principal: dict | None = None) -> asyncio.Queue[str]:
    """Subscribe one authenticated panel identity to its own conversation events."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_SIZE)
    with _subscribers_lock:
        _subscribers[queue] = (asyncio.get_running_loop(), principal)
    return queue


def unsubscribe_chat_updates(queue: asyncio.Queue[str]) -> None:
    with _subscribers_lock:
        _subscribers.pop(queue, None)


def _can_receive(principal: dict | None, audience: dict | None) -> bool:
    if principal is None or principal.get("role") == "admin":
        return True
    if audience is None:
        return False

    role = principal.get("role")
    user_id = principal.get("user_id")
    if user_id is None:
        return False
    if role == "teacher":
        return audience.get("teacher_id") == user_id or audience.get("participant_id") == user_id
    if role == "student":
        return audience.get("student_id") == user_id or audience.get("participant_id") == user_id
    return False


def _payload_for_subscriber(payload: dict[str, Any], principal: dict | None) -> str:
    visible = {
        key: value for key, value in payload.items()
        if key not in {"audience", "summary_by_role"}
    }
    summaries = payload.get("summary_by_role") or {}
    if principal:
        summary = summaries.get(principal.get("role"))
        if summary is not None:
            visible["summary"] = summary
    return json.dumps(visible, ensure_ascii=False, separators=(",", ":"))


def _enqueue(queue: asyncio.Queue[str], payload: str, event_id: int) -> None:
    if queue.full():
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(json.dumps({"event_id": event_id, "resync": True}))
        return
    queue.put_nowait(payload)


def publish_chat_update(
    conversation_id: int,
    conversation_type: str = "conversation",
    message_id: int | None = None,
    action: str = "upsert",
    actor_role: str | None = None,
    message_ids: list[int] | None = None,
    sender_role: str | None = None,
    read_at: str | None = None,
    audience: dict | None = None,
    summary_by_role: dict[str, dict] | None = None,
) -> None:
    """Publish one committed state change, scoped to the conversation participants."""
    with _subscribers_lock:
        event_id = next(_event_ids)
        subscribers = tuple(_subscribers.items())

    payload = {
        "event_id": event_id,
        "conversation_id": int(conversation_id),
        "conversation_type": conversation_type,
        "message_id": int(message_id) if message_id is not None else None,
        "action": action,
        "actor_role": actor_role,
        "sender_role": sender_role,
        "message_ids": [int(item) for item in message_ids] if message_ids else [],
        "read_at": read_at,
        "audience": audience,
        "summary_by_role": summary_by_role or {},
    }

    for queue, (loop, principal) in subscribers:
        if not _can_receive(principal, audience):
            continue
        encoded = _payload_for_subscriber(payload, principal)
        try:
            loop.call_soon_threadsafe(_enqueue, queue, encoded, event_id)
        except RuntimeError:
            with _subscribers_lock:
                _subscribers.pop(queue, None)
