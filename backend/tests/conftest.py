"""Shared isolated database and API client for backend integration tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import hash_web_password
from app.main import app
from app.models import User
from app.modules.dependencies import get_db
from app.core import security


@pytest.fixture
def api(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with test_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(security, "SessionLocal", test_sessions)
    monkeypatch.setattr(security, "ADMIN_USERNAME", "test-admin")
    monkeypatch.setattr(security, "ADMIN_PASSWORD", "a-long-test-password-123")

    with test_sessions() as db:
        db.add_all([
            User(full_name="Teacher One", web_username="teacher-one", role="teacher",
                 web_password_hash=hash_web_password("teacher-password-1")),
            User(full_name="Teacher Two", web_username="teacher-two", role="teacher",
                 web_password_hash=hash_web_password("teacher-password-2")),
            User(full_name="Student One", web_username="student-one", role="student",
                 web_password_hash=hash_web_password("student-password-1")),
            User(full_name="Student Two", web_username="student-two", role="student",
                 web_password_hash=hash_web_password("student-password-2")),
        ])
        db.commit()
        users = {user.web_username: user.id for user in db.query(User).all()}

    clients = []

    def make_client():
        client = TestClient(app)
        clients.append(client)
        return client

    yield make_client, users

    for client in clients:
        client.close()
    app.dependency_overrides.clear()
    engine.dispose()
