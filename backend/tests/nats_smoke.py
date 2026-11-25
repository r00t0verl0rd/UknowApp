"""Run against a disposable NATS server using the deployment ACL."""
import asyncio
import json
import os

import nats

from app.bots_gateway.gateway import BotsGateway
from app.migrations import initialize_database
from connectors.common.contracts import PREFIX, STREAM


async def main():
    initialize_database()
    gateway = BotsGateway()
    connector = None
    try:
        await asyncio.wait_for(gateway.setup(), timeout=30)
        connector = await nats.connect(
            os.environ["BOTS_NATS_URL"], user="telegram",
            password=os.environ["BOTS_NATS_TELEGRAM_PASSWORD"],
            inbox_prefix=b"_INBOX.telegram", connect_timeout=3,
        )
        response = await connector.request(
            f"{PREFIX}.rpc.telegram.account.resolve",
            b'{"actor":"ci-unknown-account"}', timeout=5,
        )
        assert json.loads(response.data)["result"]["account"] is None
        js = connector.jetstream(timeout=5)
        await js.publish(f"{PREFIX}.inbound.telegram", b'{"id":"ci-inbound"}')
        await gateway.js.publish(f"{PREFIX}.outbound.telegram", b'{"id":"ci-job"}')
        sub = await js.pull_subscribe_bind(
            consumer="outbound-telegram", stream=STREAM,
            inbox_prefix=b"_INBOX.telegram.",
        )
        msg, = await sub.fetch(1, timeout=5)
        assert json.loads(msg.data)["id"] == "ci-job"
        await msg.in_progress()
        await msg.ack_sync(timeout=5)
        await js.publish(f"{PREFIX}.delivery.telegram", b'{"id":"ci-job","status":"unknown"}')
        print("Authenticated RPC, JetStream publish, pull and ACK passed")
    finally:
        if connector:
            await connector.close()
        if gateway.nc:
            await gateway.nc.close()


if __name__ == "__main__":
    asyncio.run(main())
