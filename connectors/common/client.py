"""Shared connector client: NATS RPC, JetStream, delivery receipts and HTTP media."""
import asyncio
import json
import logging
import os
from urllib.parse import quote

import nats
from nats.errors import TimeoutError as NatsTimeout

from .contracts import PREFIX, STREAM, encode

logger = logging.getLogger(__name__)


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

    async def deliveries(self, adapter):
        sub = await self.js.pull_subscribe_bind(
            consumer="outbound-" + self.platform, stream=STREAM,
            inbox_prefix=("_INBOX." + self.platform + ".").encode())
        while True:
            try:
                msgs = await sub.fetch(1, timeout=2)
            except NatsTimeout:
                continue
            for msg in msgs:
                heartbeat = asyncio.create_task(self.extend_ack(msg))
                try:
                    job_id = json.loads(msg.data)["id"]
                    receipt = self.spool.delivery(job_id)
                    if receipt is None:
                        try:
                            job = await self.rpc("delivery.authorize", id=job_id)
                        except RpcError as exc:
                            if exc.code in {403, 404}:
                                await msg.ack_sync()
                                continue
                            raise
                        # Record before any externally visible operation; a crash means unknown.
                        self.spool.begin_delivery(job_id)
                        try:
                            if job.get("operation") == "delete":
                                await adapter.delete(job)
                                external_id = job["external_message_id"]
                            else:
                                external_id = await adapter.send(job, self)
                            receipt = {"id": job_id, "status": "delivered", "external_message_id": str(external_id)}
                        except asyncio.CancelledError:
                            raise
                        except DeliveryRejected:
                            receipt = {"id": job_id, "status": "failed"}
                        except Exception as exc:
                            logger.warning("External delivery outcome uncertain: %s", type(exc).__name__)
                            receipt = {"id": job_id, "status": "unknown"}
                        self.spool.finish_delivery(job_id, receipt)
                    await self.js.publish(f"{PREFIX}.delivery.{self.platform}", encode(receipt),
                                          headers={"Nats-Msg-Id": "result:" + job_id})
                    await msg.ack_sync()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Delivery will retry transport: %s", type(exc).__name__)
                    await msg.nak(delay=5)
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
