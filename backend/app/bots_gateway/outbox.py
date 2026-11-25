"""Durable web delivery queue, independent of connector availability."""
import asyncio
import json
import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.models import BotDeliveryJob, Conversation, Message
from app.modules.communication.contracts import MessageKind, OutboundMedia
from app.modules.communication.service import record_messenger_delivery
from app.modules.panel.delivery import (
    deliver_panel_message, panel_sender_and_recipients,
    refresh_teacher_panel_after_web_delivery, save_panel_messenger_results,
)

logger = logging.getLogger(__name__)


def uses_outbox(app):
    gateway = getattr(app.state, "bots_gateway", None)
    return gateway is not None and "telegram" in gateway.registrations


def enqueue_web_delivery(db, row):
    metadata = json.loads(row.metadata_json or "{}")
    record_messenger_delivery(metadata, "telegram", status="queued")
    row.metadata_json = encode_message_metadata(metadata)
    db.add(BotDeliveryJob(message_id=row.id, status="queued"))


def terminal(db, job, row, conversation, status):
    job.status = status
    if row is not None and conversation is not None:
        save_panel_messenger_results(db, row, conversation, {
            "telegram": {"status": status},
        })
    else:
        db.commit()


def recover_interrupted():
    # A provider may have accepted a send immediately before a Core crash.
    # Do not send it again without reconciliation.
    with SessionLocal() as db:
        for job in db.scalars(select(BotDeliveryJob).where(BotDeliveryJob.status == "processing")).all():
            row = db.get(Message, job.message_id)
            conversation = db.get(Conversation, row.conversation_id) if row else None
            terminal(db, job, row, conversation, "unknown")


async def deliver_one(app, gateway):
    if not gateway.connected("telegram"):
        return False
    with SessionLocal() as db:
        job = db.scalar(select(BotDeliveryJob).where(BotDeliveryJob.status == "queued")
                        .order_by(BotDeliveryJob.message_id).limit(1))
        if not job:
            return False
        row = db.get(Message, job.message_id)
        conversation = db.get(Conversation, row.conversation_id) if row else None
        if not row or not conversation or conversation.status != "active" or (
            row.sender_role == "teacher" and row.sender_id != conversation.teacher_id
        ) or (
            row.sender_role == "student" and row.sender_id != conversation.student_id
        ):
            terminal(db, job, row, conversation, "cancelled")
            return True
        job.status = "processing"
        db.commit()
        try:
            _, recipients, student, teacher = panel_sender_and_recipients(
                db, {"role": row.sender_role}, conversation,
            )
            kind = MessageKind(row.content_type)
            media = (json.loads(row.metadata_json or "{}").get("media") or {})
            attachment = OutboundMedia(
                storage_key=media["local_path"], file_name=media["file_name"],
                mime_type=media.get("mime_type"),
            ) if kind != MessageKind.TEXT else None
            results = await deliver_panel_message(
                db, app.state.communication, row, conversation, recipients,
                row.sender_role, student, row.text, kind, media=attachment,
            )
            job.status = "complete"
            if results:
                save_panel_messenger_results(db, row, conversation, results)
            else:
                db.commit()
            teacher_id, conversation_id = teacher.id, conversation.id
        except asyncio.CancelledError:
            # Leave processing; the next startup will mark it unknown.
            raise
        except Exception as exc:  # noqa: BLE001 - isolate one job from the worker
            logger.warning("Gateway outbox outcome unknown: %s", type(exc).__name__)
            db.rollback()
            job = db.get(BotDeliveryJob, row.id)
            if job:
                terminal(db, job, row, conversation, "unknown")
            return True
    await refresh_teacher_panel_after_web_delivery(app.state.telegram_bot, teacher_id, conversation_id)
    return True


async def run_outbox(app, gateway):
    recover_interrupted()
    while True:
        gateway.outbox_wakeup.clear()
        try:
            while await deliver_one(app, gateway):
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retry transient DB failure
            logger.warning("Gateway outbox unavailable: %s", type(exc).__name__)
            await asyncio.sleep(5)
        try:
            await asyncio.wait_for(gateway.outbox_wakeup.wait(), 30)
        except TimeoutError:
            pass
