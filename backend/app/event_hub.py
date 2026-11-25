"""Bounded in-process SSE recovery hints; business messages remain in Main DB."""

import asyncio
import json
import logging
from time import time_ns
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_subscribers: dict[asyncio.Queue[str], tuple[asyncio.AbstractEventLoop, dict | None]] = {}
_subscribers_lock = Lock()
_event_lock = Lock()
# Microseconds fit a JS safe integer. A new process gets a new cursor range.
_latest_id = time_ns() // 1000
_latest_payload: dict | None = None
_MAX_REPLAY_PAYLOAD_BYTES = 4096
_QUEUE_SIZE = 128


def subscribe_chat_updates(principal: dict | None = None) -> asyncio.Queue[str]:
    """Подписать участника на разрешённые события чатов."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_SIZE)
    with _subscribers_lock:
        _subscribers[queue] = (asyncio.get_running_loop(), principal)
    return queue


def unsubscribe_chat_updates(queue: asyncio.Queue[str]) -> None:
    with _subscribers_lock:
        _subscribers.pop(queue, None)


def _can_receive(principal: dict | None, audience: dict | None) -> bool:
    if principal is None:
        return False
    if principal.get("role") == "admin":
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


def _enqueue(queue: asyncio.Queue[str], payload: str, event_id: int | None) -> None:
    if queue.full():
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # A fresh snapshot restores state after queue overflow.
        resync_payload = {"resync": True}
        if event_id is not None:
            resync_payload["event_id"] = event_id
        queue.put_nowait(json.dumps(resync_payload))
        return
    queue.put_nowait(payload)


def reset_replay():
    """Drop old hints on startup/restore; never reuse a cursor in this process."""
    global _latest_id, _latest_payload
    with _event_lock:
        _latest_id = max(_latest_id + 2, time_ns() // 1000)
        _latest_payload = None


def current_event_id():
    with _event_lock:
        return _latest_id


def _dispatch(payload: dict, event_id: int | None) -> None:
    if event_id is not None:
        payload["event_id"] = event_id
    with _subscribers_lock:
        subscribers = tuple(_subscribers.items())

    for queue, (loop, principal) in subscribers:
        if not _can_receive(principal, payload.get("audience")):
            continue
        encoded = _payload_for_subscriber(payload, principal)
        try:
            loop.call_soon_threadsafe(_enqueue, queue, encoded, event_id)
        except RuntimeError:
            with _subscribers_lock:
                _subscribers.pop(queue, None)


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
    db: Session | None = None,
) -> int:
    """Publish a hint after the caller commits its business transaction (no SQL)."""
    payload = {
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
    global _latest_id, _latest_payload
    # One bounded recovery hint, not a second message history. Serialize dispatch
    # across HTTP and gateway threads so live cursors arrive in order.
    with _event_lock:
        _latest_id += 1
        recovery = {"audience": audience, "resync": True}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        _latest_payload = (recovery if len(payload["message_ids"]) > 512 or
                           len(encoded.encode("utf-8")) > _MAX_REPLAY_PAYLOAD_BYTES
                           else json.loads(encoded))
        _dispatch(payload, _latest_id)
        return _latest_id


def replay_chat_updates(
    db: Session | None,
    principal: dict,
    after_event_id: int,
) -> list[tuple[int, str]]:
    """Replay one hint or request a fresh snapshot. No database access."""
    if after_event_id <= 0:
        return []
    with _event_lock:
        latest_id, latest = _latest_id, _latest_payload
        if after_event_id == latest_id:
            return []
        if latest is None or after_event_id != latest_id - 1:
            return [(latest_id, json.dumps({"event_id": latest_id, "resync": True}))]
        if not _can_receive(principal, latest.get("audience")):
            return []
        payload = {**latest, "event_id": latest_id}
        return [(latest_id, _payload_for_subscriber(payload, principal))]
