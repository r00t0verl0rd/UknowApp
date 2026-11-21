"""Regression tests for primary/secondary Telegram mode boundary.

No BotFather token, external network or real school data are required.
"""
import asyncio
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.telegram import gateway, internal
from app.modules.telegram.inbox import TelegramUpdate
from app.modules.telegram.remote_transport import REMOTE_BOT_PLACEHOLDER, create_remote_bot


def test_remote_bot_uses_gateway_not_real_bot_token():
    bot = create_remote_bot("https://telegram.example.com", "a" * 64)
    try:
        assert bot.token == REMOTE_BOT_PLACEHOLDER
        assert bot.session.api.api_url(bot.token, "sendMessage") == (
            "https://telegram.example.com/bot" + REMOTE_BOT_PLACEHOLDER + "/sendMessage"
        )
    finally:
        asyncio.run(bot.session.close())


def test_gateway_webhook_secret_and_spool_persist(monkeypatch, tmp_path):
    path = tmp_path / "gateway.sqlite3"
    monkeypatch.setattr(gateway, "SPOOL_PATH", path)
    monkeypatch.setattr(gateway, "WEBHOOK_SECRET", "webhook-secret-" + "a" * 48)
    gateway.init_spool()

    # Do not run the gateway lifespan: that would register a live webhook.
    client = TestClient(gateway.app)
    endpoint = "/telegram/webhook"
    update = {"update_id": 411, "message": {"message_id": 7, "text": "hello"}}
    bad = client.post(endpoint, json=update)
    assert bad.status_code == 401
    headers = {"X-Telegram-Bot-Api-Secret-Token": gateway.WEBHOOK_SECRET}
    assert client.post(endpoint, json=update, headers=headers).status_code == 200
    assert client.post(endpoint, json=update, headers=headers).status_code == 200
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT update_id, payload FROM telegram_updates").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 411
        assert json.loads(rows[0][1]) == update

    assert client.post(endpoint, json={"other": 5}, headers=headers).status_code == 400
    assert client.post(endpoint, data=b"x" * (gateway.MAX_UPDATE_SIZE + 1), headers=headers).status_code == 413


def test_primary_accepts_durable_updates_once(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[TelegramUpdate.__table__])
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    key = "gateway-remote-test-" + "x" * 48
    monkeypatch.setattr(internal, "TELEGRAM_GATEWAY_TOKEN", key)
    monkeypatch.setattr(internal, "SessionLocal", sessions)
    primary = FastAPI()
    primary.include_router(internal.router)
    client = TestClient(primary)
    endpoint = "/api/internal/telegram/updates"
    payload = {"update_id": 90, "message": {"message_id": 15, "chat": {"id": 40}}}
    assert client.post(endpoint, json=payload).status_code == 401
    headers = {"X-Uknow-Gateway-Key": key}
    assert client.post(endpoint, json=payload, headers=headers).status_code == 202
    assert client.post(endpoint, json=payload, headers=headers).status_code == 202
    with sessions() as db:
        assert db.scalar(select(TelegramUpdate).where(TelegramUpdate.update_id == 90)).state == "pending"
        assert db.query(TelegramUpdate).count() == 1
    assert client.post(endpoint, json={}, headers=headers).status_code == 400
    engine.dispose()


def test_primary_worker_processes_stored_raw_update(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[TelegramUpdate.__table__])
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(internal, "SessionLocal", sessions)
    with sessions() as db:
        db.add(TelegramUpdate(update_id=700, payload=json.dumps({"update_id": 700})))
        db.commit()

    class Dispatcher:
        async def feed_raw_update(self, bot, update):
            assert bot == "fake"
            assert update["update_id"] == 700
            stop.set()

    stop = asyncio.Event()
    asyncio.run(internal.process_update_inbox("fake", Dispatcher(), stop))
    with sessions() as db:
        item = db.get(TelegramUpdate, 700)
        assert item.state == "done"
        assert item.payload == "{}"
    engine.dispose()
