from app.modules.notifications import endpoints


def test_rejects_local_and_untrusted_push_destinations(monkeypatch):
    monkeypatch.setattr(
        endpoints.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    assert not endpoints.is_safe_push_endpoint("https://fcm.googleapis.com/push/token")
    assert not endpoints.is_safe_push_endpoint("http://localhost/push")
    assert not endpoints.is_safe_push_endpoint("https://attacker.example/push")
    assert not endpoints.is_safe_push_endpoint("https://user@fcm.googleapis.com/push")


def test_accepts_known_provider_with_public_dns(monkeypatch):
    monkeypatch.setattr(
        endpoints.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("142.250.72.138", 443))],
    )
    assert endpoints.is_safe_push_endpoint("https://fcm.googleapis.com/fcm/send/token")
