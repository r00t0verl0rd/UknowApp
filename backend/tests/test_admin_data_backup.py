"""Тесты полного резервного копирования и восстановления."""

import hashlib
import io
import json
import sqlite3
import zipfile

from fastapi import status

from app.modules.administration import data as admin_data


def login_admin(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "test-admin", "password": "a-long-test-password-123"},  # pragma: allowlist secret
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
            json.dumps({"media": {"local_path": media_path, "archive_status": "stored"}}, ensure_ascii=False)
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


def setup_data_root(monkeypatch, root):
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(admin_data, "DATA_DIR", root)
    monkeypatch.setattr(admin_data, "MEDIA_DIR", root / "media")
    monkeypatch.setattr(admin_data, "_database_path", lambda: root / "uknowapp.db")


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


def test_full_backup_refuses_missing_media_references(api, monkeypatch, tmp_path):
    make_client, _, _ = api
    data_root = tmp_path / "data"
    setup_data_root(monkeypatch, data_root)
    create_database(
        data_root / "uknowapp.db",
        media_path="missing-photo.jpg",
    )

    admin = make_client()
    login_admin(admin)
    response = admin.get("/api/admin/data/full")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "отсутствующие медиафайлы" in response.json()["detail"]



def test_backup_tolerates_legacy_text_metadata_but_rejects_broken_media(api, monkeypatch, tmp_path):
    root = tmp_path / "data"
    setup_data_root(monkeypatch, root)
    database = root / "uknowapp.db"
    create_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE messages ADD COLUMN content_type TEXT DEFAULT 'text'")

    client = api[0]()
    login_admin(client)
    for legacy_json in ("null", "[]", '"old-value"', "not valid JSON"):
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE messages SET metadata_json = ?, content_type = 'text'",
                (legacy_json,),
            )
        assert client.get("/api/admin/data/full").status_code == 200

    # A missing/invalid metadata object *is* an error for a real attachment.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE messages SET metadata_json = 'null', content_type = 'voice'")
    response = client.get("/api/admin/data/full")
    assert response.status_code == 409
    assert "медиафайлы" in response.json()["detail"]


def test_full_restore_refuses_zip_path_traversal_without_touching_current_data(api, monkeypatch, tmp_path):
    root = tmp_path / "data"
    setup_data_root(monkeypatch, root)
    database = root / "uknowapp.db"
    create_database(database)
    client = api[0]()
    login_admin(client)
    backup = client.get("/api/admin/data/full")
    assert backup.status_code == 200

    malicious_name = "data/../outside.txt"
    malicious_body = b"should-not-extract"
    modified = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup.content)) as source, zipfile.ZipFile(modified, "w") as output:
        manifest = json.loads(source.read("manifest.json"))
        for item in manifest["files"]:
            output.writestr(item["path"], source.read(item["path"]))
        manifest["files"].append({
            "path": malicious_name,
            "size": len(malicious_body),
            "sha256": hashlib.sha256(malicious_body).hexdigest(),
        })
        manifest["file_count"] += 1
        manifest["unpacked_bytes"] += len(malicious_body)
        output.writestr(malicious_name, malicious_body)
        output.writestr("manifest.json", json.dumps(manifest))

    uploaded = client.post(
        "/api/admin/data/full",
        files={"file": ("unsafe.zip", modified.getvalue(), "application/zip")},
    )
    assert uploaded.status_code == 400
    assert database.is_file()
    assert not (tmp_path / "outside.txt").exists()
    assert not (root / admin_data.PENDING_RESTORE_NAME).exists()


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

    restore_id = uploaded.json()["restore_id"]
    assert admin.get("/api/admin/data/restore-status").json()["restore"] == {
        "id": restore_id, "status": "pending",
    }

    # Рабочие данные не меняются до запуска процедуры восстановления.
    assert (data_root / "obsolete.txt").is_file()
    with sqlite3.connect(data_root / "uknowapp.db") as connection:
        assert connection.execute("SELECT role FROM users WHERE id = 1").fetchone()[0] == "changed"

    assert admin_data.apply_pending_data_restore() is True
    assert admin.get("/api/admin/data/restore-status").json()["restore"]["status"] == "pending"
    admin_data.finish_startup_restore(True)

    with sqlite3.connect(data_root / "uknowapp.db") as connection:
        assert connection.execute("SELECT role FROM users WHERE id = 1").fetchone()[0] == "admin"
    result = admin.get("/api/admin/data/restore-status").json()["restore"]
    assert result["status"] == "completed"
    assert result["id"] == restore_id
    assert media.read_bytes() == b"original-media"
    assert (data_root / "vapid_private.pem").read_bytes() == original_vapid_key
    assert (data_root / "future-state.json").read_text(encoding="utf-8") == "original-state"
    assert not (data_root / "obsolete.txt").exists()
    assert not (data_root / admin_data.PENDING_RESTORE_NAME).exists()


def test_personal_media_checked_on_export_and_import(api, monkeypatch, tmp_path):
    root = tmp_path / "data"
    setup_data_root(monkeypatch, root)
    database = root / "uknowapp.db"
    create_database(database)
    media = root / "media" / "private.txt"
    media.parent.mkdir()
    media.write_bytes(b"abc")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE personal_messages(metadata_json TEXT)")
        db.execute("INSERT INTO personal_messages VALUES (?)", (json.dumps({
            "media": {"local_path": "private.txt", "archive_status": "stored", "file_size": 3},
        }),))
    admin = api[0]()
    login_admin(admin)
    backup = admin.get("/api/admin/data/full")
    assert backup.status_code == 200
    media.write_bytes(b"truncated")
    assert admin.get("/api/admin/data/full").status_code == 409
    # ZIP and manifest agree, but the referenced attachment itself is missing.
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup.content)) as src, zipfile.ZipFile(out, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        records = [item for item in manifest["files"] if item["path"] != "data/media/private.txt"]
        manifest.update(files=records, file_count=len(records), unpacked_bytes=sum(item["size"] for item in records))
        for item in records:
            dst.writestr(item["path"], src.read(item["path"]))
        dst.writestr("manifest.json", json.dumps(manifest))
    response = admin.post("/api/admin/data/full", files={"file": ("partial.zip", out.getvalue())})
    assert response.status_code == 409
    assert not (root / admin_data.PENDING_RESTORE_NAME).exists()


def test_interrupted_full_restore_returns_original_directory(api, monkeypatch, tmp_path):
    monkeypatch.delenv("UKNOWAPP_AUTO_RESTART_ON_RESTORE", raising=False)
    root = tmp_path / "data"
    setup_data_root(monkeypatch, root)
    create_database(root / "uknowapp.db")
    admin = api[0]()
    login_admin(admin)
    # Exactly the maximum number of data entries plus the manifest.
    monkeypatch.setattr(admin_data, "MAX_ARCHIVE_ENTRIES", 1)
    backup = admin.get("/api/admin/data/full")
    assert backup.status_code == 200
    (root / "original-only").write_text("before")
    assert admin.post("/api/admin/data/full", files={"file": ("full.zip", backup.content)}).status_code == 202
    assert admin_data.apply_pending_data_restore()
    assert not (root / "original-only").exists()
    # Simulate a new process before startup confirmed the replacement.
    assert not admin_data.apply_pending_data_restore()
    assert (root / "original-only").read_text() == "before"
    assert admin.get("/api/admin/data/restore-status").json()["restore"]["status"] == "failed"


def test_transfer_to_new_sqlite_path_and_checksum_failure(api, monkeypatch, tmp_path):
    monkeypatch.delenv("UKNOWAPP_AUTO_RESTART_ON_RESTORE", raising=False)
    root = tmp_path / "data"
    setup_data_root(monkeypatch, root)
    create_database(root / "uknowapp.db")
    admin = api[0]()
    login_admin(admin)
    archive = admin.get("/api/admin/data/full")
    assert archive.status_code == 200
    damaged = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive.content)) as src, zipfile.ZipFile(damaged, "w") as dst:
        for name in src.namelist():
            body = src.read(name)
            if name == "data/uknowapp.db":
                body = body[:-1] + bytes([body[-1] ^ 1])
            dst.writestr(name, body)
    assert admin.post("/api/admin/data/full", files={"file": ("bad.zip", damaged.getvalue())}).status_code == 400
    assert not (root / admin_data.PENDING_RESTORE_NAME).exists()

    destination = root / "new" / "school.sqlite3"
    monkeypatch.setattr(admin_data, "_database_path", lambda: destination)
    assert admin.post("/api/admin/data/full", files={"file": ("copy.zip", archive.content)}).status_code == 202
    assert admin_data.apply_pending_data_restore()
    with sqlite3.connect(destination) as db:
        assert db.execute("SELECT role FROM users").fetchone() == ("admin",)
    admin_data.finish_startup_restore(True)
