"""Disposable broker test: real RPC, consumers, durable inbound ACK and stream-loss recovery."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from app.bots_gateway.gateway import BotsGateway
from app.modules.communication.outbox import enqueue_web_delivery
from app.core.database import SessionLocal
from app.migrations import initialize_database
from app.models import Assignment, BotEventReceipt, ConnectorDelivery, Conversation, Message, User, TransportJob
from app.core import runtime_database
from app.modules.communication.accounts import sync_messenger_account
from connectors.common.client import GatewayClient
from connectors.common.contracts import STREAM
from connectors.common.spool import EventSpool


async def until(predicate, seconds=25):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(.05)


class FakeAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, job, gateway):
        self.sent.append((job["chat_id"], job["id"]))
        return "external-" + job["id"]

    async def refresh_panel(self, *args, **kwargs):
        pass


async def main():
    initialize_database()
    gateway = BotsGateway()
    connector = spool = None
    workers = []
    core_password = os.environ["BOTS_NATS_PASSWORD"]
    try:
        await asyncio.wait_for(gateway.setup(), timeout=30)
        assert (await gateway.js.consumer_info(STREAM, "outbound-telegram")).config.max_ack_pending == 16
        suffix = uuid4().hex
        actor = "student-" + suffix
        with SessionLocal() as db:
            teacher = User(full_name="CI teacher " + suffix,role="teacher")
            student = User(full_name="CI student " + suffix,role="student")
            db.add_all([teacher,student])
            db.flush()
            assignment = Assignment(teacher_id=teacher.id,student_id=student.id,active=True)
            db.add(assignment)
            db.flush()
            conversation = Conversation(assignment_id=assignment.id,teacher_id=teacher.id,student_id=student.id,status="active")
            db.add(conversation)
            sync_messenger_account(db,student.id,"telegram",actor,actor)
            db.flush()
            row = Message(conversation_id=conversation.id,sender_id=teacher.id,sender_role="teacher",text="test")
            db.add(row)
            db.flush()
            enqueue_web_delivery(db,row,("telegram",))
            db.commit()
            job_id = db.query(ConnectorDelivery).filter_by(message_id=row.id).one().id

        def status():
            with SessionLocal() as db:
                return db.get(ConnectorDelivery,job_id).status

        # Публикуем без коннектора и проверяем восстановление после потери потока.
        worker = asyncio.create_task(gateway.publish_outbox())
        workers.append(worker)
        def published():
            with runtime_database.RuntimeSessionLocal() as runtime:
                job = runtime.get(TransportJob, job_id)
                return job is not None and job.state == "published"
        await until(published)
        worker.cancel()
        await asyncio.gather(worker,return_exceptions=True)
        workers.clear()
        await gateway.js.delete_stream(STREAM)
        await gateway.nc.close()
        await gateway.close()
        gateway = BotsGateway()
        await gateway.setup()
        os.environ["BOTS_NATS_USER"] = "telegram"
        os.environ["BOTS_NATS_PASSWORD"] = os.environ["BOTS_NATS_TELEGRAM_PASSWORD"]
        os.environ["BOTS_MEDIA_URL"] = "http://localhost"
        os.environ["BOTS_MEDIA_SECRET"] = os.environ["BOTS_MEDIA_SECRET_TELEGRAM"]
        with tempfile.TemporaryDirectory() as tmp:
            spool = EventSpool(Path(tmp) / "spool.db","ci")
            connector = GatewayClient("telegram",None,spool)
            await connector.connect()
            assert (await connector.rpc("account.resolve",actor=actor))["account"]["role"] == "student"
            adapter = FakeAdapter()
            workers = [asyncio.create_task(gateway.consume("telegram",d)) for d in ("inbound","delivery")]
            workers += [asyncio.create_task(gateway.publish_outbox()),asyncio.create_task(connector.deliveries(adapter)),
                        asyncio.create_task(connector.publish_inbound())]
            event_id = "ci-" + suffix
            await connector.inbound({"id":event_id,"actor":actor,"channel":"private","chat_id":actor,
                                     "kind":"text","text":"hello"})
            await until(lambda:status()=="delivered")
            await until(lambda:spool.inbound_count()==0)
            assert adapter.sent == [(actor,job_id)]
            with SessionLocal() as db:
                assert db.get(BotEventReceipt,("telegram",event_id)) is not None
            print("Authenticated RPC, delivery after stream loss and durable inbound acknowledgement passed")
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        if connector:
            await connector.close()
        if spool:
            spool.close()
        if gateway.nc and not gateway.nc.is_closed:
            await gateway.nc.close()
        await gateway.close()
        os.environ["BOTS_NATS_USER"]="core"
        os.environ["BOTS_NATS_PASSWORD"]=core_password


if __name__ == "__main__":
    asyncio.run(main())
