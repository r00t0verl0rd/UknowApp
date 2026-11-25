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
from sqlalchemy import func, select, update

from app.core.database import SessionLocal
from app.infrastructure.storage.media import MAX_ATTACHMENT_BYTES, MEDIA_DIR
from app.models import ConnectorDeletion, ConnectorDelivery, Conversation, MessengerAccount
from app.event_hub import subscribe_chat_updates, unsubscribe_chat_updates
from .contracts import PREFIX, STREAM, decode, encode, identifier, platforms
from .operations import receive_message, rpc
from .outbox import PENDING, authorized_job, get_job, now_utc, publication_candidates, record_result

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
        self.diagnostics = {}
        self.connectors = {}

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
        recreated = False
        try:
            info = await self.js.stream_info(STREAM)
        except NotFoundError:
            recreated = True
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
                        ack_wait=120, max_ack_pending=16 if direction == "outbound" else 1))
                else:
                    if info.config.filter_subject != subject:
                        raise RuntimeError("existing consumer filter incompatible")
                    if direction == "outbound" and info.config.max_ack_pending != 16:
                        info.config.max_ack_pending = 16
                        await self.js.add_consumer(STREAM, config=info.config)
            await self.nc.subscribe(f"{PREFIX}.rpc.{platform}.>", cb=self.handle_rpc)
            await self.nc.subscribe(f"{PREFIX}.health.{platform}", cb=self.handle_health)
        if recreated:
            # A newly created stream has lost all old jobs. Recover immediately,
            # including sending jobs whose local receipt is still available.
            with SessionLocal() as db:
                for model in (ConnectorDelivery, ConnectorDeletion):
                    db.execute(update(model).where(model.platform.in_(self.platforms),
                        model.status.in_(("published", "sending"))).values(published_at=None))
                db.commit()
        await self.nc.flush()

    async def handle_health(self, msg):
        try:
            platform = msg.subject.split(".")[-1]
            payload = decode(msg.data)
            # Only numeric diagnostics, no message content or external identifiers.
            stats = {k: int(payload[k]) for k in ("raw_pending", "inbound_pending", "active", "buffered")
                     if isinstance(payload.get(k), int) and 0 <= payload[k] <= 1000000}
            self.connectors[platform] = {**stats, "seen": now_utc().isoformat()}
        except (ValueError, TypeError, KeyError):
            pass

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
                payload = {}
                try:
                    payload = decode(msg.data)
                    with SessionLocal() as db:
                        if direction == "inbound":
                            receive_message(db, platform, payload, self.platforms, media_path)
                        else:
                            job = get_job(db, identifier(payload.get("id")))
                            status = payload.get("status")
                            if not job or job.platform != platform:
                                await msg.term()
                                continue
                            if status not in {"delivered", "failed", "unknown", "cancelled"}:
                                raise ValueError("invalid result")
                            external_id = identifier(payload.get("external_message_id")) if status == "delivered" else None
                            record_result(db, job, status, external_id)
                    self.outbox_wakeup.set()
                    if direction == "inbound":
                        await self.nc.publish(f"{PREFIX}.accepted.{platform}", encode({"id": payload["id"], "ok": True}))
                    await msg.ack_sync()
                except (HTTPException, ValueError, TypeError, KeyError) as exc:
                    logger.warning("Rejected connector event platform=%s type=%s", platform, type(exc).__name__)
                    if direction == "inbound" and isinstance(payload.get("id"), str):
                        await self.nc.publish(f"{PREFIX}.accepted.{platform}", encode({"id": payload["id"], "ok": False}))
                    await msg.term()
                except Exception as exc:  # noqa: BLE001 - retry transient broker/DB failures
                    logger.warning("Connector event processing will retry: %s", type(exc).__name__)
                    await msg.nak(delay=5)

    async def publish_outbox(self):
        while True:
            self.outbox_wakeup.clear()
            with SessionLocal() as db:
                entries = publication_candidates(db, self.platforms)
            for job_id, platform, chat, thread, status, heavy in entries:
                # Stable IDs for normal publish, separate time-bucket ID for stale recovery.
                # A connector's durable receipt and Core claim prevent duplicate sends.
                dedup = job_id if status == "queued" else f"{job_id}:recover:{int(now_utc().timestamp()) // 60}"
                try:
                    await self.js.publish(f"{PREFIX}.outbound.{platform}",
                        encode({"id": job_id, "route": [chat, thread], "heavy": heavy}),
                        headers={"Nats-Msg-Id": dedup})
                except Exception as exc:
                    # Backpressure or a transient publish failure must not stop
                    # inbound processing and the RPC server.
                    logger.warning("Outbox publication delayed: %s", type(exc).__name__)
                    await asyncio.sleep(5)
                    break
                with SessionLocal() as db:
                    job = get_job(db, job_id)
                    if job and job.status in PENDING:
                        if job.status == "queued":
                            job.status = "published"
                        job.published_at = now_utc()
                        db.commit()
                if status != "queued":
                    logger.info("Republished stale connector job platform=%s status=%s", platform, status)
            if not entries:
                try:
                    await asyncio.wait_for(self.outbox_wakeup.wait(), 5)
                except TimeoutError:
                    pass

    async def collect_diagnostics(self):
        while True:
            stats = {}
            with SessionLocal() as db:
                for model, name in ((ConnectorDelivery, "send"), (ConnectorDeletion, "delete")):
                    rows = db.execute(select(model.platform, model.status, func.count(), func.min(model.created_at))
                        .where(model.platform.in_(self.platforms)).group_by(model.platform, model.status)).all()
                    for platform, status, count, oldest in rows:
                        data = stats.setdefault(platform, {}).setdefault(name, {})
                        data[status] = {"count": count, "oldest": oldest.isoformat() if oldest else None}
            self.diagnostics = stats
            for platform in self.platforms:
                pending = sum(v["count"] for d in stats.get(platform, {}).values() for k, v in d.items() if k in PENDING)
                if pending:
                    logger.info("Connector queue platform=%s pending=%d", platform, pending)
            await asyncio.sleep(30)

    async def refresh_panels(self):
        # Best-effort UI invalidations only. Messages remain durable in JetStream.
        queue = subscribe_chat_updates({"role": "admin"})
        try:
            while True:
                event = json.loads(await queue.get())
                if event.get("conversation_type") != "conversation" or event.get("action") not in {"upsert", "delete", "read"}:
                    continue
                with SessionLocal() as db:
                    chat = db.get(Conversation, event["conversation_id"])
                    if not chat:
                        continue
                    actors = db.scalars(select(MessengerAccount).where(
                        MessengerAccount.user_id == chat.teacher_id,
                        MessengerAccount.status == "linked",
                        MessengerAccount.platform.in_(self.platforms))).all()
                    targets = [(account.platform, account.external_user_id) for account in actors]
                for platform, actor in targets:
                    await self.nc.publish(f"{PREFIX}.ui.{platform}", encode({"actor": actor}))
        finally:
            unsubscribe_chat_updates(queue)

    async def run(self):
        while True:
            workers = []
            try:
                await self.setup()
                workers = [asyncio.create_task(self.consume(p, direction))
                           for p in self.platforms for direction in ("inbound", "delivery")]
                workers.append(asyncio.create_task(self.publish_outbox()))
                workers.append(asyncio.create_task(self.refresh_panels()))
                workers.append(asyncio.create_task(self.collect_diagnostics()))
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
        if not job or job.platform != platform or job.status not in PENDING:
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
