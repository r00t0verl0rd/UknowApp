"""Compatibility adapter: keep Telegram business handlers in Core, move all network I/O out."""
import asyncio
import json
import tempfile
from pathlib import Path
from urllib.parse import unquote

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import FSInputFile, Update

from app.core.database import SessionLocal
from app.models import BotEventReceipt
from app.modules.telegram.adapter import TelegramAdapter
from app.modules.telegram.bot import create_dispatcher
from app.modules.communication.service import CommunicationService
from .gateway import GatewayUnavailable

PLATFORM = "telegram"


class RemoteTelegramSession(BaseSession):
    def __init__(self, gateway):
        super().__init__()
        self.gateway = gateway

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        files = {}
        fields = {}
        tickets = {}
        try:
            for key, value in method.model_dump(warnings=False).items():
                value = self.prepare_value(value, bot=bot, files=files)
                if value is not None:
                    fields[key] = value
            for key, file in files.items():
                if not isinstance(file, FSInputFile):
                    raise GatewayUnavailable("unsupported upload source")
                token = self.gateway.issue_ticket(PLATFORM, file.path, "download")
                tickets[key] = {"ticket": token, "filename": file.filename or key}
            response = await self.gateway.call(PLATFORM, "telegram.api", {
                "method": method.__api_method__, "fields": fields, "files": tickets,
            }, timeout=max(timeout or self.timeout, 300) if files else (timeout or self.timeout))
            if not isinstance(response, dict) or "status" not in response or "body" not in response:
                raise GatewayUnavailable("invalid connector response")
            return self.check_response(bot, method, response["status"],
                                       json.dumps(response["body"])).result
        except (GatewayUnavailable, OSError) as exc:
            raise TelegramNetworkError(method=method, message=str(exc)) from exc
        finally:
            for item in tickets.values():
                self.gateway.revoke_ticket(item["ticket"])

    async def fetch_file(self, file_path, destination, timeout):
        token = self.gateway.issue_ticket(PLATFORM, destination, "upload")
        try:
            result = await self.gateway.call(PLATFORM, "telegram.download", {
                "path": file_path, "ticket": token,
            }, timeout=max(timeout, 300))
            if not isinstance(result, dict) or not result.get("ok") or not self.gateway.tickets[token].completed:
                raise OSError("connector did not finish file transfer")
        except GatewayUnavailable as exc:
            raise OSError("connector unavailable for file transfer") from exc
        finally:
            self.gateway.revoke_ticket(token)

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        # Only the synthetic Bot below uses this URL; never make a network request to it.
        path = unquote(url.split("/file/bot0:gateway/", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "download"
            await self.fetch_file(path, target, timeout)
            with target.open("rb") as source:
                while chunk := await asyncio.to_thread(source.read, chunk_size):
                    yield chunk


class RemoteTelegramBot(Bot):
    async def download_file(self, file_path, destination=None, timeout=30, chunk_size=65536, seek=True):
        if not file_path:
            raise OSError("Telegram file unavailable")
        if isinstance(destination, (str, Path)):
            await self.session.fetch_file(file_path, Path(destination), timeout)
            return None
        return await super().download_file(file_path, destination, timeout, chunk_size, seek)


def install_telegram(app, gateway, secret):
    # Only the connector has the actual token. This Bot is an aiogram-compatible RPC facade.
    bot = RemoteTelegramBot(token="0:gateway", session=RemoteTelegramSession(gateway))  # pragma: allowlist secret
    dispatcher = create_dispatcher()

    async def on_event(event_id, payload):
        update = Update.model_validate(payload, context={"bot": bot})
        # Namespace includes the provider bot ID supplied by the authenticated connector.
        prefix, separator, update_id = event_id.partition(":")
        if not separator or not prefix.isdecimal() or update_id != str(update.update_id):
            raise ValueError("invalid Telegram event id")
        with SessionLocal() as db:
            if db.get(BotEventReceipt, (PLATFORM, event_id)):
                return
        await dispatcher.feed_update(bot, update)
        with SessionLocal() as db:
            db.add(BotEventReceipt(platform=PLATFORM, event_id=event_id))
            db.commit()

    def status(value):
        app.state.telegram_status = value
        if value == "connected":
            # A connector may have been replaced; do not keep stale getMe identity.
            bot._me = None

    gateway.register(PLATFORM, secret, on_event, status)
    app.state.telegram_bot = bot
    app.state.telegram_status = "connecting"
    app.state.communication = CommunicationService([TelegramAdapter(bot)])
    return bot
