"""Independent Telegram gateway (run with uvicorn on secondary VPS).

No UknowApp models or SQLAlchemy access. Telegram webhooks are durably spooled
before HTTP 200 and forwarded to the primary's authenticated internal inbox.
The second server owns the real BotFather token and streams Bot API traffic.
"""
import asyncio
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GATEWAY_TOKEN = os.getenv("TELEGRAM_GATEWAY_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
PRIMARY_URL = os.getenv("TELEGRAM_PRIMARY_URL", "").strip().rstrip("/")
SPOOL_PATH = Path(os.getenv("TELEGRAM_SPOOL_PATH", "/data/telegram_spool.sqlite3"))
TELEGRAM_API_URL = "https://api.telegram.org"
REMOTE_TOKEN = "1000000:REMOTE_GATEWAY_TRANSPORT"
MAX_UPDATE_SIZE = 2 * 1024 * 1024
METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


def validate_configuration() -> None:
    if ":" not in BOT_TOKEN or not BOT_TOKEN.split(":", 1)[0].isdigit():
        raise RuntimeError("Set a valid TELEGRAM_BOT_TOKEN on the secondary server")
    if len(GATEWAY_TOKEN) < 32 or len(WEBHOOK_SECRET) < 32:
        raise RuntimeError("TELEGRAM_GATEWAY_TOKEN and TELEGRAM_WEBHOOK_SECRET must be at least 32 characters")
    if not WEBHOOK_URL.startswith("https://") or not WEBHOOK_URL.endswith("/telegram/webhook"):
        raise RuntimeError("TELEGRAM_WEBHOOK_URL must be an HTTPS URL ending in /telegram/webhook")
    if urlsplit(PRIMARY_URL).scheme != "https" or not urlsplit(PRIMARY_URL).netloc:
        raise RuntimeError("TELEGRAM_PRIMARY_URL must use HTTPS")


@contextmanager
def connection():
    """Commit or roll back the short spool transaction and close its handle."""
    SPOOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(SPOOL_PATH), timeout=30)
    try:
        db.execute("PRAGMA busy_timeout=30000")
        with db:
            yield db
    finally:
        db.close()


def init_spool():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS telegram_updates ("
            "update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL,"
            "attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0)"
        )


async def spool_worker(client: aiohttp.ClientSession, stop: asyncio.Event):
    while not stop.is_set():
        with connection() as db:
            row = db.execute(
                "SELECT update_id, payload, attempts, next_try FROM telegram_updates "
                "ORDER BY update_id LIMIT 1",
            ).fetchone()
        if not row or row[3] > time.time():
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            continue
        update_id, payload, attempts, _next_try = row
        try:
            async with client.post(
                PRIMARY_URL + "/api/internal/telegram/updates",
                data=payload.encode("utf-8"),
                headers={"X-Uknow-Gateway-Key": GATEWAY_TOKEN, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 202:
                    raise RuntimeError("Primary refused update: HTTP " + str(response.status))
            with connection() as db:
                db.execute("DELETE FROM telegram_updates WHERE update_id = ?", (update_id,))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Primary delivery retry (update_id=%s error_type=%s)", update_id, type(exc).__name__)
            with connection() as db:
                db.execute(
                    "UPDATE telegram_updates SET attempts=?, next_try=? WHERE update_id=?",
                    (attempts + 1, time.time() + min(300, 2 ** min(attempts + 1, 8)), update_id),
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_configuration()
    init_spool()
    stop = asyncio.Event()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as client:
        app.state.client = client
        # A restart re-registers the same webhook without dropping pending updates.
        async with client.post(
            f"{TELEGRAM_API_URL}/bot{BOT_TOKEN}/setWebhook",
            json={"url": WEBHOOK_URL, "secret_token": WEBHOOK_SECRET, "drop_pending_updates": False},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            result = await response.json()
            if response.status != 200 or not result.get("ok"):
                raise RuntimeError("Telegram refused webhook registration")
        task = asyncio.create_task(spool_worker(client, stop))
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Uknow Telegram Gateway", lifespan=lifespan)


def authorize(request: Request):
    if not hmac.compare_digest(request.headers.get("x-uknow-gateway-key", ""), GATEWAY_TOKEN):
        raise HTTPException(401, "Unauthorized")


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if not hmac.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""), WEBHOOK_SECRET):
        raise HTTPException(401, "Unauthorized")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPDATE_SIZE:
            raise HTTPException(413, "Update too large")
    try:
        update = json.loads(body)
        update_id = update["update_id"]
        if not isinstance(update_id, int) or isinstance(update_id, bool):
            raise ValueError("Invalid update id")
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Invalid Telegram update") from None
    with connection() as db:
        db.execute(
            "INSERT OR IGNORE INTO telegram_updates (update_id, payload) VALUES (?, ?)",
            (update_id, body.decode("utf-8")),
        )
    return {"ok": True}


@app.api_route("/bot{proxy_token}/{method}", methods=["POST"])
async def bot_api(proxy_token: str, method: str, request: Request):
    authorize(request)
    if proxy_token != REMOTE_TOKEN or not METHOD_RE.fullmatch(method):
        raise HTTPException(404, "Unknown method")
    # Avoid buffering multipart file uploads in the gateway; stream to Telegram.
    ctype = request.headers.get("content-type", "")
    headers = {"Content-Type": ctype} if ctype else {}
    async with request.app.state.client.post(
        f"{TELEGRAM_API_URL}/bot{BOT_TOKEN}/{method}",
        data=request.stream(),
        headers=headers,
    ) as response:
        body = await response.read()
        return JSONResponse(
            content=json.loads(body),
            status_code=response.status,
        )


@app.get("/file/bot{proxy_token}/{file_path:path}")
async def bot_file(proxy_token: str, file_path: str, request: Request):
    authorize(request)
    if proxy_token != REMOTE_TOKEN or not file_path or ".." in file_path.split("/") or file_path.startswith("/"):
        raise HTTPException(404, "Unknown file")
    # Telegram returns paths relative to the bot. Never accept arbitrary URLs.
    url = f"{TELEGRAM_API_URL}/file/bot{BOT_TOKEN}/" + quote(file_path, safe="/")
    upstream = await request.app.state.client.get(url, timeout=aiohttp.ClientTimeout(total=180))
    if upstream.status != 200:
        upstream.release()
        raise HTTPException(502, "Telegram file unavailable")

    async def chunks():
        try:
            async for chunk in upstream.content.iter_chunked(65536):
                yield chunk
        finally:
            upstream.release()

    return StreamingResponse(chunks(), media_type=upstream.headers.get("Content-Type", "application/octet-stream"))


@app.get("/health")
async def health(request: Request):
    with connection() as db:
        pending = db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0]
    return {"status": "ok", "pending_updates": pending}
