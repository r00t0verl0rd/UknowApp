import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock

from connectors.common.client import GatewayClient, select_heads
from connectors.common.spool import EventSpool
from connectors.common.ingress import forward


def test_scheduler_reserves_light_slots_and_does_not_skip_route_head():
    queue = deque([(None,"media1",("a",""),True), (None,"text1",("a",""),False),
                   (None,"text2",("b",""),False), (None,"media2",("c",""),True)])
    active = [(("d",""),None,True), (("e",""),None,True)]
    chosen = select_heads(queue, active)
    assert [item[1] for item in chosen] == ["text2"]
    assert [item[1] for item in queue] == ["media1","text1","media2"]


def test_claim_and_normalized_inbound_survive_restart(tmp_path):
    path = tmp_path / "spool.db"
    spool = EventSpool(path,"bot")
    claim = spool.prepare_delivery("job")
    spool.remember_inbound({"id":"incoming","text":"hello"})
    spool.mark_published("incoming")
    spool.close()
    spool = EventSpool(path,"bot")
    assert spool.prepare_delivery("job") == claim
    assert spool.delivery("job") is None
    assert spool.inbound_count() == 1
    assert not spool.pending_inbound()
    assert spool.pending_inbound(age=0)[0][0] == "incoming"
    spool.begin_delivery("job")
    spool.close()
    spool = EventSpool(path,"bot")
    assert spool.delivery("job")["status"] == "unknown"
    spool.accept_inbound("incoming")
    assert spool.inbound_count() == 0
    spool.close()


def test_ingress_light_actor_can_pass_slow_media_but_same_actor_keeps_order(tmp_path):
    async def run():
        spool = EventSpool(tmp_path / "spool.db","bot")
        hold = asyncio.Event()
        processed = []
        async def handle(ident, update, gateway, store):
            if ident == "media":
                await hold.wait()
            processed.append(ident)
        adapter = SimpleNamespace(inbound_route=lambda x:(x["actor"],x["heavy"]), handle=handle)
        task = asyncio.create_task(forward(adapter,None,spool))
        try:
            await asyncio.sleep(0)
            spool.append([("media",{"actor":"a","heavy":True}),
                          ("same",{"actor":"a","heavy":False}),
                          ("other",{"actor":"b","heavy":False})],4)
            async def wait_for(predicate):
                for _ in range(100):
                    if predicate():
                        return
                    await asyncio.sleep(.01)
                raise AssertionError("timed out")
            await wait_for(lambda:"other" in processed)
            assert processed == ["other"]
            hold.set()
            await wait_for(lambda:spool.count() == 0)
            assert processed == ["other","media","same"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            spool.close()
    asyncio.run(run())


def test_recovered_receipt_is_republished_without_external_send(tmp_path,monkeypatch):
    monkeypatch.setenv("BOTS_MEDIA_URL","http://backend")
    monkeypatch.setenv("BOTS_MEDIA_SECRET","test")
    async def run():
        spool = EventSpool(tmp_path / "spool.db","bot")
        spool.begin_delivery("job")
        spool.finish_delivery("job",{"id":"job","status":"delivered","external_message_id":"x"})
        client = GatewayClient("alpha",None,spool)
        client.js = SimpleNamespace(publish=AsyncMock())
        msg = SimpleNamespace(ack_sync=AsyncMock(),nak=AsyncMock())
        adapter = SimpleNamespace(send=AsyncMock())
        await client.complete(adapter,msg,"job",{})
        adapter.send.assert_not_awaited()
        msg.ack_sync.assert_awaited_once()
        client.js.publish.assert_awaited_once()
        spool.close()
    asyncio.run(run())


def test_rate_limit_defers_only_affected_route_and_preserves_claim(tmp_path, monkeypatch):
    from connectors.common.client import RetryLater
    monkeypatch.setenv("BOTS_MEDIA_URL", "http://backend")
    monkeypatch.setenv("BOTS_MEDIA_SECRET", "test")

    async def run():
        spool = EventSpool(tmp_path / "spool.db", "telegram")
        try:
            client = GatewayClient("telegram", None, spool)
            client.js = SimpleNamespace(publish=AsyncMock())
            msg = SimpleNamespace(ack_sync=AsyncMock(), nak=AsyncMock())
            other = SimpleNamespace(ack_sync=AsyncMock(), nak=AsyncMock())
            claim = spool.prepare_delivery("topic")
            count = 0

            async def send(job, _gateway):
                nonlocal count
                if job["thread_id"]:
                    count += 1
                    if count == 1:
                        raise RetryLater(120)
                    return 11
                return 22

            adapter = SimpleNamespace(send=send)
            topic = {"ok":True,"result":{"thread_id":"7"}}
            private = {"ok":True,"result":{"thread_id":None}}
            await asyncio.gather(client.complete(adapter,msg,"topic",topic),
                                 client.complete(adapter,other,"private",private))
            msg.nak.assert_awaited_once_with(delay=120)
            msg.ack_sync.assert_not_awaited()
            assert spool.delivery("topic") is None
            assert spool.prepare_delivery("topic") == claim
            assert spool.delivery("private")["status"] == "delivered"
            await client.complete(adapter,msg,"topic",topic)
            assert spool.delivery("topic")["external_message_id"] == "11"
            msg.ack_sync.assert_awaited_once()
        finally:
            spool.close()

    asyncio.run(run())


def test_confirmed_topic_ack_clears_only_matching_pending_invitation(tmp_path):
    spool = EventSpool(tmp_path / "spool.db", "telegram")
    try:
        event = {"id": "first", "chat_id": "-1001", "thread_id": "7", "pending_topic": True}
        spool.remember_forum_topic("-1001", "7")
        spool.remember_inbound(event)
        spool.accept_inbound("first")
        assert spool.forum_topic("-1001") == "7"
        spool.remember_inbound(event)
        spool.remember_forum_topic("-1001", "8")
        spool.accept_inbound("first", route_confirmed=True)
        assert spool.forum_topic("-1001") == "8"
        spool.remember_forum_topic("-1001", "7")
        spool.remember_inbound(event)
        spool.accept_inbound("first", route_confirmed=True)
        assert spool.forum_topic("-1001") is None
        assert spool.inbound_count() == 0
    finally:
        spool.close()


def test_permanent_rejection_does_not_block_next_event(tmp_path):
    from connectors.common.client import DeliveryRejected

    async def run():
        spool = EventSpool(tmp_path / "spool.db", "bot")
        processed = []
        async def handle(ident, update, gateway, store):
            processed.append(ident)
            if ident == "bad":
                raise DeliveryRejected("forbidden")
        adapter = SimpleNamespace(inbound_route=lambda x: ("same", False), handle=handle)
        spool.append([("bad", {}), ("good", {})], 3)
        task = asyncio.create_task(forward(adapter, None, spool))
        try:
            for _ in range(100):
                if not spool.count():
                    break
                await asyncio.sleep(.01)
            assert processed == ["bad", "good"]
            assert spool.count() == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            spool.close()
    asyncio.run(run())


def test_partial_send_keeps_known_copy_and_never_retries_whole_message(tmp_path, monkeypatch):
    from connectors.common.client import RetryLater
    monkeypatch.setenv("BOTS_MEDIA_URL", "http://backend")
    monkeypatch.setenv("BOTS_MEDIA_SECRET", "test")

    async def run():
        spool = EventSpool(tmp_path / "parts.db", "telegram")
        try:
            client = GatewayClient("telegram", None, spool)
            async def send(job, gateway):
                gateway.spool.record_delivery_part("job", "101")
                raise RetryLater(120)
            adapter = SimpleNamespace(send=AsyncMock(side_effect=send))
            receipt = await client.execute_delivery(adapter, "job", {})
            assert receipt == {"id": "job", "status": "failed",
                               "external_message_id": "101", "external_message_ids": ["101"]}
            assert spool.delivery("job") == receipt
            adapter.send.assert_awaited_once()
        finally:
            spool.close()
    asyncio.run(run())
