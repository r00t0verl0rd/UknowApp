"""Permanent, administrator-only removal of personal conversations."""

import json

from app.infrastructure.storage import media
from app.models import PersonalConversation, PersonalMessage
from app.event_hub import current_event_id, replay_chat_updates
from app.modules.personal_chat import operations as personal
from app.modules.panel.session import visible_payload
from test_access_control import login


def test_admin_removes_personal_chat_messages_media_and_orphans(api, monkeypatch, tmp_path):
    make_client, users, sessions = api
    admin = make_client()
    teacher = make_client()
    other = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    login(teacher, "teacher-one", "teacher-password-1")
    login(other, "teacher-two", "teacher-password-2")

    created = admin.post(
        "/api/panel/personal-conversations", json={"user_id": users["teacher-one"]},
    )
    assert created.status_code == 201
    chat_id = created.json()["id"]
    other_created = admin.post(
        "/api/panel/personal-conversations", json={"user_id": users["teacher-two"]},
    )
    assert other_created.status_code == 201
    other_id = other_created.json()["id"]

    base = f"/api/panel/personal-conversations/{chat_id}"
    assert admin.post(base + "/messages", json={"text": "Admin confidential text"}).status_code == 201
    assert teacher.post(base + "/messages", json={"text": "Teacher confidential text"}).status_code == 201
    assert admin.post(
        f"/api/panel/personal-conversations/{other_id}/messages", json={"text": "Keep me"},
    ).status_code == 201

    attachment_folder = tmp_path / "personal" / str(chat_id)
    attachment_folder.mkdir(parents=True)
    attachment = attachment_folder / "private.bin"
    attachment.write_bytes(b"private attachment")
    orphan = attachment_folder / "orphan.bin"
    orphan.write_bytes(b"abandoned upload")
    other_folder = tmp_path / "personal" / str(other_id)
    other_folder.mkdir(parents=True)
    other_file = other_folder / "untouched.bin"
    other_file.write_bytes(b"keep")

    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(personal, "MEDIA_DIR", tmp_path)
    with sessions() as db:
        db.add(PersonalMessage(
            conversation_id=chat_id,
            sender_id=users["teacher-one"],
            sender_role="teacher",
            text="attachment caption",
            metadata_json=json.dumps({
                "media": {
                    "kind": "document",
                    "file_name": "private.bin",
                    "local_path": f"personal/{chat_id}/private.bin",
                    "archive_status": "stored",
                },
            }),
        ))
        db.commit()

    assert teacher.delete(base).status_code == 403
    assert other.delete(base).status_code == 403
    assert admin.get(base + "/messages").status_code == 200
    assert len(teacher.get(base + "/messages").json()) == 3

    cursor = current_event_id()
    response = admin.delete(base)
    assert response.status_code == 200, response.text
    assert response.json()["deleted_conversation_id"] == chat_id
    assert response.json()["deleted_messages"] == 3
    assert not attachment_folder.exists()
    assert not attachment.exists()
    assert not orphan.exists()
    assert other_file.read_bytes() == b"keep"

    with sessions() as db:
        assert db.get(PersonalConversation, chat_id) is None
        assert db.query(PersonalMessage).filter_by(conversation_id=chat_id).count() == 0
        assert db.get(PersonalConversation, other_id) is not None
        assert db.query(PersonalMessage).filter_by(conversation_id=other_id).count() == 1
        events = replay_chat_updates(db, {"role": "teacher", "user_id": users["teacher-one"]}, cursor)
        assert json.loads(events[0][1])["action"] == "delete_conversation"
        assert not replay_chat_updates(db, {"role": "teacher", "user_id": users["teacher-two"]}, cursor)
        assert json.loads(visible_payload(
            db, {"role": "teacher", "user_id": users["teacher-one"]},
            json.dumps({"conversation_id": chat_id, "conversation_type": "personal"}),
        )) == {"resync": True}

    assert teacher.get("/api/panel/personal-conversations").json() == []
    assert {row["id"] for row in admin.get("/api/panel/personal-conversations").json()} == {other_id}
    assert teacher.get(base + "/messages").status_code == 404
    assert admin.get(base + "/summary").status_code == 404
    assert admin.delete(base).status_code == 404

    # A new conversation with the same participant starts without old history.
    fresh = admin.post("/api/panel/personal-conversations", json={"user_id": users["teacher-one"]})
    assert fresh.status_code == 201
    fresh_id = fresh.json()["id"]
    assert admin.get(f"/api/panel/personal-conversations/{fresh_id}/messages").json() == []


def test_delete_personal_chat_requires_admin_and_existing_chat(api):
    make_client, users, sessions = api
    admin = make_client()
    student = make_client()
    anonymous = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    login(student, "student-one", "student-password-1")
    created = admin.post("/api/panel/personal-conversations", json={"user_id": users["student-one"]})
    assert created.status_code == 201
    chat_id = created.json()["id"]
    endpoint = f"/api/panel/personal-conversations/{chat_id}"

    assert anonymous.delete(endpoint).status_code == 401
    assert student.delete(endpoint).status_code == 403
    with sessions() as db:
        assert db.get(PersonalConversation, chat_id) is not None
    assert admin.delete("/api/panel/personal-conversations/9999999").status_code == 404


def test_cleanup_retries_without_reusing_deleted_chat_id(api, monkeypatch, tmp_path):
    make_client, users, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    base = "/api/panel/personal-conversations"
    old = admin.post(base, json={"user_id": users["teacher-one"]}).json()["id"]
    folder = tmp_path / "personal" / str(old)
    folder.mkdir(parents=True)
    (folder / "attachment.bin").write_bytes(b"attachment")
    monkeypatch.setattr(personal, "MEDIA_DIR", tmp_path)

    def disk_error(_path):
        raise OSError("disk unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(personal.shutil, "rmtree", disk_error)
        result = admin.delete(f"{base}/{old}")
    assert result.status_code == 200
    assert result.json()["media_cleanup_pending"] is True
    assert folder.exists()

    fresh = admin.post(base, json={"user_id": users["teacher-two"]}).json()["id"]
    assert fresh != old
    assert admin.delete(f"{base}/{old}").status_code == 404
    monkeypatch.setattr(personal, "SessionLocal", sessions)
    personal.retry_personal_media_cleanup()
    assert not folder.exists()
    with sessions() as db:
        assert db.get(personal.PersonalMediaCleanup, old) is None
    assert admin.get(f"{base}/{fresh}/summary").status_code == 200
