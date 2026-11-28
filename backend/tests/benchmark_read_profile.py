"""Read-path diagnostics, isolated migrated SQLite and real ASGI endpoints."""
import argparse
import asyncio
import hashlib
import json
import math
import os
import resource
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace


def percentile(values, p):
    return round(sorted(values)[max(0, math.ceil(len(values) * p / 100) - 1)], 2) if values else None


def main(args, folder):
    # Set before importing the application; never connect to a real school database.
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(folder) / "load.db")
    os.environ["BOTS_PLATFORMS"] = ""
    os.environ["VAPID_PRIVATE_KEY"] = ""
    os.environ["VAPID_PUBLIC_KEY"] = ""
    os.environ["SEED_DEMO_DATA"] = "false"
    import httpx
    from sqlalchemy import func, insert, select
    from app.core.database import SessionLocal, engine
    from app.main import app
    from app.migrations import initialize_database
    from app.models import Assignment, Conversation, Message, MessengerAccount, PanelSession, User, ConnectorDelivery
    from app.modules.auth.service import SESSION_COOKIE

    initialize_database()
    pairs = (max(args.clients) + 1) // 2
    actors, chats = [], []
    now = datetime.now(UTC)
    fingerprint = hashlib.sha256(b"synthetic-only").hexdigest()
    with SessionLocal() as db:
        for i in range(pairs):
            users = [User(full_name=f"Load {role} {i}", role=role, web_password_hash="synthetic-only")
                     for role in ("teacher", "student")]
            db.add_all(users)
            db.flush()
            teacher, student = users
            assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
            db.add(assignment)
            db.flush()
            conversation = Conversation(assignment_id=assignment.id, teacher_id=teacher.id, student_id=student.id, status="active")
            db.add(conversation)
            db.flush()
            chats.append((conversation.id, teacher.id, student.id))
            for user in users:
                token = f"synthetic-session-{user.id}"
                db.add(PanelSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                    role=user.role, user_id=user.id, credential_fingerprint=fingerprint,
                                    expires_at=now + timedelta(hours=4)))
                actors.append((token, conversation.id))
                for platform in ("telegram", "max"):
                    db.add(MessengerAccount(platform=platform, user_id=user.id, external_user_id=str(user.id),
                                            external_chat_id=str(user.id), status="linked"))
        db.commit()
        started = perf_counter()
        for start in range(0, args.messages, 5000):
            rows = []
            for j in range(start, min(start + 5000, args.messages)):
                chat, teacher, student = chats[j % pairs]
                role = "teacher" if (j // pairs) % 2 == 0 else "student"
                rows.append(dict(conversation_id=chat, sender_id=teacher if role == "teacher" else student,
                                 sender_role=role, text=f"History {j}", teacher_read_at=now.isoformat(),
                                 student_read_at=now.isoformat(), admin_read_at=now.isoformat()))
            db.execute(insert(Message), rows)
            db.commit()
        print(json.dumps({"seed_messages": args.messages, "accounts": len(actors),
                          "seed_seconds": round(perf_counter() - started, 2),
                          "cpu_count": os.cpu_count(), "sqlite": __import__("sqlite3").sqlite_version}), flush=True)

    import anyio
    import contextvars
    import fastapi.routing
    import statistics
    from sqlalchemy import event
    from sqlalchemy.orm import joinedload
    from app.modules.messaging.service import panel_message_dict

    sql = select(Message).options(joinedload(Message.sender)).where(
        Message.conversation_id == chats[0][0], Message.id > 0
    ).order_by(Message.id.desc()).limit(50)
    compiled = str(sql.compile(engine, compile_kwargs={"literal_binds": True}))
    with engine.connect() as conn:
        print(json.dumps({"journal": conn.exec_driver_sql("PRAGMA journal_mode").scalar(),
                          "synchronous": conn.exec_driver_sql("PRAGMA synchronous").scalar(),
                          "pool": engine.pool.status(),
                          "plan": [list(r) for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + compiled)]}), flush=True)

    # Per-request instrumentation; SQL execute excludes row fetching, ORM and JSON.
    trace = contextvars.ContextVar("trace", default=None)
    @event.listens_for(engine, "before_cursor_execute")
    def before_sql(conn, cursor, statement, params, context, executemany):
        context.profile_start = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_sql(conn, cursor, statement, params, context, executemany):
        t = trace.get()
        if t is not None:
            t["sql_ms"] += (perf_counter() - context.profile_start) * 1000
            t["sql_count"] += 1

    original_thread = anyio.to_thread.run_sync
    async def timed_thread(func, *args, **kwargs):
        t = trace.get()
        if t is None:
            return await original_thread(func, *args, **kwargs)
        queued = perf_counter()
        def execute(*a):
            entered = perf_counter()
            t["thread_wait_ms"] += (entered - queued) * 1000
            try:
                return func(*a)
            finally:
                t["thread_work_ms"] += (perf_counter() - entered) * 1000
        return await original_thread(execute, *args, **kwargs)

    original_serialize = fastapi.routing.serialize_response
    async def timed_serialize(*args, **kwargs):
        t = trace.get()
        started = perf_counter()
        try:
            return await original_serialize(*args, **kwargs)
        finally:
            if t is not None:
                t["serialize_ms"] += (perf_counter() - started) * 1000

    anyio.to_thread.run_sync = timed_thread
    fastapi.routing.serialize_response = timed_serialize

    def raw_read(cid):
        query = select(Message).options(joinedload(Message.sender)).where(
            Message.conversation_id == cid, Message.id > 0
        ).order_by(Message.id.desc()).limit(50)
        # Exact same SELECT and JOIN, no ORM mapping or HTTP.
        with engine.connect() as conn:
            return len(conn.execute(query).all())

    def orm_read(cid):
        with SessionLocal() as db:
            rows = db.scalars(select(Message).options(joinedload(Message.sender)).where(
                Message.conversation_id == cid, Message.id > 0
            ).order_by(Message.id.desc()).limit(50)).all()
            return len(rows)

    async def bench():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        print(json.dumps({"default_thread_tokens": original_tokens}), flush=True)
        results = []
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client:
            for threads, n, cases in [
                (original_tokens, 1, ("profile", "inbox", "history1", "history10", "history50", "history50_read", "raw50", "orm50")),
                (original_tokens, 100, ("profile", "inbox", "history1", "history10", "history50", "history50_read", "raw50", "orm50")),
                (4, 100, ("history50", "raw50", "orm50")),
                (10, 100, ("history50", "raw50", "orm50")),
                (20, 100, ("history50", "raw50", "orm50")),
            ]:
                limiter.total_tokens = threads
                for case in cases:
                    samples = []
                    codes = Counter()
                    async def request(i):
                        token, cid = actors[i]
                        t = dict(sql_ms=0., sql_count=0, thread_wait_ms=0., thread_work_ms=0., serialize_ms=0.)
                        ctx = trace.set(t)
                        began = perf_counter()
                        try:
                            if case in ("raw50", "orm50"):
                                count = await anyio.to_thread.run_sync(raw_read if case == "raw50" else orm_read, cid)
                                codes[str(count)] += 1
                            else:
                                path = "/api/panel/me" if case == "profile" else "/api/panel/conversations" if case == "inbox" else (
                                    f"/api/panel/conversations/{cid}/messages?limit=" +
                                    ("1" if case == "history1" else "10" if case == "history10" else "50") +
                                    "&mark_read=" + ("true" if case == "history50_read" else "false"))
                                response = await client.get(path, headers={"Cookie": f"{SESSION_COOKIE}={token}"})
                                codes[str(response.status_code)] += 1
                                t["bytes"] = len(response.content)
                        finally:
                            t["total_ms"] = (perf_counter() - began) * 1000
                            samples.append(t)
                            trace.reset(ctx)
                    # Warm caches at the same endpoint, then time a reproducible burst.
                    await request(0)
                    samples.clear()
                    codes.clear()
                    began = perf_counter()
                    for _ in range(20 if n == 1 else 2):
                        await asyncio.gather(*(request(i) for i in range(n)))
                    elapsed = perf_counter() - began
                    row = {"case": case, "threads": threads, "concurrency": n,
                           "requests": len(samples), "codes": dict(codes),
                           "rps": round(len(samples)/elapsed, 2),
                           "p95_ms": percentile([s["total_ms"] for s in samples],95),
                           **{key+"_mean": round(statistics.mean(s.get(key,0) for s in samples),2)
                              for key in ("total_ms","sql_ms","sql_count","thread_wait_ms","thread_work_ms","serialize_ms","bytes")}}
                    print(json.dumps(row), flush=True)
                    results.append(row)
                    if case in ("raw50","orm50"):
                        assert codes == {"50":len(samples)}, row
                    else:
                        assert codes == {"200":len(samples)}, row
        limiter.total_tokens = original_tokens
        return results

    try:
        results = asyncio.run(bench())
        Path(args.output).write_text(json.dumps(results, indent=2))
    finally:
        anyio.to_thread.run_sync = original_thread
        fastapi.routing.serialize_response = original_serialize
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=int, default=100000)
    parser.add_argument("--clients", type=int, nargs="+", default=[100])
    parser.add_argument("--output", default="sqlite-read-profile.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="uknow-read-profile-") as folder:
        main(args, folder)
