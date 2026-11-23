"""Regression tests for the admin statistics endpoint with restored legacy data."""

import sqlite3

from app.models import Conversation, Message, User
from app.modules.administration import data as admin_data


def test_stats_tolerates_legacy_message_metadata(api, monkeypatch, tmp_path):
    make_client, _, test_sessions = api
    data_root = tmp_path / "school-data"
    data_root.mkdir()
    database_path = data_root / "uknowapp.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE test_snapshot (id INTEGER PRIMARY KEY)")
    media_dir = data_root / "media"
    media_dir.mkdir()
    (media_dir / "photo.jpg").write_bytes(b"test-photo")

    monkeypatch.setattr(admin_data, "DATA_DIR", data_root)
    monkeypatch.setattr(admin_data, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(admin_data, "SessionLocal", test_sessions)
    monkeypatch.setattr(admin_data, "_database_path", lambda: database_path)

    legacy_values = [
        "[]", "null", '"legacy text"', '{"media": []}',
        '{"media": "legacy"}', '{"media": {"local_path": null}}',
        '{"media": {"local_path": "photo.jpg", "kind": "photo", "mime_type": 123}}',
        "{broken json",
    ]
    with test_sessions() as db:
        teacher = db.query(User).filter(User.role == "teacher").first()
        student = db.query(User).filter(User.role == "student").first()
        chat = Conversation(teacher_id=teacher.id, student_id=student.id)
        db.add(chat)
        db.flush()
        db.add_all([
            Message(
                conversation_id=chat.id,
                sender_id=teacher.id,
                sender_role="teacher",
                metadata_json=metadata,
                text="",
            )
            for metadata in legacy_values
        ])
        db.commit()

    client = make_client()
    login = client.post(
        "/api/auth/login",
        json={"username": "test-admin", "password": "a-long-test-password-123"},  # pragma: allowlist secret
    )
    assert login.status_code == 200
    response = client.get("/api/admin/data/stats")
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["users"] == 4
    assert stats["teachers"] == 2
    assert stats["students"] == 2
    assert stats["conversations"] == 1
    assert stats["messages"] == len(legacy_values)
    assert stats["media_files"] == 1
    assert stats["media_images"] == 1
    assert stats["media_bytes"] == len(b"test-photo")
