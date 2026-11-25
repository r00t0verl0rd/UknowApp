"""Real API registrations and mocked provider fan-out for independent devices."""
import json
import threading
from concurrent.futures import Future
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

from app.models import PushSubscription
from app.core import runtime_database
from app.modules.notifications import service as push
from app.modules.notifications import vapid
from app.modules.system import routes
from app.migrations.push_devices import upgrade_push_devices


def login(client, username="test-admin", password="a-long-test-password-123"):
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def subscription(index):
    return {"endpoint": f"https://web.push.apple.com/push/device-{index}",
            "keys": {"p256dh": "k" * 30, "auth": "a" * 16}}


def register(client, index):
    assert client.post("/api/push/subscribe", json=subscription(index)).status_code == 200


@pytest.fixture
def provider(api, monkeypatch):
    _, _, sessions = api
    from app.core import database
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(routes, "is_safe_push_endpoint", lambda _: True)
    monkeypatch.setattr(push, "is_safe_push_endpoint", lambda _: True)
    monkeypatch.setattr(vapid, "VAPID_PRIVATE_KEY", "fake-private-key")
    monkeypatch.setattr(vapid, "VAPID_PUBLIC_KEY", "fake-public-key")
    collections = []
    monkeypatch.setattr(push, "_RESULT_POOL", SimpleNamespace(submit=lambda fn, args: collections.append((fn, args))))
    return collections


@pytest.mark.parametrize("count", [2, 3, 5, 10])
def test_admin_fanout_all_devices_in_parallel_and_logout(api, provider, monkeypatch, count):
    make_client, _, sessions = api
    clients = [make_client() for _ in range(count)]
    for index, client in enumerate(clients):
        login(client)
        register(client, index)
    # Reopening/re-registering a device is idempotent, not another device.
    register(clients[0], 0)
    diag = clients[0].get("/api/admin/push/diagnostics").json()
    assert diag["admin_devices"] == diag["admin_eligible"] == count
    assert all(d["session_active"] for d in diag["devices"])
    assert all("endpoint" not in d and "session_hash" not in d and "keys" not in d for d in diag["devices"])
    barrier = threading.Barrier(count, timeout=5)
    sent = []
    def send(**kwargs):
        barrier.wait()
        sent.append((kwargs["subscription_info"]["endpoint"], json.loads(kwargs["data"])["body"]))
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, "webpush", send)
    with sessions() as db:
        push.schedule_push(db, [], "Message", "normal", "/?openConversation=1", include_admin=True, admin_body="admin")
    fn, args = provider.pop()
    fn(args)
    assert len(sent) == count
    assert {endpoint for endpoint, _ in sent} == {subscription(i)["endpoint"] for i in range(count)}
    assert {body for _, body in sent} == {"admin"}
    diag = clients[0].get("/api/admin/push/diagnostics").json()
    assert all(d["state"] == "accepted" and d["last_success_at"] for d in diag["devices"])
    # Another admin session cannot detach this device's registered endpoint.
    assert clients[1].request("DELETE", "/api/push/subscribe", json={"endpoint": subscription(0)["endpoint"]}).status_code == 200
    assert clients[1].get("/api/admin/push/diagnostics").json()["admin_eligible"] == count
    # The API logout alone detaches the current device, even if the browser
    # failed to send its separate unsubscribe request.
    assert clients[0].post("/api/auth/logout").status_code == 200
    assert clients[0].get("/api/admin/push/diagnostics").status_code == 401
    assert clients[1].get("/api/admin/push/diagnostics").json()["admin_eligible"] == count - 1


def test_one_expired_and_one_failed_device_do_not_block_others(api, provider, monkeypatch):
    make_client, _, sessions = api
    clients = [make_client() for _ in range(5)]
    for index, client in enumerate(clients):
        login(client)
        register(client, index)
    attempted = []
    def send(**kwargs):
        endpoint = kwargs["subscription_info"]["endpoint"]
        attempted.append(endpoint)
        if endpoint.endswith("-0"):
            raise push.WebPushException("expired", response=SimpleNamespace(status_code=410))
        if endpoint.endswith("-1"):
            raise ValueError("bad provider response")
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, "webpush", send)
    with sessions() as db:
        push.schedule_push(db, [], "Message", "body", include_admin=True)
    fn, args = provider.pop()
    fn(args)
    assert len(attempted) == 5
    diag = clients[2].get("/api/admin/push/diagnostics").json()
    assert [d["state"] for d in diag["devices"]] == ["expired", "failed", "accepted", "accepted", "accepted"]
    assert diag["admin_eligible"] == 4
    assert clients[0].post("/api/push/subscribe", json=subscription(0)).status_code == 410
    # A new login must not erase the information that the old endpoint is dead.
    login(clients[0])
    assert clients[0].post("/api/push/subscribe", json=subscription(0)).status_code == 410
    register(clients[0], 99)
    with runtime_database.RuntimeSessionLocal() as db:
        db.query(PushSubscription).filter_by(endpoint=subscription(99)["endpoint"]).delete()
        db.commit()
    register(clients[0], 99)  # Core lost registration, local subscription is still valid.
    assert clients[0].get("/api/admin/push/diagnostics").json()["admin_eligible"] == 5


def test_old_delivery_result_cannot_expire_new_registration(api, provider):
    make_client, _, sessions = api
    client = make_client()
    login(client)
    register(client, 1)
    with runtime_database.RuntimeSessionLocal() as db:
        row = db.query(PushSubscription).one()
        target = {"id": row.id, "endpoint": row.endpoint, "revision": row.revision,
                  "keys": {"p256dh": row.p256dh, "auth": row.auth}}
    changed = subscription(1)
    changed["keys"]["auth"] = "b" * 16
    assert client.post("/api/push/subscribe", json=changed).status_code == 200
    future = Future()
    future.set_result((target, datetime.now(UTC), "expired", 410))
    push._collect([future])
    with runtime_database.RuntimeSessionLocal() as db:
        assert db.query(PushSubscription).one().delivery_state is None


def test_push_diagnostics_requires_admin(api, provider):
    make_client, _, _ = api
    client = make_client()
    login(client, "teacher-one", "teacher-password-1")
    assert client.get("/api/admin/push/diagnostics").status_code == 401


def test_migration_preserves_legacy_subscriptions(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "old.sqlite"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE push_subscriptions(id INTEGER PRIMARY KEY, endpoint VARCHAR(2048))"))
        c.execute(text("INSERT INTO push_subscriptions VALUES (1,'legacy')"))
        upgrade_push_devices(c)
        upgrade_push_devices(c)
        assert c.scalar(text("SELECT endpoint FROM push_subscriptions")) == "legacy"
        assert {"session_hash","revision","synced_at","last_attempt_at","last_success_at","delivery_state","last_http_status"} <= {x["name"] for x in inspect(c).get_columns("push_subscriptions")}
