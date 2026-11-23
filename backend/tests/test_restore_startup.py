"""Проверяем штатный lifespan на отдельной установке и временном каталоге data."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_transfer_and_startup_rollback(tmp_path):
    source = Path(__file__).resolve().parents[1] / "app"
    shutil.copytree(source, tmp_path / "backend/app", ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "backend"), DATABASE_URL="",
               TELEGRAM_BOT_ENABLED="false", SEED_DEMO_DATA="true",
               UKNOWAPP_AUTO_RESTART_ON_RESTORE="false", ADMIN_USERNAME="test-admin",
               ADMIN_PASSWORD="local-restore-test-password")  # pragma: allowlist secret - fixed test-only credential
    subprocess.run([sys.executable, __file__], cwd=tmp_path, env=env, check=True, timeout=90)


def exercise_transfer():
    import sqlite3
    from fastapi.testclient import TestClient
    from app.main import app
    from app.modules.administration import data

    def login(client):
        client.post("/api/auth/login", json={
            "username": "test-admin", "password": "local-restore-test-password",
        }).raise_for_status()

    with TestClient(app) as client:
        login(client)
        chat = client.get("/api/panel/conversations").json()[0]
        personal = client.post("/api/panel/personal-conversations", json={"user_id": chat["student"]["id"]}).json()
        media = {}
        for collection, messages, conversation in (
            ("conversations", "messages", chat),
            ("personal-conversations", "personal-messages", personal),
        ):
            content = collection.encode()
            response = client.post(f"/api/panel/{collection}/{conversation['id']}/attachments",
                                   files={"file": ("report.txt", content, "text/plain")})
            response.raise_for_status()
            media[f"/api/panel/{messages}/{response.json()['id']}/media"] = content
        backup = client.get("/api/admin/data/full")
        backup.raise_for_status()
        db = client.get("/api/admin/data/database")
        db.raise_for_status()
        (data.DATA_DIR / "after-export").touch()
        # A restore on a new host must supply the actual attachment bytes.
        shutil.rmtree(data.MEDIA_DIR)
        refused = client.post("/api/admin/data/database", files={"file": ("old.db", db.content)})
        assert refused.status_code == 409
        assert client.post("/api/admin/data/full", files={"file": ("backup.zip", backup.content)}).status_code == 202

    with TestClient(app) as client:
        login(client)
        assert client.get("/api/admin/data/restore-status").json()["restore"]["status"] == "completed"
        assert not (data.DATA_DIR / "after-export").exists()
        for path, expected in media.items():
            response = client.get(path)
            response.raise_for_status()
            assert response.content == expected
        (data.DATA_DIR / "keep-during-db-restore").touch()
        assert client.post("/api/admin/data/database", files={"file": ("backup.db", db.content)}).status_code == 202

    with TestClient(app) as client:
        login(client)
        assert client.get("/api/admin/data/restore-status").json()["restore"]["status"] == "completed"
        assert (data.DATA_DIR / "keep-during-db-restore").exists()
        # SQLite integrity succeeds, but application migrations cannot use this database.
        broken = Path("incompatible.db")
        with sqlite3.connect(broken) as connection:
            connection.executescript("CREATE TABLE users(id INTEGER); CREATE TABLE messages(id INTEGER); CREATE TABLE conversations(id INTEGER);")
        assert client.post("/api/admin/data/database", files={"file": ("old.db", broken.read_bytes())}).status_code == 202
    with TestClient(app) as client:
        login(client)
        assert client.get("/api/admin/data/restore-status").json()["restore"]["status"] == "failed"
        for path, expected in media.items():
            assert client.get(path).content == expected


if __name__ == "__main__":
    exercise_transfer()
