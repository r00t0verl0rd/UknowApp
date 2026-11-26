"""Provider-neutral transactional outbox, one job per permitted external address."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from app.infrastructure.storage.message_metadata import (
    encode_message_metadata,
    metadata_with_field,
)
from app.models import (
    ConnectorDeletion,
    ConnectorDelivery,
    Conversation,
    ExternalEndpoint,
    Message,
    MessengerAccount,
)
from app.modules.communication.service import record_messenger_delivery
from app.modules.conversations.service import publish_conversation_update

PENDING = {"queued", "published", "sending"}
TERMINAL = {"delivered", "failed", "unknown", "cancelled"}
RECOVERY_AFTER = timedelta(minutes=15)


def now_utc():
    return datetime.now(UTC)


def as_utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def claim_is_recent(job, now=None):
    return bool(job.started_at and as_utc(job.started_at) > (now or now_utc()) - RECOVERY_AFTER)


def earlier_send_pending(db, job):
    if not isinstance(job, ConnectorDelivery) or job.status == "sending":
        return False
    # Preserve ordering at each external address even after a delayed NAK or reconnect.
    return db.scalar(select(ConnectorDelivery.id).where(
        ConnectorDelivery.platform == job.platform,
        ConnectorDelivery.chat_id == job.chat_id,
        ConnectorDelivery.thread_id == job.thread_id,
        ConnectorDelivery.status.in_(PENDING),
        ConnectorDelivery.id != job.id,
        or_(ConnectorDelivery.created_at < job.created_at,
            and_(ConnectorDelivery.created_at == job.created_at, ConnectorDelivery.id < job.id)),
    ).limit(1)) is not None


def enqueue_web_delivery(db, row, platforms):
    if not platforms:
        return
    conversation = db.get(Conversation, row.conversation_id)
    if conversation is None or conversation.status != "active":
        return
    recipients = []
    if row.sender_role != "student":
        recipients.append(conversation.student_id)
    if row.sender_role != "teacher":
        recipients.append(conversation.teacher_id)
    accounts = db.execute(select(
        MessengerAccount.platform, MessengerAccount.user_id, MessengerAccount.external_user_id,
        MessengerAccount.external_chat_id, ExternalEndpoint.chat_id, ExternalEndpoint.thread_id,
    ).outerjoin(ExternalEndpoint, and_(
        ExternalEndpoint.platform == MessengerAccount.platform,
        ExternalEndpoint.user_id == MessengerAccount.user_id,
    )).where(
        MessengerAccount.user_id.in_(recipients),
        MessengerAccount.platform.in_(platforms),
        MessengerAccount.status == "linked",
    )).all()
    if not accounts:
        return
    metadata = json.loads(row.metadata_json or "{}")
    existing = set(db.execute(select(
        ConnectorDelivery.platform, ConnectorDelivery.recipient_id,
        ConnectorDelivery.chat_id, ConnectorDelivery.thread_id,
    ).where(ConnectorDelivery.message_id == row.id)).tuples())
    existing.update(
        (job.platform, job.recipient_id, job.chat_id, job.thread_id)
        for job in db.new if isinstance(job, ConnectorDelivery) and job.message_id == row.id
    )
    for platform, user_id, external_id, private_chat, group_chat, thread in accounts:
        # The private account and its bound group are independent addresses.
        routes = {(private_chat or external_id, "")}
        if group_chat:
            routes.add((group_chat, thread or ""))
        added = False
        for chat_id, thread_id in sorted(routes):
            key = (platform, user_id, chat_id, thread_id)
            if key in existing:
                continue
            existing.add(key)
            db.add(ConnectorDelivery(id=uuid4().hex, message_id=row.id,
                recipient_id=user_id, platform=platform,
                external_user_id=external_id, chat_id=chat_id,
                thread_id=thread_id, status="queued"))
            added = True
        if added:
            record_messenger_delivery(metadata, platform, status="queued")
    row.metadata_json = encode_message_metadata(metadata)


def authorized_job(db, job):
    if job.message_id is None:
        return None
    row = db.get(Message, job.message_id)
    conversation = db.get(Conversation, row.conversation_id) if row else None
    if not conversation or conversation.status != "active" or not conversation.assignment or not conversation.assignment.active:
        return None
    if job.recipient_id not in (conversation.teacher_id, conversation.student_id):
        return None
    if row.sender_role == "teacher" and row.sender_id != conversation.teacher_id:
        return None
    if row.sender_role == "student" and row.sender_id != conversation.student_id:
        return None
    account = db.scalar(select(MessengerAccount).where(
        MessengerAccount.platform == job.platform, MessengerAccount.user_id == job.recipient_id,
        MessengerAccount.status == "linked", MessengerAccount.external_user_id == job.external_user_id,
    ))
    if account is None:
        return None
    if job.thread_id or job.chat_id != (account.external_chat_id or account.external_user_id):
        endpoint = db.get(ExternalEndpoint, (job.platform, job.recipient_id))
        if not endpoint or endpoint.chat_id != job.chat_id or (endpoint.thread_id or "") != (job.thread_id or ""):
            return None
    return row


def job_payload(db, job):
    if isinstance(job, ConnectorDeletion):
        return {"id": job.id, "operation": "delete", "chat_id": job.chat_id,
                "external_message_id": job.external_message_id}
    row = authorized_job(db, job)
    if row is None:
        return None
    media = (json.loads(row.metadata_json or "{}").get("media") or {})
    sender = row.sender.full_name if row.sender_role != "admin" else "Администратор"
    media_key = hashlib.sha256(str(media.get("local_path", "")).encode()).hexdigest()
    return {"id": job.id, "operation": "send", "chat_id": job.chat_id, "thread_id": job.thread_id or None,
            "recipient": job.external_user_id, "kind": row.content_type,
            "text": sender + ("\n" + row.text if row.text else ""),
            "media": {"file_name": media.get("file_name") or "attachment",
                      "mime_type": media.get("mime_type"), "file_size": media.get("file_size"), "key": media_key if media.get("local_path") else None} if media.get("archive_status") == "stored" else None}


def get_job(db, job_id, *, for_update=False):
    return (db.get(ConnectorDelivery, job_id, with_for_update=for_update)
            or db.get(ConnectorDeletion, job_id, with_for_update=for_update))


def enqueue_deletion(db, platform, chat_id, external_id):
    # IDs are stable across legacy metadata, SQL delivery rows and late receipts.
    chat_id, external_id = str(chat_id), str(external_id)
    ident = hashlib.sha256(json.dumps([platform, chat_id, external_id]).encode()).hexdigest()
    if db.get(ConnectorDeletion, ident) is None:
        db.add(ConnectorDeletion(id=ident, platform=platform, chat_id=chat_id,
                                 external_message_id=external_id, status="queued"))
    return ident


def enqueue_message_deletions(db, row):
    """Detach in-flight sends before deleting the web row; late receipts trigger deletion."""
    metadata = json.loads(row.metadata_json or "{}")
    ledgers = dict(metadata.get("messenger_deliveries") or {})
    copies = set()
    for platform, result in ledgers.items():
        for copy in result.get("delivered", []):
            chat = copy.get("external_chat_id") or copy.get("chat_id")
            ident = copy.get("external_message_id")
            if chat and ident:
                copies.add((platform, str(chat), str(ident)))
    jobs = db.scalars(select(ConnectorDelivery).where(ConnectorDelivery.message_id == row.id)
                      .order_by(ConnectorDelivery.id).with_for_update()).all()
    inflight = 0
    unknown = 0
    for job in jobs:
        if job.external_message_id:
            copies.add((job.platform, job.chat_id, job.external_message_id))
        if job.status == "sending":
            inflight += 1
        elif job.status == "unknown":
            unknown += 1
        elif job.status in {"queued", "published"}:
            job.status = "cancelled"
        job.message_id = None
    for platform, chat, ident in copies:
        enqueue_deletion(db, platform, chat, ident)
    db.flush()
    return len(copies) + inflight, unknown


def record_result(db, job, status, external_id=None, *, external_ids=None):
    if job.status in TERMINAL:
        return
    job.status = status
    if isinstance(job, ConnectorDeletion):
        db.commit()
        return
    ids = external_ids or ([external_id] if external_id else [])
    job.external_message_id = ids[0] if ids else None
    db.flush()
    row = db.get(Message, job.message_id) if job.message_id is not None else None
    if row is None:
        # The original message may have been deleted while the provider request was in flight.
        for ident in ids:
            enqueue_deletion(db, job.platform, job.chat_id, ident)
        db.commit()
        return
    jobs = db.scalars(select(ConnectorDelivery).where(
        ConnectorDelivery.message_id == row.id, ConnectorDelivery.platform == job.platform)).all()
    def address(j):
        return {"user_id": j.recipient_id, "external_chat_id": j.chat_id,
                "external_thread_id": j.thread_id or None,
                "endpoint_type": "group" if j.thread_id else "private"}
    metadata = json.loads(row.metadata_json or "{}")
    # Keep every confirmed part in the existing delivery ledger. The first ID
    # remains in the job row for compatibility with old single-copy receipts.
    previous = metadata.get("messenger_deliveries", {}).get(job.platform, {}).get("delivered", [])
    delivered = {}
    for copy in previous + [
        {**address(j), "external_message_id": j.external_message_id}
        for j in jobs if j.external_message_id
    ] + [{**address(job), "external_message_id": ident} for ident in ids]:
        if copy.get("external_chat_id") and copy.get("external_message_id"):
            delivered[(str(copy["external_chat_id"]), str(copy["external_message_id"]))] = copy
    delivered = list(delivered.values())
    errors = [{**address(j), "reason": j.status}
              for j in jobs if j.status in {"failed", "unknown", "cancelled"}]
    states = {j.status for j in jobs}
    status = ("queued" if states & PENDING else
              "partial" if delivered and errors else "delivered" if delivered else
              "unknown" if "unknown" in states else "failed")
    record_messenger_delivery(metadata, job.platform, delivered, errors, status)
    db.execute(update(Message).where(Message.id == row.id).values(
        metadata_json=metadata_with_field(db, Message.metadata_json, "messenger_deliveries", metadata["messenger_deliveries"])
    ), execution_options={"synchronize_session": False})
    db.expire(row, ["metadata_json"])
    db.commit()
    conversation = db.get(Conversation, row.conversation_id)
    if conversation:
        publish_conversation_update(db, conversation, message_id=row.id, action="delivery", sender_role=row.sender_role,
            admin_message_status={"id": row.id, "metadata": {"messenger_deliveries": metadata["messenger_deliveries"]}})
