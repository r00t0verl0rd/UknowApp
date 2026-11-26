"""School business operations exposed through a provider-neutral authenticated transport."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import begin_serialized_write
from app.infrastructure.storage.media import provider_attachment_limit, safe_media_type
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.models import (
    Assignment,
    BotEventReceipt,
    Conversation,
    ExternalEndpoint,
    Message,
    MessengerAccount,
    User,
)
from app.modules.communication.accounts import (
    claim_messenger_connection_code,
    get_messenger_user,
)
from app.modules.communication.outbox import (
    PENDING,
    claim_is_recent,
    earlier_send_pending,
    enqueue_web_delivery,
    get_job,
    job_payload,
    now_utc,
    record_result,
)
from app.modules.conversations.service import (
    conversation_dicts,
    message_preview,
    publish_conversation_update,
    unread_condition,
)
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.messaging.read_state import mark_conversation_read
from app.modules.notifications.content import PUSH_TITLE, push_body
from app.modules.notifications.service import schedule_push
from app.rate_limit import SlidingWindowLimiter

from .contracts import encode, identifier

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
        raise TypeError("conversation id required")
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
    endpoint.chat_id, endpoint.thread_id = chat, thread
    return endpoint


def summaries(db, user):
    items = conversation_dicts(db, available(db, user), include_messenger_accounts=False, viewer_role=user.role)
    previews = {}
    if items:
        ranked = select(Message.id.label("id"), Message.conversation_id,
            func.row_number().over(partition_by=Message.conversation_id, order_by=Message.id.desc()).label("rank")
        ).where(Message.conversation_id.in_([i["id"] for i in items]),
                Message.delivery_status != "blocked_contact", unread_condition(db, user.role)).subquery()
        rows = db.scalars(select(Message).join(ranked, Message.id == ranked.c.id)
                          .where(ranked.c.rank <= 3).order_by(Message.id)).all()
        for row in rows:
            previews.setdefault(row.conversation_id, []).append(message_preview(row)[:115])
    result = [{"id": item["id"], "name": item["student" if user.role == "teacher" else "teacher"]["full_name"],
               "unread": item["unread_count"], "last_message": item["last_message"][:115],
               "last_at": item["last_message_at"] or item["created_at"],
               "unread_previews": previews.get(item["id"], [])} for item in items]
    return sorted(result, key=lambda i: (i["unread"] > 0, i["last_at"]), reverse=True)


def chat_view(db, user, conversation, read=False):
    rows = list(reversed(db.scalars(select(Message).where(
        Message.conversation_id == conversation.id).order_by(Message.id.desc()).limit(12)).all()))
    if read:
        mark_conversation_read(db, conversation, {"role": user.role, "user_id": user.id}, 0, [r.id for r in rows])
    total = db.scalar(select(Conversation.message_count).where(Conversation.id == conversation.id))
    return {"id": conversation.id, "name": (conversation.student if user.role == "teacher" else conversation.teacher).full_name,
            "total": total,
            "messages": [{"id": r.id, "name": "Вы" if r.sender_id == user.id else r.sender.full_name,
                          "text": r.text[:1000], "preview": message_preview(r)[:115],
                          "kind": r.content_type} for r in rows]}


def authorize_delivery(db, platform, job_id, claim=None):
    if claim is not None and (not isinstance(claim, str) or len(claim) != 32 or not all(c in "0123456789abcdef" for c in claim)):
        raise HTTPException(400, "invalid claim")
    if db.info.get("gateway_runtime"):
        begin_serialized_write(db)
    job = get_job(db, identifier(job_id), for_update=True)
    if not job or job.platform != platform or job.status not in PENDING:
        raise HTTPException(404, "job unavailable")
    same_claim = bool(claim and job.claim_id == claim)
    if job.status == "sending" and not same_claim:
        # No second external attempt if a receipt was lost with the connector volume.
        # Recent claims may still be executing; let them finish.
        raise HTTPException(425 if claim_is_recent(job) else 409, "delivery already claimed")
    if earlier_send_pending(db, job):
        raise HTTPException(425, "earlier delivery pending")
    result = job_payload(db, job)
    if result is None:
        record_result(db, job, "cancelled")
        raise HTTPException(403, "job no longer authorized")
    size = (result.get("media") or {}).get("file_size")
    if isinstance(size, int) and size > provider_attachment_limit(platform):
        record_result(db, job, "failed")
        raise HTTPException(413, "attachment exceeds provider limit")
    # The four-job batch must fit inside the wire frame even with legacy rows.
    if len(encode(result)) > 60 * 1024:
        record_result(db, job, "failed")
        raise HTTPException(413, "delivery payload too large")
    job.status = "sending"
    job.started_at = now_utc()
    job.claim_id = claim
    db.commit()
    return result


def rpc(db, platform, operation, payload):
    if operation == "delivery.authorize":
        return authorize_delivery(db, platform, payload.get("id"), payload.get("claim"))
    if operation == "delivery.authorize_batch":
        items = payload.get("jobs")
        if not isinstance(items, list) or not 1 <= len(items) <= 4:
            raise HTTPException(400, "invalid batch")
        result = {}
        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(400, "invalid batch item")
            job_id = identifier(item.get("id"))
            try:
                result[job_id] = {"ok": True, "result": authorize_delivery(db, platform, job_id, item.get("claim"))}
            except HTTPException as exc:
                # A failed item may still hold a writer reservation.
                db.rollback()
                result[job_id] = {"ok": False, "code": exc.status_code}
        return result

    if operation == "endpoint.student_candidates":
        # Only the authenticated Telegram connector needs IDs for getChatMember.
        # Include already bound and inactive students to detect ambiguous groups.
        if platform != "telegram":
            raise HTTPException(403, "operation unavailable")
        after = payload.get("after", 0)
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise HTTPException(400, "invalid cursor")
        rows = db.execute(select(MessengerAccount.id, MessengerAccount.external_user_id)
                          .join(User, User.id == MessengerAccount.user_id)
                          .where(MessengerAccount.platform == platform, MessengerAccount.status == "linked",
                                 User.role == "student", MessengerAccount.id > after)
                          .order_by(MessengerAccount.id).limit(201)).all()
        return {"actors": [row[1] for row in rows[:200]],
                "next": rows[199][0] if len(rows) > 200 else None}

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
        chat = identifier(payload.get("chat_id"))
        thread = identifier(payload["thread_id"]) if payload.get("thread_id") else ""
        if payload.get("initial_only") is True:
            if user.role != "student" or not available(db, user) or not thread:
                raise HTTPException(403, "endpoint unavailable")
            existing = db.get(ExternalEndpoint, (platform, user.id))
            if existing is not None:
                # A service event must never move a previously authorized route.
                return {"bound": existing.chat_id == chat and existing.thread_id == thread}
        bind_endpoint(db, platform, user, chat, thread)
        db.commit()
        return {"bound": True}
    if operation in {"conversation.open", "conversation.peek"}:
        conversation = visible(db, user, payload.get("conversation_id"))
        return chat_view(db, user, conversation, read=operation == "conversation.open")
    if operation == "panel.sync":
        items = summaries(db, user)
        selected = payload.get("conversation_id")
        current = next((i for i in items if i["id"] == selected), None)
        return {"account": identity(user), "conversations": items,
                "chat": chat_view(db, user, visible(db, user, selected)) if current else None}
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
    group = payload.get("channel") == "group"
    if group:
        if user.role != "student" or (platform == "telegram" and not thread):
            raise HTTPException(403, "group sender unavailable")
    elif payload.get("channel") != "private":
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
    if group:
        endpoint = db.get(ExternalEndpoint, (platform, user.id))
        same_route = endpoint is not None and endpoint.chat_id == chat and endpoint.thread_id == thread
        if not same_route:
            if endpoint is not None and platform != "telegram":
                raise HTTPException(403, "group not linked")
            # Bind only on a real, non-replayed inbound message from the linked
            # student. A blocked message cannot change a Telegram delivery route.
            if platform != "telegram" or not blocked:
                bind_endpoint(db, platform, user, chat, thread)
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
