"""Guard against blocking async handlers and slow connector SQL affecting HTTP."""
import ast
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.bots_gateway import gateway
from app.main import app


def test_async_functions_do_not_call_sync_sql_directly():
    # A cheap static guard complements the runtime SQLAlchemy fixture.
    class Scan(ast.NodeVisitor):
        def __init__(self, path):
            self.path = path
            self.async_body = False
            self.errors = []

        def visit_AsyncFunctionDef(self, node):
            previous = self.async_body
            self.async_body = True
            for statement in node.body:
                self.visit(statement)
            self.async_body = previous

        def visit_FunctionDef(self, node):
            previous = self.async_body
            self.async_body = False
            for statement in node.body:
                self.visit(statement)
            self.async_body = previous

        def visit_Call(self, node):
            fn = node.func
            if self.async_body:
                direct = isinstance(fn, ast.Name) and fn.id in {
                    "SessionLocal", "initialize_database", "replay_chat_updates",
                    "receive_message", "record_result", "schedule_push", "create_tables"}
                direct |= (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                           and fn.value.id in {"db", "session", "engine", "connection"}
                           and fn.attr in {"get", "execute", "exec_driver_sql", "query", "scalar", "scalars",
                                           "commit", "rollback", "flush", "refresh", "connect", "begin"})
                if direct:
                    self.errors.append(f"{self.path}:{node.lineno}")
            self.generic_visit(node)

    root = Path(__file__).resolve().parents[1] / "app"
    errors = []
    for path in root.rglob("*.py"):
        scan = Scan(path.relative_to(root))
        scan.visit(ast.parse(path.read_text(encoding="utf-8")))
        errors.extend(scan.errors)
    assert not errors, "Blocking SQL in async code: " + ", ".join(errors)


def test_slow_gateway_sql_does_not_block_http(api, tmp_path, monkeypatch):
    # Separate connection ensures this test measures event-loop isolation, not
    # legitimate SQLite contention for the same database write lock.
    engine = create_engine("sqlite:///" + str(tmp_path / "slow.sqlite3"))
    slow_sessions = sessionmaker(bind=engine)
    entered, release = threading.Event(), threading.Event()

    @event.listens_for(engine, "before_cursor_execute")
    def slow_query(*args):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("event loop was blocked by SQL")

    def slow_rpc(db, *_):
        return {"value": db.scalar(text("SELECT 1"))}

    monkeypatch.setattr(gateway, "SessionLocal", slow_sessions)
    monkeypatch.setattr(gateway, "rpc", slow_rpc)

    async def run():
        instance = gateway.BotsGateway()
        msg = SimpleNamespace(subject="uknow.v1.rpc.telegram.account.resolve",
                              data=b'{}', reply="response", respond=AsyncMock())
        task = asyncio.create_task(instance.handle_rpc(msg))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await asyncio.wait_for(client.get("/api/health"), timeout=2)
                assert response.status_code == 200
            assert not task.done(), "HTTP must complete before the stalled connector query"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=3)
            await instance.close()
        assert gateway.decode(msg.respond.await_args.args[0]) == {"ok": True, "result": {"value": 1}}

    try:
        asyncio.run(run())
    finally:
        engine.dispose()


def test_gateway_read_can_finish_while_writer_is_busy():
    async def run():
        instance = gateway.BotsGateway()
        entered, release = threading.Event(), threading.Event()

        def write():
            entered.set()
            assert release.wait(5)

        writer = asyncio.create_task(instance.run_db(write))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert await asyncio.wait_for(instance.run_db(lambda: 42, read_only=True), 2) == 42
        finally:
            release.set()
            await writer
            await instance.close()

    asyncio.run(run())


def test_gateway_db_worker_is_bounded():
    async def run():
        instance = gateway.BotsGateway()
        active = 0
        maximum = 0
        lock = threading.Lock()
        loop_thread = threading.get_ident()
        def work():
            nonlocal active, maximum
            assert threading.get_ident() != loop_thread
            with lock:
                active += 1
                maximum = max(maximum, active)
            threading.Event().wait(.01)
            with lock:
                active -= 1
        try:
            await asyncio.gather(*(instance.run_db(work) for _ in range(20)))
            assert maximum == 1
        finally:
            await instance.close()
    asyncio.run(run())


def test_readiness_distinguishes_degraded_gateway(api, monkeypatch):
    make_client, _, _ = api
    client = make_client()
    monkeypatch.setattr(app, "state", SimpleNamespace(runtime_status="ok", bots_gateway=SimpleNamespace(platforms=())))
    assert client.get("/api/ready").status_code == 200
    broker = SimpleNamespace(platforms=("telegram",), ready=False, nc=None)
    app.state.bots_gateway = broker
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ready").status_code == 503
    broker.ready = True
    broker.nc = SimpleNamespace(is_connected=True)
    assert client.get("/api/ready").status_code == 200
    app.state.runtime_status = "unavailable"
    assert client.get("/api/ready").status_code == 503
