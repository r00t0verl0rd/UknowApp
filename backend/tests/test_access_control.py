from fastapi import status


def login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == status.HTTP_200_OK
    return response.json()


def test_authentication_rejects_invalid_credentials(api):
    make_client, _ = api
    client = make_client()
    response = client.post(
        "/api/auth/login",
        json={"username": "teacher-one", "password": "wrong-password"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_only_assignment_and_conversation_isolation(api):
    make_client, users = api
    admin = make_client()
    login(admin, "test-admin", "a-long-test-password-123")

    created = admin.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-one"]},
    )
    assert created.status_code == status.HTTP_201_CREATED
    conversation_id = created.json()["id"]

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

    assert teacher_one.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    ).status_code == status.HTTP_200_OK
    assert teacher_two.get(
        f"/api/panel/conversations/{conversation_id}/messages",
    ).status_code == status.HTTP_404_NOT_FOUND

    forbidden = teacher_one.post(
        "/api/admin/assignments",
        json={"teacher_id": users["teacher-one"], "student_id": users["student-two"]},
    )
    assert forbidden.status_code == status.HTTP_401_UNAUTHORIZED


def test_panel_routes_require_authentication(api):
    make_client, _ = api
    client = make_client()
    assert client.get("/api/panel/conversations").status_code == status.HTTP_401_UNAUTHORIZED
