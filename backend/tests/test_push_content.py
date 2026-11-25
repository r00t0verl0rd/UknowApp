import json

from app.core import config
from app.modules.notifications import service as push_service
from app.modules.notifications.content import PUSH_TITLE, push_body


def test_default_push_adds_from_prefix_without_direction(monkeypatch):
    monkeypatch.setattr(config, "PUSH_MESSAGE_PREVIEW_ENABLED", False)
    assert PUSH_TITLE == "Сообщение"
    assert push_body("Падаван", "Привет! Как дела?") == "от Падаван"
    assert push_body("Администратор", "Личное сообщение") == "от Администратор"
    assert push_body("Падаван", "", kind="voice") == "от Падаван"


def test_admin_push_shows_direction_but_not_text(monkeypatch):
    monkeypatch.setattr(config, "PUSH_MESSAGE_PREVIEW_ENABLED", False)
    assert push_body("Учитель Анна", "Домашнее задание готово", recipient_name="Ученик Иван") == (
        "Учитель Анна → Ученик Иван"
    )
    assert push_body("Ученик Иван", "Спасибо", recipient_name="Учитель Анна") == (
        "Ученик Иван → Учитель Анна"
    )
    assert push_body("Анна", "секретный текст", recipient_name="Иван", kind="document") == "Анна → Иван"


def test_optional_previews_can_be_switched_on(monkeypatch):
    monkeypatch.setattr(config, "PUSH_MESSAGE_PREVIEW_ENABLED", True)
    assert push_body("Падаван", "  Привет!  Как дела? ") == "от Падаван: Привет! Как дела?"
    assert push_body("Учитель Анна", "Домашнее задание", recipient_name="Иван") == (
        "Учитель Анна → Иван: Домашнее задание"
    )
    assert push_body("Администратор", "", kind="document") == "от Администратор: Файл"
    assert push_body("Падаван", "", kind="voice") == "от Падаван: Голосовое"
    message = push_body("А" * 120, "Б" * 400, recipient_name="В" * 120)
    assert len(message) <= 155
    assert message.endswith("…")


def test_push_delivery_selects_admin_specific_payload(monkeypatch):
    sent = []
    monkeypatch.setattr(push_service, "is_safe_push_endpoint", lambda endpoint: True)
    monkeypatch.setattr(
        push_service, "webpush", lambda **kwargs: sent.append(json.loads(kwargs["data"])),
    )
    base = {"endpoint": "https://web.push.apple.com/something",
            "keys": {"p256dh": "key", "auth": "auth"}}
    targets = [
        {"id": 1, "role": "teacher", **base},
        {"id": 2, "role": "admin", **base},
    ]
    push_service._deliver(
        targets, json.dumps({"body": "Анна: Привет"}),
        json.dumps({"body": "Анна → Иван: Привет"}),
    )
    assert sorted(item["body"] for item in sent) == sorted([
        "Анна: Привет", "Анна → Иван: Привет",
    ])
