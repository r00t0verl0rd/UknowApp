from fastapi import status
from starlette.requests import Request

from app.core import security
from app.models import Assignment, Conversation, Message


def login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == status.HTTP_200_OK
    return response.json()


def test_authentication_rejects_invalid_credentials(api):
    make_client, _, _ = api
    client = make_client()
    invalid_credential = "incorrect-value"
    response = client.post(
        "/api/auth/login",
        json={"username": "teacher-one", "password": invalid_credential},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_only_assignment_and_conversation_isolation(api):
    make_client, users, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")

    created = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert created.status_code == status.HTTP_201_CREATED
    conversation_id = created.json()["id"]
    with sessions() as db:
        db.add(Message(
            conversation_id=conversation_id,
            sender_id=users["student-one"],
            sender_role="student",
            text="Private conversation message",
        ))
        db.commit()

    teacher_one = make_client()
    login(teacher_one, "teacher-one", "teacher-password-1")
    teacher_two = make_client()
    login(teacher_two, "teacher-two", "teacher-password-2")
    student_one = make_client()
    login(student_one, "student-one", "student-password-1")
    student_two = make_client()
    login(student_two, "student-two", "student-password-2")

    assert len(teacher_one.get("/api/panel/conversations").json()) == 1
    assert teacher_two.get("/api/panel/conversations").json() == []
    assert len(student_one.get("/api/panel/conversations").json()) == 1
    assert student_two.get("/api/panel/conversations").json() == []

    teacher_messages = teacher_one.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    )
    assert teacher_messages.status_code == status.HTTP_200_OK
    assert teacher_messages.json()[0]["text"] == "Private conversation message"
    assert teacher_two.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    ).status_code == status.HTTP_404_NOT_FOUND
    assert student_two.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    ).status_code == status.HTTP_404_NOT_FOUND

    forbidden = teacher_one.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-two"]},
    )
    assert forbidden.status_code == status.HTTP_401_UNAUTHORIZED


def test_panel_routes_require_authentication(api):
    make_client, _, _ = api
    client = make_client()
    assert client.get("/api/panel/conversations").status_code == status.HTTP_401_UNAUTHORIZED

def test_forwarded_client_ip_is_trusted_only_from_proxy(monkeypatch):
    monkeypatch.setattr(security, "TRUSTED_PROXY_IPS", {"127.0.0.1"})

    def request(peer, headers):
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
            "client": (peer, 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        })

    trusted = request("127.0.0.1", {"cf-connecting-ip": "203.0.113.8"})
    untrusted = request("198.51.100.4", {"cf-connecting-ip": "203.0.113.8"})
    assert security._client_ip(trusted) == "203.0.113.8"
    assert security._client_ip(untrusted) == "198.51.100.4"

def test_health_checks_database_connection(api):
    make_client, _, _ = api
    response = make_client().get("/api/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["components"]["database"] == "ok"
    assert response.json()["components"]["bots_gateway"] == "disabled"
    assert response.json()["status"] == "ok"


def test_admin_can_unassign_student_without_deleting_conversation_history(api):
    make_client, users, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    created = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert created.status_code == status.HTTP_201_CREATED
    conversation_id = created.json()["id"]
    with sessions() as db:
        db.add(Message(
            conversation_id=conversation_id,
            sender_id=users["student-one"],
            sender_role="student",
            text="History must remain",
        ))
        db.commit()

    response = admin.delete(f"/api/admin/assignments/{users['student-one']}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"ok": True, "student_id": users["student-one"]}

    with sessions() as db:
        assignment = db.query(Assignment).one()
        conversation = db.get(Conversation, conversation_id)
        assert assignment.active is False
        assert assignment.closed_at is not None
        assert conversation.status == "closed"
        assert conversation.assignment_id is None
        assert db.query(Message).filter(Message.conversation_id == conversation_id).one().text == "History must remain"

    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    student = make_client()
    login(student, "student-one", "student-password-1")
    assert teacher.get("/api/panel/conversations").json() == []
    assert student.get("/api/panel/conversations").json() == []
    assert admin.delete(f"/api/admin/assignments/{users['student-one']}").status_code == status.HTTP_404_NOT_FOUND


def test_admin_dialogue_cleanup_accepts_all_retention_options(api, monkeypatch, tmp_path):
    from app.modules.administration import data as admin_data

    make_client, _, sessions = api
    monkeypatch.setattr(admin_data, "SessionLocal", sessions)
    monkeypatch.setattr(admin_data, "MEDIA_DIR", tmp_path)

    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")

    for days in (30, 60, 180, 360):
        response = admin.delete(
            "/api/admin/data/dialogues",
            params={"days": days},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["days"] == days

    unsupported = admin.delete(
        "/api/admin/data/dialogues",
        params={"days": 120},
    )
    assert unsupported.status_code == status.HTTP_400_BAD_REQUEST
    assert unsupported.json()["detail"] == "Выберите срок 30, 60, 180 или 360 дней"



def test_reassigning_student_to_same_teacher_restores_conversation_history(api):
    make_client, users, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")

    created = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert created.status_code == status.HTTP_201_CREATED
    conversation_id = created.json()["id"]

    with sessions() as db:
        db.add(Message(
            conversation_id=conversation_id,
            sender_id=users["student-one"],
            sender_role="student",
            text="История должна восстановиться",
        ))
        db.commit()

    unassigned = admin.delete(f"/api/admin/assignments/{users['student-one']}")
    assert unassigned.status_code == status.HTTP_200_OK

    restored = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert restored.status_code == status.HTTP_201_CREATED
    assert restored.json()["id"] == conversation_id
    assert restored.json()["status"] == "active"

    with sessions() as db:
        conversation = db.get(Conversation, conversation_id)
        active_assignment = db.query(Assignment).filter(Assignment.active.is_(True)).one()
        messages = db.query(Message).filter(Message.conversation_id == conversation_id).all()
        assert conversation.status == "active"
        assert conversation.assignment_id == active_assignment.id
        assert active_assignment.teacher_id == users["teacher-one"]
        assert active_assignment.student_id == users["student-one"]
        assert len(messages) == 1
        assert messages[0].text == "История должна восстановиться"
        assert db.query(Conversation).count() == 1

    teacher = make_client()
    login(teacher, "teacher-one", "teacher-password-1")
    inbox = teacher.get("/api/panel/conversations")
    history = teacher.get(f"/api/panel/conversations/{conversation_id}/messages")
    assert inbox.status_code == status.HTTP_200_OK
    assert [item["id"] for item in inbox.json()] == [conversation_id]
    assert history.status_code == status.HTTP_200_OK
    assert history.json()[0]["text"] == "История должна восстановиться"


def test_reassigning_student_to_different_teacher_creates_separate_conversation(api):
    make_client, users, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")

    first = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert first.status_code == status.HTTP_201_CREATED
    old_conversation_id = first.json()["id"]

    with sessions() as db:
        db.add(Message(
            conversation_id=old_conversation_id,
            sender_id=users["student-one"],
            sender_role="student",
            text="История прежнего учителя",
        ))
        db.commit()

    unassigned = admin.delete(f"/api/admin/assignments/{users['student-one']}")
    assert unassigned.status_code == status.HTTP_200_OK

    second = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-two"], "student_id": users["student-one"]},
    )
    assert second.status_code == status.HTTP_201_CREATED
    new_conversation_id = second.json()["id"]
    assert new_conversation_id != old_conversation_id

    with sessions() as db:
        old_conversation = db.get(Conversation, old_conversation_id)
        new_conversation = db.get(Conversation, new_conversation_id)
        assert old_conversation.status == "closed"
        assert old_conversation.assignment_id is None
        assert new_conversation.status == "active"
        assert db.query(Message).filter(
            Message.conversation_id == old_conversation_id,
        ).one().text == "История прежнего учителя"

    teacher_one = make_client()
    login(teacher_one, "teacher-one", "teacher-password-1")
    teacher_two = make_client()
    login(teacher_two, "teacher-two", "teacher-password-2")
    student = make_client()
    login(student, "student-one", "student-password-1")

    assert teacher_one.get("/api/panel/conversations").json() == []
    assert [item["id"] for item in teacher_two.get("/api/panel/conversations").json()] == [
        new_conversation_id,
    ]
    assert [item["id"] for item in student.get("/api/panel/conversations").json()] == [
        new_conversation_id,
    ]
    assert teacher_two.get(
        f"/api/panel/conversations/{old_conversation_id}/messages",
    ).status_code == status.HTTP_404_NOT_FOUND


def test_workspace_permissions_are_server_derived(api):
    make_client, _, _ = api
    client = make_client()
    login(client, "teacher-one", "teacher-password-1")
    profile = client.get("/api/panel/me", params={"role": "admin"}).json()
    assert set(profile["permissions"]) == {"structure.view", "dialogs.own", "boards.view"}
    assert client.get("/api/admin/users").status_code == 401
    login(client, "student-one", "student-password-1")
    assert set(client.get("/api/panel/me").json()["permissions"]) == {"dialogs.own", "boards.view"}


def test_expired_session_loses_profile_and_admin_access(api):
    from datetime import UTC, datetime, timedelta
    from app.models import PanelSession

    make_client, _, sessions = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    with sessions() as db:
        db.query(PanelSession).one().expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert admin.get("/api/panel/me").status_code == 401
    assert admin.get("/api/admin/users").status_code == 401


def test_admin_posts_as_admin_in_observed_dialog(api):
    make_client, users, _ = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")
    chat = admin.post("/api/admin/assignments", json={
        "teacher_id": users["teacher-one"], "student_id": users["student-one"],
    }).json()
    path = f"/api/panel/conversations/{chat['id']}/messages"
    assert admin.post(path, json={"text": "Сообщение администрации"}).status_code == 201
    student = make_client()
    login(student, "student-one", "student-password-1")
    assert student.get(path).json()[0]["sender_role"] == "admin"
