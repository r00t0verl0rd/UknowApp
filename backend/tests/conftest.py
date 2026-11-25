"""Изолированная база и API-клиент для тестов."""

import asyncio
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core import runtime_database
from app.core.security import hash_web_password
from app.main import app
from app.models import User
from app.modules.dependencies import get_db
from app.core import security
from app.modules.auth import service as auth_service


@lru_cache(maxsize=4)
def _shared_fixture_password_hash(password: str) -> str:
    """Keep real PBKDF2 verification but hash recurring test passwords only once per run."""
    return hash_web_password(password)


@pytest.fixture
def api(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    runtime_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    runtime_database.RuntimeBase.metadata.create_all(runtime_engine)
    monkeypatch.setattr(runtime_database, "RuntimeSessionLocal", sessionmaker(bind=runtime_engine, autoflush=False, expire_on_commit=False))
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with test_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(auth_service, "SessionLocal", test_sessions)
    monkeypatch.setattr(security, "ADMIN_USERNAME", "test-admin")
    monkeypatch.setattr(security, "ADMIN_PASSWORD", "a-long-test-password-123")

    with test_sessions() as db:
        db.add_all([
            User(full_name="Teacher One", web_username="teacher-one", role="teacher",
                 web_password_hash=_shared_fixture_password_hash("teacher-password-1")),
            User(full_name="Teacher Two", web_username="teacher-two", role="teacher",
                 web_password_hash=_shared_fixture_password_hash("teacher-password-2")),
            User(full_name="Student One", web_username="student-one", role="student",
                 web_password_hash=_shared_fixture_password_hash("student-password-1")),
            User(full_name="Student Two", web_username="student-two", role="student",
                 web_password_hash=_shared_fixture_password_hash("student-password-2")),
        ])
        db.commit()
        users = {user.web_username: user.id for user in db.query(User).all()}

    clients = []

    def make_client():
        client = TestClient(app)
        clients.append(client)
        return client

    yield make_client, users, test_sessions

    for client in clients:
        client.close()
    app.dependency_overrides.clear()
    engine.dispose()
    runtime_engine.dispose()


@pytest.fixture(autouse=True)
def forbid_sync_sql_in_event_loop():
    """Fail regression tests when blocking SQL is executed on an asyncio thread."""
    def check(*_args):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise AssertionError("Synchronous SQLAlchemy executed on an active event loop")

    # Catch checkout, execution and transaction boundaries, including raw SQL.
    listeners = [(Engine, "before_cursor_execute"), (Engine, "commit"), (Engine, "rollback")]
    for target, name in listeners:
        event.listen(target, name, check)
    try:
        yield
    finally:
        for target, name in listeners:
            event.remove(target, name, check)
