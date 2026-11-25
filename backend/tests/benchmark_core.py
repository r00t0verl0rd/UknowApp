"""Synthetic ASGI benchmark. No production DB or network access."""
import argparse
import asyncio
import hashlib
import json
import math
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import perf_counter

import httpx
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app
from app.models import Assignment, Conversation, Message, PanelSession, User
from app.modules.auth import service as auth
from app.modules.dependencies import get_db


def percentile(values, percent):
    return round(sorted(values)[max(0, math.ceil(len(values)*percent/100)-1)], 3)


def run(messages, clients, rounds):
    with tempfile.TemporaryDirectory(prefix="uknow-perf-") as temp:
        engine = create_engine("sqlite:///" + str(Path(temp)/"benchmark.db"),
                               connect_args={"check_same_thread":False}, pool_size=10, max_overflow=30)
        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        password_hash = "synthetic-credential-fingerprint-only"  # No usable account password.
        token = "isolated-benchmark-session"
        with sessions() as db:
            teacher = User(full_name="Benchmark Teacher", role="teacher", web_password_hash=password_hash)
            student = User(full_name="Benchmark Student", role="student")
            db.add_all([teacher, student])
            db.flush()
            assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
            db.add(assignment)
            db.flush()
            chat = Conversation(assignment_id=assignment.id, teacher_id=teacher.id, student_id=student.id, status="active")
            db.add(chat)
            db.flush()
            chat_id = chat.id
            for start in range(0, messages, 2000):
                db.execute(insert(Message), [
                    dict(conversation_id=chat_id, sender_id=student.id if i%2 else teacher.id,
                         sender_role="student" if i%2 else "teacher", text=f"Message {i}",
                         metadata_json='{"teacher_read_at":"2026-01-01","student_read_at":"2026-01-01"}')
                    for i in range(start,min(start+2000,messages))
                ])
            db.add(PanelSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                 role="teacher",user_id=teacher.id,
                 credential_fingerprint=hashlib.sha256(password_hash.encode()).hexdigest(),
                 expires_at=datetime.now(UTC)+timedelta(hours=1)))
            db.commit()

        def get_test_db():
            with sessions() as db:
                yield db
        previous = auth.SessionLocal
        old_override = app.dependency_overrides.get(get_db)
        auth.SessionLocal = sessions
        app.dependency_overrides[get_db] = get_test_db
        count = 0
        lock = Lock()
        @event.listens_for(engine,"before_cursor_execute")
        def count_sql(*_):
            nonlocal count
            with lock:
                count += 1

        async def benchmark():
            results = []
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://benchmark",
                                         cookies={auth.SESSION_COOKIE:token}) as client:
                paths = {
                    "profile":"/api/panel/me",
                    "history_50":f"/api/panel/conversations/{chat_id}/messages?limit=50&mark_read=false",
                    "inbox":"/api/panel/conversations",
                }
                for name,path in paths.items():
                    response = await client.get(path)
                    response.raise_for_status()
                    for concurrency in clients:
                        start_count = count
                        samples = []
                        started = perf_counter()
                        async def request():
                            before = perf_counter()
                            response = await client.get(path)
                            response.raise_for_status()
                            samples.append((perf_counter()-before)*1000)
                        for _ in range(rounds):
                            await asyncio.gather(*(request() for _ in range(concurrency)))
                        results.append({
                            "scenario":name,"concurrency":concurrency,"requests":len(samples),
                            "p50_ms":percentile(samples,50),"p95_ms":percentile(samples,95),
                            "p99_ms":percentile(samples,99),
                            "requests_per_sec":round(len(samples)/(perf_counter()-started),2),
                            "sql_per_request":round((count-start_count)/len(samples),2),
                        })
                return results
        try:
            return asyncio.run(benchmark())
        finally:
            auth.SessionLocal = previous
            if old_override is None:
                app.dependency_overrides.pop(get_db,None)
            else:
                app.dependency_overrides[get_db] = old_override
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages",type=int,default=100000)
    parser.add_argument("--clients",type=int,nargs="+",default=[10,50,100])
    parser.add_argument("--rounds",type=int,default=2)
    args = parser.parse_args()
    if args.messages < 1 or args.rounds < 1 or any(c<1 or c>200 for c in args.clients):
        parser.error("positive messages/rounds and concurrency 1..200 required")
    print(json.dumps({"messages":args.messages,"results":run(args.messages,args.clients,args.rounds)},indent=2))
