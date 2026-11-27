import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from connectors.common.client import RetryLater
from connectors.common.spool import EventSpool
from connectors.max.__main__ import application
from connectors.max.webhook import WebhookMonitor, UPDATE_TYPES

URL = "https://school.example/hooks/max"
SECRET = "test-webhook-secret"  # pragma: allowlist secret


def subscription(url=URL, types=UPDATE_TYPES):
    return {"url": url, "update_types": list(types)}


def test_startup_refreshes_secret_then_healthy_subscription_is_not_rewritten():
    async def run():
        api = AsyncMock(side_effect=[
            {"subscriptions": [subscription()]}, {"success": True},
            {"subscriptions": [subscription()]},
        ])
        monitor = WebhookMonitor(SimpleNamespace(api=api), URL, SECRET, clock=lambda: 100)
        assert await monitor.check() == 60
        assert await monitor.check() == 60
        assert [c.args for c in api.await_args_list] == [
            ("GET", "/subscriptions"), ("POST", "/subscriptions"), ("GET", "/subscriptions"),
        ]
        assert api.await_args_list[1].kwargs["body"]["secret"] == SECRET
        assert monitor.status == "active"
        assert monitor.recoveries == 0
        assert monitor.last_success == 100
    asyncio.run(run())


@pytest.mark.parametrize("existing", [[], [subscription(types=("message_created",))],
                                      [subscription(url="https://other.example/hooks/max")]])
def test_missing_or_incomplete_subscription_is_repaired(existing):
    async def run():
        api = AsyncMock(side_effect=[{"subscriptions": existing}, {"success": True}])
        monitor = WebhookMonitor(SimpleNamespace(api=api), URL, SECRET)
        monitor.needs_registration = False
        assert await monitor.check() == 60
        assert monitor.recoveries == 1
        assert monitor.status == "active"
        assert api.await_args_list[1].kwargs["body"] == {
            "url": URL, "secret": SECRET, "update_types": list(UPDATE_TYPES),
        }
    asyncio.run(run())


def test_api_failure_backoff_retry_after_and_recovery():
    async def run():
        api = AsyncMock(side_effect=[
            OSError("unavailable"), RetryLater(400), {"bad": []},
            {"subscriptions": []}, {"success": False},
            {"subscriptions": []}, {"success": True},
        ])
        monitor = WebhookMonitor(SimpleNamespace(api=api), URL, SECRET)
        assert await monitor.check() == 60
        assert monitor.status == "degraded"
        assert await monitor.check() == 400
        assert await monitor.check() == 240
        assert await monitor.check() == 300
        assert monitor.needs_registration
        assert monitor.last_success is None
        assert await monitor.check() == 60
        assert monitor.status == "active"
        assert monitor.failures == 0
        assert monitor.recoveries == 1
        assert all(c.args[0] != "DELETE" for c in api.await_args_list)
    asyncio.run(run())


def test_webhook_activity_only_after_authenticated_durable_write(tmp_path):
    async def run():
        spool = EventSpool(tmp_path / "max.db", "max")
        monitor = WebhookMonitor(None, URL, SECRET, clock=lambda: 123)
        try:
            async with TestClient(TestServer(application(spool, SECRET, monitor))) as client:
                event = {"update_type": "message_created", "message": {"body": {"mid": "1"}}}
                assert (await client.post("/hooks/max", json=event)).status == 403
                assert monitor.last_event is None
                headers = {"X-Max-Bot-Api-Secret": SECRET}
                assert (await client.post("/hooks/max", json=[], headers=headers)).status == 400
                assert (await client.post("/hooks/max", json=event, headers=headers)).status == 200
                assert spool.count() == 1
                assert monitor.last_event == 123
                assert (await client.post("/hooks/max", json=event, headers=headers)).status == 200
                assert spool.count() == 1
                assert SECRET not in str(monitor.diagnostics())
        finally:
            spool.close()
    asyncio.run(run())
