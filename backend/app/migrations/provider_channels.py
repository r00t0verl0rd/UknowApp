"""One-time import of legacy provider-specific identifiers; no destructive schema changes."""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import BotDeliveryJob, ExternalEndpoint, Message, MessengerAccount, StudentTelegramGroup, User
from app.bots_gateway.outbox import enqueue_web_delivery
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.modules.communication.service import record_messenger_delivery
import json
from app.modules.communication.accounts import sync_messenger_account


def migrate_provider_channels():
    with SessionLocal() as db:
        for user in db.scalars(select(User).where(User.telegram_id.is_not(None))).all():
            existing = db.scalar(select(MessengerAccount).where(
                MessengerAccount.platform == "telegram", MessengerAccount.user_id == user.id,
            ))
            if existing is None:
                sync_messenger_account(db, user.id, "telegram", str(user.telegram_id),
                                       external_chat_id=str(user.telegram_id))
        for group in db.scalars(select(StudentTelegramGroup)).all():
            if db.get(ExternalEndpoint, ("telegram", group.student_id)) is None:
                db.add(ExternalEndpoint(platform="telegram", user_id=group.student_id,
                                        chat_id=str(group.chat_id), thread_id=str(group.thread_id),
                                        preferred=True))
        db.flush()
        for job in db.scalars(select(BotDeliveryJob).where(BotDeliveryJob.status.in_(("queued", "processing")))).all():
            row = db.get(Message, job.message_id)
            if row is not None and job.status == "queued":
                enqueue_web_delivery(db, row, ("telegram",))
            elif row is not None:
                metadata = json.loads(row.metadata_json or "{}")
                record_messenger_delivery(metadata, "telegram", status="unknown")
                row.metadata_json = encode_message_metadata(metadata)
            job.status = "migrated" if job.status == "queued" else "unknown"
        db.commit()
