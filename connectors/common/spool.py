"""Durable, connector-local transport inbox (not the UknowApp database)."""
import asyncio
import json
import sqlite3
from pathlib import Path

MAX_EVENTS = 10000


class EventSpool:
    def __init__(self, path, namespace):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (namespace TEXT PRIMARY KEY, cursor INTEGER)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, namespace TEXT NOT NULL,
            event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS deliveries (namespace TEXT NOT NULL, id TEXT NOT NULL, result TEXT, PRIMARY KEY(namespace,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS selections (namespace TEXT NOT NULL, actor TEXT NOT NULL, conversation INTEGER, PRIMARY KEY(namespace,actor))")
        self.db.execute("CREATE TABLE IF NOT EXISTS panels (namespace TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(namespace,actor))")
        self.db.commit()
        self.namespace = namespace
        self.changed = asyncio.Event()

    def cursor(self):
        row = self.db.execute("SELECT cursor FROM state WHERE namespace=?", (self.namespace,)).fetchone()
        return row[0] if row else None

    def count(self):
        return self.db.execute("SELECT count(*) FROM events WHERE namespace=?", (self.namespace,)).fetchone()[0]

    def append(self, updates, cursor):
        # Commit events and provider offset together, before acknowledging the provider.
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO events (namespace,event_id,payload) VALUES (?,?,?)", [
                (self.namespace, event_id, json.dumps(payload, ensure_ascii=False))
                for event_id, payload in updates
            ])
            self.db.execute("""INSERT INTO state(namespace,cursor) VALUES (?,?)
                ON CONFLICT(namespace) DO UPDATE SET cursor=excluded.cursor""", (self.namespace, cursor))
        self.changed.set()

    async def wait_for_event(self):
        self.changed.clear()
        if self.first() is None:
            await self.changed.wait()

    def first(self):
        row = self.db.execute(
            "SELECT event_id,payload FROM events WHERE namespace=? ORDER BY seq LIMIT 1",
            (self.namespace,),
        ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def ack(self, event_id):
        with self.db:
            self.db.execute("DELETE FROM events WHERE namespace=? AND event_id=?", (self.namespace, event_id))

    def close(self):
        self.db.close()

    def delivery(self, job_id):
        row = self.db.execute("SELECT result FROM deliveries WHERE namespace=? AND id=?",
                              (self.namespace, job_id)).fetchone()
        if row is None:
            return None
        return json.loads(row[0]) if row[0] else {"id": job_id, "status": "unknown"}

    def begin_delivery(self, job_id):
        with self.db:
            self.db.execute("INSERT INTO deliveries(namespace,id,result) VALUES (?,?,NULL)",
                            (self.namespace, job_id))

    def finish_delivery(self, job_id, receipt):
        with self.db:
            self.db.execute("UPDATE deliveries SET result=? WHERE namespace=? AND id=?",
                            (json.dumps(receipt), self.namespace, job_id))

    def select_conversation(self, actor, conversation):
        with self.db:
            self.db.execute("""INSERT INTO selections(namespace,actor,conversation) VALUES (?,?,?)
                ON CONFLICT(namespace,actor) DO UPDATE SET conversation=excluded.conversation""",
                (self.namespace, actor, conversation))

    def selected_conversation(self, actor):
        row = self.db.execute("SELECT conversation FROM selections WHERE namespace=? AND actor=?",
                              (self.namespace, actor)).fetchone()
        return row[0] if row else None

    def panel(self, actor):
        row = self.db.execute("SELECT payload FROM panels WHERE namespace=? AND actor=?",
                              (self.namespace, actor)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_panel(self, actor, panel):
        with self.db:
            self.db.execute("""INSERT INTO panels(namespace,actor,payload) VALUES (?,?,?)
                ON CONFLICT(namespace,actor) DO UPDATE SET payload=excluded.payload""",
                (self.namespace, actor, json.dumps(panel)))
