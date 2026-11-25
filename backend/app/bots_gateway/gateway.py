"""One authenticated, duplex connection per messenger; no database access for connectors."""
import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from hmac import compare_digest
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.infrastructure.storage.media import MAX_ATTACHMENT_BYTES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/bots", include_in_schema=False)
PROTOCOL = 1
MAX_FRAME = 1024 * 1024
MAX_PENDING = 64


class GatewayUnavailable(RuntimeError):
    pass


@dataclass
class Ticket:
    platform: str
    path: Path
    direction: str
    claimed: bool = False
    completed: bool = False


@dataclass
class Peer:
    socket: WebSocket
    pending: dict = field(default_factory=dict)
    ready: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    events: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=8))

    async def send(self, payload):
        async with self.send_lock:
            await self.socket.send_json(payload)

    async def call(self, operation, payload, timeout):
        if len(self.pending) >= MAX_PENDING:
            raise GatewayUnavailable("connector is busy")
        request_id = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({"type": "command", "id": request_id,
                             "operation": operation, "payload": payload})
            return await asyncio.wait_for(future, timeout)
        except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect) as exc:
            raise GatewayUnavailable("connector command outcome unavailable") from exc
        finally:
            self.pending.pop(request_id, None)

    def fail(self):
        for future in list(self.pending.values()):
            if not future.done():
                future.set_exception(GatewayUnavailable("connector disconnected"))


@dataclass
class Registration:
    secret: str
    event_handler: Callable[[str, dict], Awaitable[None]]
    status_handler: Callable[[str], None]


class BotsGateway:
    def __init__(self):
        self.registrations: dict[str, Registration] = {}
        self.peers: dict[str, Peer] = {}
        self.tickets: dict[str, Ticket] = {}
        self.outbox_wakeup = asyncio.Event()

    def register(self, platform, secret, event_handler, status_handler):
        if len(secret) < 32:
            raise ValueError("connector secret must contain at least 32 characters")
        if platform in self.registrations:
            raise ValueError("duplicate connector platform")
        self.registrations[platform] = Registration(secret, event_handler, status_handler)

    def authorized(self, platform, authorization):
        registration = self.registrations.get(platform)
        return bool(registration and compare_digest(
            authorization.encode("utf-8"), ("Bearer " + registration.secret).encode("utf-8")
        ))

    def connected(self, platform):
        peer = self.peers.get(platform)
        return peer is not None and peer.ready

    async def call(self, platform, operation, payload, timeout=60):
        peer = self.peers.get(platform)
        if peer is None or not peer.ready:
            raise GatewayUnavailable("connector offline")
        return await peer.call(operation, payload, timeout)

    def issue_ticket(self, platform, path, direction):
        if len(self.tickets) >= MAX_PENDING * 4:
            raise GatewayUnavailable("too many active media transfers")
        token = secrets.token_urlsafe(32)
        self.tickets[token] = Ticket(platform, Path(path), direction)
        return token

    def revoke_ticket(self, token):
        self.tickets.pop(token, None)

    async def handle_events(self, registration, peer):
        while True:
            frame = await peer.events.get()
            event_id = frame["id"]
            try:
                await registration.event_handler(event_id, frame["payload"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate malformed provider events
                logger.warning("Connector event failed: %s", type(exc).__name__)
                await peer.send({"type": "ack", "id": event_id, "ok": False})
            else:
                await peer.send({"type": "ack", "id": event_id, "ok": True})

    async def serve(self, socket, platform):
        registration = self.registrations.get(platform)
        if not self.authorized(platform, socket.headers.get("authorization", "")):
            await socket.close(code=1008)
            return
        # Reserve before the first await: only one live connector per platform.
        if platform in self.peers:
            await socket.close(code=1008)
            return
        peer = Peer(socket)
        self.peers[platform] = peer
        worker = None
        try:
            await socket.accept()
            await peer.send({"type": "hello", "version": PROTOCOL})
            peer.ready = True
            registration.status_handler("connected")
            self.outbox_wakeup.set()
            worker = asyncio.create_task(self.handle_events(registration, peer))
            while True:
                raw = await socket.receive_text()
                if len(raw.encode("utf-8")) > MAX_FRAME:
                    await socket.close(code=1009)
                    break
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    await socket.close(code=1008)
                    break
                kind = frame.get("type")
                ident = frame.get("id")
                if kind == "result" and isinstance(ident, str):
                    future = peer.pending.get(ident)
                    if future is not None and not future.done():
                        future.set_result(frame.get("payload"))
                elif (kind == "event" and isinstance(ident, str) and 0 < len(ident) <= 200
                      and isinstance(frame.get("payload"), dict)):
                    try:
                        peer.events.put_nowait(frame)
                    except asyncio.QueueFull:
                        await socket.close(code=1013)
                        break
                elif kind == "ping":
                    await peer.send({"type": "pong"})
                else:
                    await socket.close(code=1008)
                    break
        except (WebSocketDisconnect, ValueError, RuntimeError, OSError):
            pass
        finally:
            peer.ready = False
            peer.fail()
            if worker:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            self.peers.pop(platform, None)
            registration.status_handler("unavailable")

    async def close(self):
        for peer in list(self.peers.values()):
            peer.fail()
            try:
                await peer.socket.close(code=1012)
            except (RuntimeError, OSError):
                pass


@router.websocket("/ws/{platform}")
async def connector_socket(socket: WebSocket, platform: str):
    gateway = getattr(socket.app.state, "bots_gateway", None)
    if gateway is None:
        await socket.close(code=1008)
        return
    await gateway.serve(socket, platform)


def _ticket(request, platform, token, direction):
    gateway = getattr(request.app.state, "bots_gateway", None)
    if gateway is None or not gateway.authorized(platform, request.headers.get("authorization", "")):
        raise HTTPException(403)
    ticket = gateway.tickets.get(token)
    if not ticket or ticket.platform != platform or ticket.direction != direction or ticket.claimed:
        raise HTTPException(404)
    ticket.claimed = True
    return ticket


@router.get("/media/{platform}/{token}")
async def download_media(request: Request, platform: str, token: str):
    ticket = _ticket(request, platform, token, "download")
    if not ticket.path.is_file() or ticket.path.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(404)
    return FileResponse(ticket.path, media_type="application/octet-stream")


@router.put("/media/{platform}/{token}")
async def upload_media(request: Request, platform: str, token: str):
    ticket = _ticket(request, platform, token, "upload")
    count = 0
    try:
        # Write to a unique staging file; a timed-out ticket may no longer publish data.
        staging = ticket.path.with_name(ticket.path.name + "." + token + ".transfer")
        with staging.open("xb") as target:
            async for chunk in request.stream():
                count += len(chunk)
                if count > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(413)
                await asyncio.to_thread(target.write, chunk)
        gateway = request.app.state.bots_gateway
        if gateway.tickets.get(token) is not ticket:
            raise HTTPException(410)
        staging.replace(ticket.path)
        ticket.completed = True
        return {"size": count}
    finally:
        staging.unlink(missing_ok=True)
