"""Тесты поиска логинов с учётом Unicode."""

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.security import hash_web_password
from app.models import User
from app.modules.users.service import validate_panel_username


def test_unicode_panel_login_tracks_rename(api):
    make_client, _, session_factory = api
    with session_factory() as db:
        db.add(User(
            full_name="Тестовый преподаватель",
            web_username="Преподаватель",
            role="teacher",
            web_password_hash=hash_web_password("unicode-pass"),
        ))
        db.commit()
        user = db.scalar(select(User).where(User.web_username == "Преподаватель"))
        assert user.web_login_key == "преподаватель"
        user_id = user.id

    client = make_client()
    assert client.post("/api/auth/login", json={
        "username": "ПРЕПОДАВАТЕЛЬ", "password": "unicode-pass",  # pragma: allowlist secret
    }).status_code == status.HTTP_200_OK

    with session_factory() as db:
        user = db.get(User, user_id)
        user.web_username = "НОВЫЙ ЛОГИН"
        db.commit()
        assert db.get(User, user_id).web_login_key == "новый логин"

    assert client.post("/api/auth/login", json={
        "username": "Преподаватель", "password": "unicode-pass",  # pragma: allowlist secret
    }).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.post("/api/auth/login", json={
        "username": "новый логин", "password": "unicode-pass",  # pragma: allowlist secret
    }).status_code == status.HTTP_200_OK


def test_collision_check_is_casefolded_and_indexed(api):
    _, _, session_factory = api
    with session_factory() as db:
        db.add(User(
            full_name="Петрова Елена",
            web_username="Учитель",
            role="teacher",
            web_password_hash=hash_web_password("unicode-pass"),
        ))
        db.commit()
        try:
            validate_panel_username(db, "УЧИТЕЛЬ")
        except HTTPException as exc:
            assert exc.status_code == status.HTTP_409_CONFLICT
        else:
            raise AssertionError("Duplicate username accepted")
