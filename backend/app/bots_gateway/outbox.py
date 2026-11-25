"""SQL transactional outbox: durable per-recipient delivery, independent of providers."""
import json
from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.models import ConnectorDelivery, Conversation, ExternalEndpoint, Message, MessengerAccount
from app.modules.communication.service import record_messenger_delivery
from app.modules.conversations.service import publish_conversation_update


def uses_outbox(app):
    gateway = getattr(app.state, "bots_gateway", None)
    return gateway is not None and bool(gateway.platforms)


def enqueue_web_delivery(db, row, platforms):
    conversation = db.get(Conversation, row.conversation_id)
    if conversation is None or conversation.status != "active":
        return
    recipients = []
    if row.sender_role != "student":
        recipients.append(conversation.student_id)
    if row.sender_role != "teacher":
        recipients.append(conversation.teacher_id)
    accounts = db.scalars(select(MessengerAccount).where(
        MessengerAccount.user_id.in_(recipients),
        MessengerAccount.platform.in_(platforms),
        MessengerAccount.status == "linked",
    )).all()
    metadata = json.loads(row.metadata_json or "{}")
    for account in accounts:
        endpoint = db.get(ExternalEndpoint, (account.platform, account.user_id))
        # Reuse an explicitly bound endpoint only when it is the preferred route.
        endpoint = endpoint if endpoint and endpoint.preferred else None
        db.add(ConnectorDelivery(id=uuid4().hex, message_id=row.id,
            recipient_id=account.user_id, platform=account.platform,
            external_user_id=account.external_user_id,
            chat_id=endpoint.chat_id if endpoint else (account.external_chat_id or account.external_user_id),
            thread_id=(endpoint.thread_id or None) if endpoint else None,
            status="queued"))
        record_messenger_delivery(metadata, account.platform, status="queued")
    row.metadata_json = encode_message_metadata(metadata)


def authorized_job(db, job):
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
        if not endpoint or endpoint.chat_id != job.chat_id or (endpoint.thread_id or None) != job.thread_id:
            return None
    return row


def job_payload(db, job):
    row = authorized_job(db, job)
    if row is None:
        return None
    media = (json.loads(row.metadata_json or "{}").get("media") or {})
    sender = row.sender.full_name if row.sender_role != "admin" else "Администратор"
    return {"id": job.id, "chat_id": job.chat_id, "thread_id": job.thread_id,
            "recipient": job.external_user_id, "kind": row.content_type,
            "text": sender + ("\n" + row.text if row.text else ""),
            "media": {"file_name": media.get("file_name") or "attachment",
                      "mime_type": media.get("mime_type")} if media.get("archive_status") == "stored" else None}


def record_result(db, job, status, external_id=None):
    if job.status in {"delivered", "failed", "unknown", "cancelled"}:
        return
    job.status = status
    job.external_message_id = external_id
    db.flush()
    row = db.get(Message, job.message_id)
    if row is None:
        db.commit()
        return
    jobs = db.scalars(select(ConnectorDelivery).where(
        ConnectorDelivery.message_id == row.id, ConnectorDelivery.platform == job.platform)).all()
    delivered = [{"user_id": j.recipient_id, "external_message_id": j.external_message_id,
                  "external_chat_id": j.chat_id, "external_thread_id": j.thread_id}
                 for j in jobs if j.status == "delivered"]
    errors = [{"user_id": j.recipient_id, "reason": j.status}
              for j in jobs if j.status in {"failed", "unknown", "cancelled"}]
    states = {j.status for j in jobs}
    status = ("queued" if states & {"queued", "published"} else
              "partial" if delivered and errors else "delivered" if delivered else
              "unknown" if "unknown" in states else "failed")
    metadata = json.loads(row.metadata_json or "{}")
    record_messenger_delivery(metadata, job.platform, delivered, errors, status)
    row.metadata_json = encode_message_metadata(metadata)
    db.commit()
    conversation = db.get(Conversation, row.conversation_id)
    if conversation:
        publish_conversation_update(db, conversation, message_id=row.id, action="delivery", sender_role=row.sender_role)
