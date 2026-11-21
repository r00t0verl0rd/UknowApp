"""Integration tests for portable full-data backup and staged restore."""

import hashlib
import io
import json
import sqlite3
import zipfile

from fastapi import status

from app.core import config
from app.modules.administration import data as admin_data


def login_admin(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "test-admin", "password": "a-long-test-password-123"},
    )
    assert response.status_code == status.HTTP_200_OK


def create_database(path, media_path=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT NOT NULL);
            CREATE TABLE conversations (id INTEGER PRIMARY KEY);
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                metadata_json TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO users (id, role) VALUES (1, 'admin')")
        connection.execute("INSERT INTO conversations (id) VALUES (1)")
        metadata = (
            json.dumps({"media": {"local_path": media_path}}, ensure_ascii=False)
            if media_path else "{}"
        )
        connection.execute(
            "INSERT INTO messages (id, metadata_json) VALUES (1, ?)",
            (metadata,),
        )
        connection.commit()


def create_vapid_key(path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(private_key)
    return private_key


def make_legacy_archive(database_path, media_bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({
                "format": "uknowapp-full-backup-v1",
                "created_at": "2026-01-01T00:00:00+00:00",
            }),
        )
        archive.write(database_path, "database.sqlite3")
        archive.writestr("media/legacy.bin", media_bytes)
    return buffer.getvalue()


def setup_data_root(monkeypatch, root):
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(admin_data, "DATA_DIR", root)
    monkeypatch.setattr(admin_data, "MEDIA_DIR", root / "media")
    monkeypatch.setattr(admin_data, "_database_path", lambda: root / "uknowapp.db")
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", config.VAPID_PUBLIC_KEY)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", config.VAPID_PRIVATE_KEY)


def test_full_backup_contains_complete_data_directory_and_checksums(api, monkeypatch, tmp_path):
    make_client, _, _ = api
    data_root = tmp_path / "data"
    setup_data_root(monkeypatch, data_root)

    media = data_root / "media" / "photo.bin"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"sample-media")
    create_database(
        data_root / "uknowapp.db",
        media_path="photo.bin",
    )
    create_vapid_key(data_root / "vapid_private.pem")
    future_file = data_root / "future" / "worker-state.json"
    future_file.parent.mkdir()
    future_file.write_text('{"ready":true}', encoding="utf-8")

    admin = make_client()
    login_admin(admin)
    response = admin.get("/api/admin/data/full")

    assert response.status_code == status.HTTP_200_OK
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = set(archive.namelist())
        assert manifest["format"] == "uknowapp-full-backup-v2"
        assert manifest["database_path"] == "uknowapp.db"
        assert "data/uknowapp.db" in names
        assert "data/media/photo.bin" in names
        assert "data/vapid_private.pem" in names
        assert "data/future/worker-state.json" in names
        assert manifest["file_count"] == len(manifest["files"])

        records = {item["path"]: item for item in manifest["files"]}
        for name, record in records.items():
            content = archive.read(name)
            assert len(content) == record["size"]
            assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_full_restore_is_staged_then_applied_before_app_start(api, monkeypatch, tmp_path):
    make_client, _, _ = api
    monkeypatch.delenv("UKNOWAPP_AUTO_RESTART_ON_RESTORE", raising=False)
    data_root = tmp_path / "data"
    setup_data_root(monkeypatch, data_root)

    media = data_root / "media" / "photo.bin"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"original-media")
    create_database(data_root / "uknowapp.db", media_path="photo.bin")
    original_vapid_key = create_vapid_key(data_root / "vapid_private.pem")
    (data_root / "future-state.json").write_text("original-state", encoding="utf-8")

    admin = make_client()
    login_admin(admin)
    downloaded = admin.get("/api/admin/data/full")
    assert downloaded.status_code == status.HTTP_200_OK

    with sqlite3.connect(data_root / "uknowapp.db") as connection:
        connection.execute("UPDATE users SET role = 'changed'")
        connection.commit()
    media.write_bytes(b"changed-media")
    create_vapid_key(data_root / "vapid_private.pem")
    (data_root / "obsolete.txt").write_text("remove-me", encoding="utf-8")

    uploaded = admin.post(
        "/api/admin/data/full",
        files={
            "file": (
                "uknowapp-full-backup.zip",
                downloaded.content,
                "application/zip",
            ),
        },
    )
    assert uploaded.status_code == status.HTTP_202_ACCEPTED
    assert uploaded.json()["restart_required"] is True
    assert (data_root / admin_data.PENDING_RESTORE_NAME).is_file()

    # The live directory is untouched until backend startup applies the prepared archive.
    assert (data_root / "obsolete.txt").is_file()
    with sqlite3.connect(data_root / "uknowapp.db") as connection:
        assert connection.execute("SELECT role FROM users WHERE id = 1").fetchone()[0] == "changed"

    assert admin_data.apply_pending_data_restore() is True

    with sqlite3.connect(data_root / "uknowapp.db") as connection:
        assert connection.execute("SELECT role FROM users WHERE id = 1").fetchone()[0] == "admin"
    assert media.read_bytes() == b"original-media"
    assert (data_root / "vapid_private.pem").read_bytes() == original_vapid_key
    assert (data_root / "future-state.json").read_text(encoding="utf-8") == "original-state"
    assert not (data_root / "obsolete.txt").exists()
    assert not (data_root / admin_data.PENDING_RESTORE_NAME).exists()


def test_legacy_full_backup_restores_database_and_media_and_keeps_current_key(
    api, monkeypatch, tmp_path,
):
    make_client, _, _ = api
    monkeypatch.delenv("UKNOWAPP_AUTO_RESTART_ON_RESTORE", raising=False)
    data_root = tmp_path / "data"
    setup_data_root(monkeypatch, data_root)

    create_database(data_root / "uknowapp.db")
    target_vapid_key = create_vapid_key(data_root / "vapid_private.pem")
    old_database = tmp_path / "old.sqlite3"
    create_database(old_database)
    archive_bytes = make_legacy_archive(old_database, b"legacy-media")

    admin = make_client()
    login_admin(admin)
    uploaded = admin.post(
        "/api/admin/data/full",
        files={"file": ("old-backup.zip", archive_bytes, "application/zip")},
    )
    assert uploaded.status_code == status.HTTP_202_ACCEPTED
    assert uploaded.json()["legacy_format"] is True
    assert admin_data.apply_pending_data_restore() is True

    assert (data_root / "media" / "legacy.bin").read_bytes() == b"legacy-media"
    assert (data_root / "vapid_private.pem").read_bytes() == target_vapid_key
