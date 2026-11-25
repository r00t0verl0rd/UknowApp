"""Durable, connector-local transport inbox (not the UknowApp database)."""
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
        self.db.commit()
        self.namespace = namespace

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
