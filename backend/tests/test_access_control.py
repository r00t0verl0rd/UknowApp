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
    assert response.json()["status"] == "degraded"


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