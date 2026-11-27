"""Maintain the configured MAX subscription without interrupting message delivery."""
import asyncio
import logging
import time

from connectors.common.client import RetryLater

logger = logging.getLogger(__name__)
UPDATE_TYPES = ("message_created", "message_callback", "bot_started")
CHECK_INTERVAL = 60
MAX_BACKOFF = 300
API_TIMEOUT = 30


class WebhookMonitor:
    def __init__(self, adapter, url, secret, *, clock=time.time):
        self.adapter = adapter
        self.url = url
        self.secret = secret
        self.clock = clock
        self.status = "starting"
        self.last_check = None
        self.last_success = None
        self.last_event = None
        self.recoveries = 0
        self.failures = 0
        self.next_check = None
        # GET does not expose the secret. Refresh the configured secret once per start.
        self.needs_registration = True

    def event_received(self):
        self.last_event = int(self.clock())

    def diagnostics(self):
        return {
            "webhook_status": self.status,
            "webhook_last_check": self.last_check,
            "webhook_last_success": self.last_success,
            "webhook_last_event": self.last_event,
            "webhook_recoveries": self.recoveries,
            "webhook_failures": self.failures,
            "webhook_next_check": self.next_check,
        }

    async def api(self, method, **kwargs):
        return await asyncio.wait_for(
            self.adapter.api(method, "/subscriptions", **kwargs), timeout=API_TIMEOUT
        )

    async def check(self):
        """One reconciliation; return delay until the next attempt."""
        self.last_check = int(self.clock())
        try:
            response = await self.api("GET")
            subscriptions = response.get("subscriptions")
            if not isinstance(subscriptions, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("url"), str)
                for item in subscriptions
            ):
                raise ValueError("invalid MAX subscriptions response")
            matching = next((item for item in subscriptions if item["url"] == self.url), None)
            types = matching.get("update_types") if matching else None
            # A null type list means unfiltered; require explicit expected configuration.
            correct = isinstance(types, list) and all(t in types for t in UPDATE_TYPES)
            needs_repair = matching is None or not correct
            if self.needs_registration or needs_repair:
                self.status = "recovering"
                result = await self.api("POST", body={
                    "url": self.url, "secret": self.secret, "update_types": list(UPDATE_TYPES),
                })
                if result.get("success") is not True:
                    raise ValueError("MAX subscription not confirmed")
                self.needs_registration = False
                if needs_repair:
                    self.recoveries += 1
                    logger.info("MAX webhook subscription restored")
            if self.failures:
                logger.info("MAX webhook subscription check recovered")
            self.status = "active"
            self.last_success = int(self.clock())
            self.failures = 0
            delay = CHECK_INTERVAL
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = "degraded"
            self.failures += 1
            delay = min(MAX_BACKOFF, CHECK_INTERVAL * 2 ** min(self.failures - 1, 3))
            if isinstance(exc, RetryLater):
                delay = max(delay, exc.seconds)
            if self.failures == 1 or self.failures % 12 == 0:
                # Do not log request URLs, secrets, tokens, or provider response bodies.
                logger.warning("MAX webhook subscription check failed: %s", type(exc).__name__)
        self.next_check = int(self.clock() + delay)
        return delay

    async def run(self):
        while True:
            await asyncio.sleep(await self.check())
