"""Isolated API benchmark with real migrated SQLite and synthetic accounts only."""
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
    with engine.connect() as conn:
        print(json.dumps({"journal": conn.exec_driver_sql("PRAGMA journal_mode").scalar(),
                          "chat_read_limit": os.getenv("UKNOWAPP_SQLITE_CHAT_READ_CONCURRENCY", "4"),
                          "pool": engine.pool.status()}), flush=True)
    pairs = (max(args.clients) + 1) // 2
    actors, chats = [], []
    now = datetime.now(UTC)
    # Synthetic credential fingerprint input, never a usable account password.
    credential = hashlib.sha256(os.urandom(32)).hexdigest()
    fingerprint = hashlib.sha256(credential.encode()).hexdigest()
    with SessionLocal() as db:
        for i in range(pairs):
            users = [User(full_name=f"Load {role} {i}", role=role, web_password_hash=credential)
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

    # Real transactional outbox enqueue, but no NATS or external provider calls.
    app.state.bots_gateway = SimpleNamespace(platforms=("telegram", "max"), wake_outbox=lambda: None)

    async def benchmark():
        results = []
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client:
            token, cid = actors[0]
            warmup = await client.get(f"/api/panel/conversations/{cid}/messages?limit=50&mark_read=false",
                                      headers={"Cookie": f"{SESSION_COOKIE}={token}"})
            warmup.raise_for_status()
            for n in args.clients:
                for scenario in ("read", "mixed", "send_burst"):
                    if scenario == "send_burst" and n > 500:
                        continue
                    timings = {"read": [], "write": [], "inbox": []}
                    statuses = Counter()
                    successes = Counter()
                    before = perf_counter()

                    async def request(i, round_no):
                        token, chat = actors[i]
                        headers = {"Cookie": f"{SESSION_COOKIE}={token}"}
                        path = f"/api/panel/conversations/{chat}/messages"
                        write = scenario == "send_burst" or (scenario == "mixed" and (i + round_no) % 10 == 0)
                        kind = "write" if write else ("inbox" if i % 5 == 0 else "read")
                        t0 = perf_counter()
                        try:
                            if write:
                                response = await client.post(path, headers=headers,
                                    json={"text": f"Load {n} {scenario} {round_no} {i}",
                                          "client_message_id": f"load-{n}-{scenario}-{round_no}-{i}"})
                            elif kind == "inbox":
                                response = await client.get("/api/panel/conversations", headers=headers)
                            else:
                                response = await client.get(path + "?limit=50&mark_read=true", headers=headers)
                            statuses[str(response.status_code)] += 1
                            if response.is_success:
                                successes[kind] += 1
                        except Exception as exc:
                            statuses[type(exc).__name__] += 1
                        finally:
                            timings[kind].append((perf_counter() - t0) * 1000)

                    for r in range(args.rounds):
                        await asyncio.gather(*(request(i, r) for i in range(n)))
                    elapsed = perf_counter() - before
                    all_samples = [v for values in timings.values() for v in values]
                    result = {"scenario": scenario, "concurrency": n, "requests": len(all_samples),
                              "ok": sum(successes.values()), "statuses": dict(statuses),
                              "rps": round(len(all_samples) / elapsed, 2),
                              "p50_ms": percentile(all_samples, 50), "p95_ms": percentile(all_samples, 95),
                              "p99_ms": percentile(all_samples, 99),
                              "read_p95_ms": percentile(timings["read"], 95),
                              "write_p95_ms": percentile(timings["write"], 95),
                              "successful_writes": successes["write"],
                              "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
                    results.append(result)
                    print(json.dumps(result), flush=True)
        return results

    results = asyncio.run(benchmark())
    expected = sum(r["successful_writes"] for r in results)
    with SessionLocal() as db:
        actual = db.scalar(select(func.count()).select_from(Message)) - args.messages
        jobs = db.scalar(select(func.count()).select_from(ConnectorDelivery))
    integrity = {"successful_writes": expected, "persisted_new_messages": actual, "outbox_jobs": jobs,
                 "expected_outbox_jobs": actual * 2}
    print(json.dumps(integrity), flush=True)
    Path(args.output).write_text(json.dumps({"results": results, "integrity": integrity}, indent=2))
    engine.dispose()
    if actual != expected or jobs != actual * 2 or any(r["ok"] != r["requests"] for r in results):
        raise RuntimeError("Persisted message or delivery count mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=int, default=1000000)
    parser.add_argument("--clients", type=int, nargs="+", default=[100, 250, 500, 1000, 2000])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", default="sqlite-load-results.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="uknow-load-") as folder:
        main(args, folder)
