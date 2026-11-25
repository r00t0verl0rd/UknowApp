"""Single Core gateway backed by NATS request/reply and JetStream."""
import asyncio
import hashlib
import json
import logging
import os
from hmac import compare_digest
from pathlib import Path
from uuid import uuid4

import nats
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from nats.errors import TimeoutError as NatsTimeout
from nats.js.api import AckPolicy, ConsumerConfig, DiscardPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError
from sqlalchemy import select

from app.core.database import SessionLocal
from app.infrastructure.storage.media import MAX_ATTACHMENT_BYTES, MEDIA_DIR
from app.models import ConnectorDelivery
from .contracts import PREFIX, STREAM, decode, encode, identifier, platforms
from .operations import receive_message, rpc
from .outbox import authorized_job, job_payload, record_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/bots", include_in_schema=False)


def media_path(platform, event_id):
    relative = Path("connector") / platform / hashlib.sha256(event_id.encode()).hexdigest()
    return MEDIA_DIR / relative, relative.as_posix()


class BotsGateway:
    def __init__(self):
        self.platforms = platforms(os.getenv("BOTS_PLATFORMS", ""))
        self.nc = None
        self.js = None
        self.task = None
        self.ready = False
        self.outbox_wakeup = asyncio.Event()

    async def start(self):
        if self.platforms:
            self.task = asyncio.create_task(self.run(), name="bots-nats")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def setup(self):
        self.nc = await nats.connect(
            servers=[os.environ["BOTS_NATS_URL"]],
            user=os.environ["BOTS_NATS_USER"], password=os.environ["BOTS_NATS_PASSWORD"],
            connect_timeout=3, max_reconnect_attempts=-1,
            inbox_prefix=b"_INBOX.core",
        )
        self.js = self.nc.jetstream(timeout=5)
        subjects = [f"{PREFIX}.{direction}.*" for direction in ("inbound", "outbound", "delivery")]
        try:
            info = await self.js.stream_info(STREAM)
        except NotFoundError:
            await self.js.add_stream(config=StreamConfig(name=STREAM, subjects=subjects,
                retention=RetentionPolicy.WORK_QUEUE, storage=StorageType.FILE,
                discard=DiscardPolicy.NEW, max_bytes=1024 ** 3, max_msg_size=256 * 1024,
                duplicate_window=600))
        else:
            if set(info.config.subjects) != set(subjects) or info.config.retention != RetentionPolicy.WORK_QUEUE:
                raise RuntimeError("existing connector stream has incompatible configuration")
        for platform in self.platforms:
            for direction in ("inbound", "outbound", "delivery"):
                name = f"{direction}-{platform}"
                subject = f"{PREFIX}.{direction}.{platform}"
                try:
                    info = await self.js.consumer_info(STREAM, name)
                except NotFoundError:
                    await self.js.add_consumer(STREAM, config=ConsumerConfig(
                        durable_name=name, filter_subject=subject, ack_policy=AckPolicy.EXPLICIT,
                        ack_wait=120, max_ack_pending=1))
                else:
                    if info.config.filter_subject != subject:
                        raise RuntimeError("existing consumer filter incompatible")
            await self.nc.subscribe(f"{PREFIX}.rpc.{platform}.>", cb=self.handle_rpc)
        await self.nc.flush()

    async def handle_rpc(self, msg):
        parts = msg.subject.split(".")
        platform, operation = parts[3], ".".join(parts[4:])
        try:
            with SessionLocal() as db:
                result = rpc(db, platform, operation, decode(msg.data))
            response = {"ok": True, "result": result}
            data = encode(response)
        except HTTPException as exc:
            data = encode({"ok": False, "code": exc.status_code, "error": str(exc.detail)})
        except (ValueError, TypeError, KeyError):
            data = encode({"ok": False, "code": 400, "error": "invalid request"})
        except Exception as exc:  # noqa: BLE001 - RPC boundary
            logger.warning("Connector RPC failed: %s", type(exc).__name__)
            data = encode({"ok": False, "code": 503, "error": "temporarily unavailable"})
        if msg.reply:
            await msg.respond(data)

    async def consume(self, platform, direction):
        sub = await self.js.pull_subscribe_bind(consumer=f"{direction}-{platform}", stream=STREAM)
        while True:
            try:
                messages = await sub.fetch(1, timeout=2)
            except NatsTimeout:
                continue
            for msg in messages:
                try:
                    payload = decode(msg.data)
                    with SessionLocal() as db:
                        if direction == "inbound":
                            receive_message(db, platform, payload, self.platforms, media_path)
                        else:
                            job = db.get(ConnectorDelivery, identifier(payload.get("id")))
                            status = payload.get("status")
                            if not job or job.platform != platform:
                                await msg.term()
                                continue
                            if status not in {"delivered", "failed", "unknown", "cancelled"}:
                                raise ValueError("invalid result")
                            external_id = identifier(payload.get("external_message_id")) if status == "delivered" else None
                            record_result(db, job, status, external_id)
                    self.outbox_wakeup.set()
                    await msg.ack_sync()
                except (HTTPException, ValueError, TypeError, KeyError) as exc:
                    logger.warning("Rejected connector event platform=%s type=%s", platform, type(exc).__name__)
                    await msg.term()
                except Exception as exc:  # noqa: BLE001 - retry transient broker/DB failures
                    logger.warning("Connector event processing will retry: %s", type(exc).__name__)
                    await msg.nak(delay=5)

    async def publish_outbox(self):
        while True:
            self.outbox_wakeup.clear()
            with SessionLocal() as db:
                queued = db.scalars(select(ConnectorDelivery).where(
                    ConnectorDelivery.status == "queued", ConnectorDelivery.platform.in_(self.platforms))
                    .order_by(ConnectorDelivery.created_at, ConnectorDelivery.id).limit(50)).all()
                entries = [(job.id, job.platform) for job in queued]
            for job_id, platform in entries:
                with SessionLocal() as db:
                    job = db.get(ConnectorDelivery, job_id)
                    if not job or job.status != "queued":
                        continue
                    if job_payload(db, job) is None:
                        record_result(db, job, "cancelled")
                        continue
                await self.js.publish(f"{PREFIX}.outbound.{platform}", encode({"id": job_id}),
                                      headers={"Nats-Msg-Id": job_id})
                with SessionLocal() as db:
                    job = db.get(ConnectorDelivery, job_id)
                    if job and job.status == "queued":
                        job.status = "published"
                        db.commit()
            if not entries:
                try:
                    await asyncio.wait_for(self.outbox_wakeup.wait(), 2)
                except TimeoutError:
                    pass

    async def run(self):
        while True:
            workers = []
            try:
                await self.setup()
                workers = [asyncio.create_task(self.consume(p, direction))
                           for p in self.platforms for direction in ("inbound", "delivery")]
                workers.append(asyncio.create_task(self.publish_outbox()))
                self.ready = True
                done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Core stays online when broker unavailable
                logger.warning("NATS gateway unavailable: %s", type(exc).__name__)
            finally:
                self.ready = False
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                if self.nc:
                    await self.nc.close()
                self.nc = None
            await asyncio.sleep(3)


def require_connector(request, platform):
    gateway = getattr(request.app.state, "bots_gateway", None)
    if not gateway or platform not in gateway.platforms:
        raise HTTPException(403)
    expected = os.getenv("BOTS_MEDIA_SECRET_" + platform.upper().replace("-", "_"), "")
    received = request.headers.get("authorization", "")
    if len(expected) < 32 or not compare_digest(received.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(403)


@router.put("/media/{platform}/inbound/{event_id}")
async def upload_media(request: Request, platform: str, event_id: str):
    require_connector(request, platform)
    if not event_id or len(event_id) > 200:
        raise HTTPException(400)
    target, _ = media_path(platform, event_id)
    if target.is_file():
        return {"size": target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + "." + uuid4().hex + ".part")
    count = 0
    try:
        with staging.open("xb") as stream:
            async for chunk in request.stream():
                count += len(chunk)
                if count > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(413)
                await asyncio.to_thread(stream.write, chunk)
        if count == 0:
            raise HTTPException(400)
        # No overwrite if an earlier attempt already committed this event file.
        try:
            os.link(staging, target)
        except FileExistsError:
            pass
        return {"size": target.stat().st_size}
    finally:
        staging.unlink(missing_ok=True)


@router.get("/media/{platform}/outbound/{job_id}")
async def download_media(request: Request, platform: str, job_id: str):
    require_connector(request, platform)
    with SessionLocal() as db:
        job = db.get(ConnectorDelivery, job_id)
        if not job or job.platform != platform or job.status not in {"queued", "published"}:
            raise HTTPException(404)
        row = authorized_job(db, job)
        if row is None:
            raise HTTPException(404)
        key = (json.loads(row.metadata_json or "{}").get("media") or {}).get("local_path")
    if not key:
        raise HTTPException(404)
    root = MEDIA_DIR.resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file() or path.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream")
