"""Bot API over a private Telegram gateway.

The primary server uses an aiogram Bot and the same existing handlers in
both modes. In remote mode its session sends requests and streamed files to a
gateway that owns the real BotFather token. The placeholder here is NOT a
credential, it merely satisfies aiogram's Bot identity validation.
"""
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

REMOTE_BOT_PLACEHOLDER = "1000000:REMOTE_GATEWAY_TRANSPORT"


class GatewaySession(AiohttpSession):
    def __init__(self, gateway_url: str, service_key: str):
        target = gateway_url.rstrip("/")
        parts = urlsplit(target)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("TELEGRAM_GATEWAY_URL must be an HTTP(S) origin without credentials or query")
        if not service_key or len(service_key) < 32:
            raise ValueError("TELEGRAM_GATEWAY_TOKEN must have at least 32 characters")
        self._service_key = service_key
        super().__init__(
            api=TelegramAPIServer(
                base=target + "/bot{token}/{method}",
                file=target + "/file/bot{token}/{path}",
            ),
        )

    async def create_session(self):
        session = await super().create_session()
        # The header applies to Bot API calls AND streamed file downloads.
        session.headers["X-Uknow-Gateway-Key"] = self._service_key
        return session


def create_remote_bot(gateway_url: str, service_key: str) -> Bot:
    return Bot(
        token=REMOTE_BOT_PLACEHOLDER,
        session=GatewaySession(gateway_url, service_key),
    )
