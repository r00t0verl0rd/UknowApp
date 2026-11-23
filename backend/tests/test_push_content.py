import json

from app.modules.notifications import service as push_service
from app.modules.notifications.content import PUSH_TITLE, push_body


def test_message_push_is_short_without_duplicate_app_name():
    message = push_body("Падаван", "  Привет!  Как дела? ")
    assert PUSH_TITLE == "Новое сообщение"
    assert message == "Падаван: Привет! Как дела?"
    assert "UknowApp" not in message


def test_admin_gets_both_names_and_direction():
    message = push_body(
        "Учитель Анна", "   Домашнее задание готово  ",
        recipient_name="Ученик Иван",
    )
    assert message == "Учитель Анна → Ученик Иван: Домашнее задание готово"
    assert push_body("Ученик Иван", "Спасибо", recipient_name="Учитель Анна") == (
        "Ученик Иван → Учитель Анна: Спасибо"
    )


def test_media_preview_and_long_text_are_concise():
    assert push_body("Администратор", "", kind="document") == "Администратор: Файл"
    assert push_body("Падаван", "", kind="voice") == "Падаван: Голосовое"
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
    assert [item["body"] for item in sent] == [
        "Анна: Привет", "Анна → Иван: Привет",
    ]
