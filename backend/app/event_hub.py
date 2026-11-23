"""События переписок с хранением и проверкой доступа."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from itertools import count
from threading import Lock
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RealtimeEvent

logger = logging.getLogger(__name__)

_subscribers: dict[asyncio.Queue[str], tuple[asyncio.AbstractEventLoop, dict | None]] = {}
_subscribers_lock = Lock()
_fallback_event_ids = count(1)
_QUEUE_SIZE = 128
_REPLAY_LIMIT = 1000
_EVENT_RETENTION_DAYS = 14


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
        # Журнал БД позволяет восстановить события после переполнения очереди.
        resync_payload = {"resync": True}
        if event_id is not None:
            resync_payload["event_id"] = event_id
        queue.put_nowait(json.dumps(resync_payload))
        return
    queue.put_nowait(payload)


def _persist_event(db: Session, conversation_id: int, conversation_type: str, payload: dict) -> int:
    event = RealtimeEvent(
        conversation_id=int(conversation_id),
        conversation_type=conversation_type,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        created_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    event_id = event.id
    db.commit()

    # Ограничиваем повтор событий и не очищаем журнал при каждой отправке.
    if event_id % 100 == 0:
        cutoff = datetime.now(UTC) - timedelta(days=_EVENT_RETENTION_DAYS)
        db.execute(delete(RealtimeEvent).where(RealtimeEvent.created_at < cutoff))
        db.commit()
    return event_id


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
) -> None:
    """Сохранить событие до оповещения подписчиков."""
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
    event_id: int
    if db is not None:
        try:
            event_id = _persist_event(db, conversation_id, conversation_type, payload)
        except Exception:
            db.rollback()
            logger.exception(
                "Realtime event persistence failed (conversation_id=%s action=%s)",
                conversation_id,
                action,
            )
            event_id = None
            payload["resync"] = True
    else:
        # Используется в тестах и внутренних сигналах без БД.
        event_id = next(_fallback_event_ids)

    _dispatch(payload, event_id)


def replay_chat_updates(
    db: Session,
    principal: dict,
    after_event_id: int,
) -> list[tuple[int, str]]:
    """Восстановить доступные события после переподключения."""
    if after_event_id <= 0:
        return []

    oldest_id = db.scalar(select(func.min(RealtimeEvent.id)))
    latest_id = db.scalar(select(func.max(RealtimeEvent.id))) or after_event_id
    if oldest_id is not None and after_event_id < oldest_id - 1:
        payload = json.dumps({"event_id": int(latest_id), "resync": True})
        return [(int(latest_id), payload)]

    rows = db.scalars(
        select(RealtimeEvent)
        .where(RealtimeEvent.id > after_event_id)
        .order_by(RealtimeEvent.id)
        .limit(_REPLAY_LIMIT + 1),
    ).all()
    if len(rows) > _REPLAY_LIMIT:
        latest_id = rows[-1].id
        payload = json.dumps({"event_id": int(latest_id), "resync": True})
        return [(int(latest_id), payload)]

    replay: list[tuple[int, str]] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            continue
        if not _can_receive(principal, payload.get("audience")):
            continue
        payload["event_id"] = row.id
        replay.append((
            row.id,
            _payload_for_subscriber(payload, principal),
        ))
    return replay
