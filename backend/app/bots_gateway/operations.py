"""School business operations exposed through a provider-neutral authenticated transport."""
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.storage.media import safe_media_type
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.models import Assignment, BotEventReceipt, ConnectorDelivery, Conversation, ExternalEndpoint, Message
from app.modules.communication.accounts import claim_messenger_connection_code, get_messenger_user
from app.modules.conversations.service import conversation_dicts, publish_conversation_update
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.notifications.content import PUSH_TITLE, push_body
from app.modules.notifications.service import schedule_push
from app.modules.panel.read_state import mark_conversation_read
from app.rate_limit import SlidingWindowLimiter
from .contracts import identifier
from .outbox import enqueue_web_delivery, job_payload, record_result

_bind_limit = SlidingWindowLimiter()
KINDS = frozenset(("text", "photo", "video", "audio", "voice", "document", "animation",
                   "sticker", "location", "contact", "video_note", "poll", "unsupported"))


def identity(user):
    return {"id": user.id, "name": user.full_name, "role": user.role}


def available(db, user):
    query = select(Conversation).join(Assignment, Conversation.assignment_id == Assignment.id).where(
        Assignment.active.is_(True), Conversation.status == "active")
    if user.role == "teacher":
        query = query.where(Conversation.teacher_id == user.id)
    elif user.role == "student":
        query = query.where(Conversation.student_id == user.id)
    else:
        return []
    return db.scalars(query.order_by(Conversation.id.desc())).all()


def visible(db, user, conversation_id):
    if not isinstance(conversation_id, int) or isinstance(conversation_id, bool):
        raise ValueError("conversation id required")
    row = db.get(Conversation, conversation_id)
    if (row is None or row.status != "active" or not row.assignment or not row.assignment.active or
        (user.role == "teacher" and row.teacher_id != user.id) or
        (user.role == "student" and row.student_id != user.id) or user.role not in {"teacher", "student"}):
        raise HTTPException(403, "conversation unavailable")
    return row


def bind_endpoint(db, platform, user, chat, thread):
    if user.role != "student" or not available(db, user):
        raise HTTPException(403, "endpoint unavailable")
    occupied = db.scalar(select(ExternalEndpoint).where(
        ExternalEndpoint.platform == platform, ExternalEndpoint.chat_id == chat,
        ExternalEndpoint.thread_id == thread))
    if occupied and occupied.user_id != user.id:
        raise HTTPException(409, "endpoint already linked")
    endpoint = db.get(ExternalEndpoint, (platform, user.id))
    if endpoint is None:
        endpoint = ExternalEndpoint(platform=platform, user_id=user.id)
        db.add(endpoint)
    endpoint.chat_id, endpoint.thread_id, endpoint.preferred = chat, thread, True
    return endpoint


def summaries(db, user):
    return [{"id": item["id"], "name": item["student" if user.role == "teacher" else "teacher"]["full_name"],
             "unread": item["unread_count"], "last_message": item["last_message"]}
            for item in conversation_dicts(db, available(db, user), include_telegram_ids=False, viewer_role=user.role)]


def rpc(db, platform, operation, payload):
    if operation == "delivery.authorize":
        job = db.get(ConnectorDelivery, identifier(payload.get("id")))
        if not job or job.platform != platform or job.status not in {"queued", "published"}:
            raise HTTPException(404, "job unavailable")
        result = job_payload(db, job)
        if result is None:
            record_result(db, job, "cancelled")
            raise HTTPException(403, "job no longer authorized")
        return result

    actor = identifier(payload.get("actor"))
    user = get_messenger_user(db, platform, actor)
    if operation == "account.bind":
        if not _bind_limit.allow_and_record((platform, actor), 5, 900):
            raise HTTPException(429, "too many attempts")
        if user is not None:
            return {"account": identity(user), "conversations": summaries(db, user)}
        user, result = claim_messenger_connection_code(
            db, str(payload.get("code", ""))[:32], platform, actor,
            identifier(payload.get("chat_id")), str(payload.get("username") or "")[:255] or None)
        if user is None:
            return {"account": None, "reason": result}
    if operation in {"account.resolve", "account.bind", "conversation.list"}:
        return {"account": identity(user) if user else None,
                "conversations": summaries(db, user) if user else []}
    if user is None:
        raise HTTPException(403, "account not linked")
    if operation == "endpoint.bind":
        bind_endpoint(db, platform, user, identifier(payload.get("chat_id")),
                      identifier(payload["thread_id"]) if payload.get("thread_id") else "")
        db.commit()
        return {"bound": True}
    if operation == "conversation.open":
        conversation = visible(db, user, payload.get("conversation_id"))
        rows = list(reversed(db.scalars(select(Message).where(
            Message.conversation_id == conversation.id).order_by(Message.id.desc()).limit(12)).all()))
        mark_conversation_read(db, conversation, {"role": user.role, "user_id": user.id}, 0, [r.id for r in rows])
        return {"id": conversation.id, "name": (conversation.student if user.role == "teacher" else conversation.teacher).full_name,
                "messages": [{"id": r.id, "name": r.sender.full_name, "text": r.text[:1000],
                              "kind": r.content_type} for r in rows]}
    raise HTTPException(404, "unknown operation")


def receive_message(db, platform, payload, enabled_platforms, media_path):
    event_id = identifier(payload.get("id"))
    if len(event_id) > 200:
        raise ValueError("event ID too long")
    if db.get(BotEventReceipt, (platform, event_id)):
        return
    user = get_messenger_user(db, platform, identifier(payload.get("actor")))
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(403, "account unavailable")
    if user.role == "student":
        choices = available(db, user)
        if not choices:
            raise HTTPException(403, "no assigned conversation")
        conversation = choices[0]
    else:
        conversation = visible(db, user, payload.get("conversation_id"))
    chat = identifier(payload.get("chat_id"))
    thread = identifier(payload["thread_id"]) if payload.get("thread_id") else ""
    endpoint = db.get(ExternalEndpoint, (platform, user.id))
    if payload.get("channel") == "group":
        if user.role != "student":
            raise HTTPException(403, "group sender unavailable")
        if endpoint is None:
            # Adapter has already checked provider-specific group visibility.
            endpoint = bind_endpoint(db, platform, user, chat, thread)
        if endpoint.chat_id != chat or endpoint.thread_id != thread:
            raise HTTPException(403, "group not linked")
        endpoint.preferred = True
    elif payload.get("channel") == "private":
        if endpoint:
            endpoint.preferred = False
    else:
        raise ValueError("unknown channel type")
    external_message_id = identifier(payload.get("external_message_id", event_id))
    source_event = f"{platform}:{chat}:{external_message_id}"
    if len(source_event) > 255:
        raise ValueError("source event too long")
    if db.scalar(select(Message.id).where(Message.sender_id == user.id,
                 Message.source_platform == platform, Message.source_event_id == source_event)):
        db.add(BotEventReceipt(platform=platform, event_id=event_id))
        db.commit()
        return
    kind = payload.get("kind", "text")
    if kind not in KINDS:
        raise ValueError("unknown message kind")
    text = payload.get("text", "")
    if not isinstance(text, str) or len(text) > 12000:
        raise ValueError("invalid message text")
    if kind == "text" and not text.strip():
        raise ValueError("empty text")
    blocked = kind == "contact" or text_contains_contact_data(text)
    metadata = {"source_mode": "group_topic" if payload.get("channel") == "group" else "private",
                "source_chat_id": chat, "source_thread_id": thread or None, "source_platform": platform}
    media = payload.get("media")
    if media and not blocked:
        path, storage_key = media_path(platform, event_id)
        if not path.is_file():
            raise ValueError("media not uploaded")
        filename = str(media.get("file_name") or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
        metadata["media"] = {"kind": kind, "file_name": filename[:180],
            "mime_type": safe_media_type(media.get("mime_type")), "file_size": path.stat().st_size,
            "local_path": storage_key, "archive_status": "stored"}
    if payload.get("media_unavailable") and not blocked:
        metadata["media"] = {"kind": kind, "archive_status": "download_failed"}
    if blocked and media:
        path, _ = media_path(platform, event_id)
        path.unlink(missing_ok=True)
    if kind == "location" and isinstance(payload.get("location"), dict):
        metadata["location"] = payload["location"]
    if kind == "poll" and isinstance(payload.get("poll"), dict):
        metadata["poll"] = payload["poll"]
    row = Message(conversation_id=conversation.id, sender_id=user.id, sender_role=user.role,
        content_type=kind, text="[Контактные данные скрыты системой]" if blocked else text,
        metadata_json=encode_message_metadata(metadata), delivery_status="blocked_contact" if blocked else "delivered",
        source_platform=platform, source_event_id=source_event)
    db.add(row)
    db.add(BotEventReceipt(platform=platform, event_id=event_id))
    try:
        db.flush()
        if not blocked:
            enqueue_web_delivery(db, row, enabled_platforms)
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.get(BotEventReceipt, (platform, event_id)):
            return
        raise
    publish_conversation_update(db, conversation, message_id=row.id, sender_role=user.role)
    receiver = conversation.teacher if user.role == "student" else conversation.student
    schedule_push(db, [receiver.id], PUSH_TITLE, push_body(user.full_name, row.text, kind=kind),
                  f"/?openConversation={conversation.id}", include_admin=True,
                  admin_body=push_body(user.full_name, row.text, recipient_name=receiver.full_name, kind=kind))
