"""Shared connector client: NATS RPC, JetStream, delivery receipts and HTTP media."""
import asyncio
import json
import logging
import os
from collections import deque
from urllib.parse import quote

import nats
from nats.errors import TimeoutError as NatsTimeout

from .contracts import PREFIX, STREAM, encode

logger = logging.getLogger(__name__)


class RetryLater(Exception):
    """Provider explicitly rejected a request due to a temporary rate limit."""
    def __init__(self, seconds):
        super().__init__("provider rate limit")
        self.seconds = seconds


class DeliveryRejected(Exception):
    """Provider definitively refused the requested operation."""


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class GatewayClient:
    def __init__(self, platform, http, spool):
        self.platform = platform
        self.http = http
        self.spool = spool
        self.nc = None
        self.js = None
        self.media_slots = asyncio.Semaphore(2)
        self.worker_slots = asyncio.Semaphore(8)
        self.ui_pending = set()
        self.base = os.environ["BOTS_MEDIA_URL"].rstrip("/")
        self.headers = {"Authorization": "Bearer " + os.environ["BOTS_MEDIA_SECRET"]}

    async def connect(self):
        self.nc = await nats.connect(
            servers=[os.environ["BOTS_NATS_URL"]],
            user=os.environ["BOTS_NATS_USER"], password=os.environ["BOTS_NATS_PASSWORD"],
            inbox_prefix=("_INBOX." + self.platform).encode(),
            max_reconnect_attempts=-1, connect_timeout=3)
        self.js = self.nc.jetstream(timeout=10)

    async def close(self):
        if self.nc:
            await self.nc.close()

    async def rpc(self, operation, **payload):
        msg = await self.nc.request(f"{PREFIX}.rpc.{self.platform}.{operation}", encode(payload), timeout=10)
        response = json.loads(msg.data)
        if not response.get("ok"):
            raise RpcError(response.get("code", 503), response.get("error", "Core unavailable"))
        return response["result"]

    async def inbound(self, event):
        await self.js.publish(f"{PREFIX}.inbound.{self.platform}", encode(event),
                              headers={"Nats-Msg-Id": self.platform + ":" + event["id"]})

    async def upload(self, event_id, chunks):
        async with self.http.put(f"{self.base}/internal/bots/media/{self.platform}/inbound/{quote(event_id, safe='')}",
                                 headers=self.headers, data=chunks, allow_redirects=False) as response:
            response.raise_for_status()

    def media_url(self, job):
        return f"{self.base}/internal/bots/media/{self.platform}/outbound/{job}"

    @staticmethod
    async def extend_ack(msg):
        while True:
            await asyncio.sleep(30)
            await msg.in_progress()

    async def execute_delivery(self, adapter, job_id, job):
        # Only an explicit provider rate-limit rejection is safe to retry.
        self.spool.begin_delivery(job_id)
        try:
            if job.get("media"):
                async with self.media_slots:
                    external_id = await self.provider_call(adapter, job)
            else:
                external_id = await self.provider_call(adapter, job)
            receipt = {"id": job_id, "status": "delivered", "external_message_id": str(external_id)}
        except asyncio.CancelledError:
            raise
        except DeliveryRejected:
            receipt = {"id": job_id, "status": "failed"}
        except Exception as exc:
            logger.warning("External delivery outcome uncertain: %s", type(exc).__name__)
            receipt = {"id": job_id, "status": "unknown"}
        self.spool.finish_delivery(job_id, receipt)
        return receipt

    async def provider_call(self, adapter, job):
        for attempt in range(3):
            try:
                if job.get("operation") == "delete":
                    await adapter.delete(job)
                    return job["external_message_id"]
                return await adapter.send(job, self)
            except RetryLater as exc:
                if attempt == 2 or exc.seconds > 60:
                    raise DeliveryRejected("provider rate limit exceeded") from exc
                await asyncio.sleep(max(1, exc.seconds))
        raise DeliveryRejected("provider rate limit exceeded")

    async def complete(self, adapter, msg, job_id, authorized):
        try:
            receipt = self.spool.delivery(job_id)
            if receipt is None:
                if not authorized.get("ok"):
                    code = authorized.get("code")
                    if code in {403, 404}:
                        await msg.ack_sync()
                        return
                    if code == 409:
                        # Core already released this job, but no durable local receipt remains.
                        receipt = {"id": job_id, "status": "unknown"}
                    else:
                        await msg.nak(delay=5)
                        return
                else:
                    receipt = await self.execute_delivery(adapter, job_id, authorized["result"])
            await self.js.publish(f"{PREFIX}.delivery.{self.platform}", encode(receipt),
                                  headers={"Nats-Msg-Id": "result:" + job_id})
            await msg.ack_sync()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Delivery will retry transport: %s", type(exc).__name__)
            try:
                await msg.nak(delay=5)
            except Exception:
                logger.warning("Delivery NAK unavailable; broker will redeliver")

    async def deliveries(self, adapter):
        # UI invalidations are best effort, coalesced per actor, and separate from sends.
        async def refresh(msg):
            try:
                actor = json.loads(msg.data)["actor"]
                self.ui_pending.add(actor)
                ui_wakeup.set()
            except (ValueError, KeyError, TypeError):
                return

        async def refresh_loop():
            while True:
                await ui_wakeup.wait()
                ui_wakeup.clear()
                await asyncio.sleep(.1)
                actors = list(self.ui_pending)
                self.ui_pending.clear()
                for actor in actors:
                    try:
                        await adapter.refresh_panel(actor, self, self.spool, background=True)
                    except Exception as exc:
                        logger.debug("Panel refresh unavailable: %s", type(exc).__name__)

        ui_wakeup = asyncio.Event()
        subscription = await self.nc.subscribe(f"{PREFIX}.ui.{self.platform}", cb=refresh)
        ui_task = asyncio.create_task(refresh_loop())
        pending = deque()
        active = {}
        heartbeats = {}
        try:
            sub = await self.js.pull_subscribe_bind(
                consumer="outbound-" + self.platform, stream=STREAM,
                inbox_prefix=("_INBOX." + self.platform + ".").encode())
            while True:
                for task, (route, msg) in list(active.items()):
                    if task.done():
                        active.pop(task)
                        heartbeat = heartbeats.pop(id(msg))
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
                        task.result()
                busy = {item[0] for item in active.values()}
                # Keep only one active job per route. Core also checks older pending jobs
                # when a delayed NAK or reconnect changes broker order.
                heads = []
                for item in list(pending):
                    if len(active) + len(heads) >= 8:
                        break
                    msg, job_id, route = item
                    if route in busy:
                        continue
                    busy.add(route)
                    heads.append(item)
                    pending.remove(item)
                    if len(heads) >= min(4, 8 - len(active)):
                        break
                if heads:
                    ids = [job_id for _, job_id, _ in heads if self.spool.delivery(job_id) is None]
                    try:
                        results = await self.rpc("delivery.authorize_batch", ids=ids) if ids else {}
                    except Exception as exc:
                        logger.warning("Batch authorization unavailable: %s", type(exc).__name__)
                        results = {}
                    for msg, job_id, route in heads:
                        task = asyncio.create_task(self.complete(adapter, msg, job_id, results.get(job_id, {})))
                        active[task] = (route, msg)
                capacity = 16 - len(pending) - len(active)
                if capacity > 0:
                    try:
                        # A short fetch while workers are running allows new light tasks
                        # to enter without waiting for an earlier media upload.
                        msgs = await sub.fetch(min(capacity, 4), timeout=.15 if active or pending else 2)
                    except NatsTimeout:
                        msgs = []
                    for msg in msgs:
                        try:
                            envelope = json.loads(msg.data)
                            job_id = envelope["id"]
                            route = tuple(envelope.get("route") or ["legacy", job_id])
                            if not isinstance(job_id, str) or len(route) != 2 or not all(isinstance(x, str) for x in route):
                                raise ValueError("invalid job envelope")
                        except (ValueError, KeyError, TypeError):
                            await msg.term()
                            continue
                        heartbeats[id(msg)] = asyncio.create_task(self.extend_ack(msg))
                        pending.append((msg, job_id, route))
                elif active:
                    await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                else:
                    await asyncio.sleep(.1)
        finally:
            tasks = list(active) + list(heartbeats.values()) + [ui_task]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await subscription.unsubscribe()
