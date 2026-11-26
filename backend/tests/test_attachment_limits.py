import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.infrastructure.storage import media, uploads
from app.modules.panel.session import panel_me


@pytest.mark.parametrize("mode,mib", [("cloud", 20), ("local", 888)])
def test_panel_and_provider_limits(mode, mib, monkeypatch, tmp_path):
    monkeypatch.setenv("BOTS_PLATFORMS", "telegram")
    monkeypatch.setenv("TELEGRAM_API_MODE", mode)
    monkeypatch.setattr(uploads, "MEDIA_DIR", tmp_path)
    limit = mib * 1024 ** 2
    assert media.provider_attachment_limit("telegram") == limit
    assert media.panel_attachment_limit() == limit
    assert panel_me({"role": "admin"})["max_attachment_bytes"] == limit
    assert panel_me({"role": "teacher", "user_id": 1, "full_name": "Teacher"})["max_attachment_bytes"] == limit
    file = SimpleNamespace(size=limit + 1, file=io.BytesIO(), filename="big.bin", content_type="application/octet-stream")
    with pytest.raises(HTTPException) as error:
        uploads.store_panel_attachment(file, 1)
    assert error.value.status_code == 413
    assert str(mib) in error.value.detail


@pytest.mark.parametrize("personal", [False, True])
def test_streaming_boundary_and_cleanup(personal, monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(uploads, "panel_attachment_limit", lambda: 4)
    def upload(data, size=None):
        return uploads.store_panel_attachment(SimpleNamespace(size=size, file=io.BytesIO(data),
            filename="file.bin", content_type="application/octet-stream"), 1, personal=personal)
    size, _, path, _, _ = upload(b"1234", 4)
    assert size == 4
    assert (tmp_path / path).read_bytes() == b"1234"
    with pytest.raises(HTTPException) as error:
        upload(b"12345")
    assert error.value.status_code == 413
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [tmp_path / path]


def test_web_only_retains_archive_limit(monkeypatch):
    monkeypatch.setenv("BOTS_PLATFORMS", "")
    monkeypatch.setenv("TELEGRAM_API_MODE", "cloud")
    assert media.panel_attachment_limit() == 1024 ** 3
    assert media.provider_attachment_limit("other") == 1024 ** 3


@pytest.mark.parametrize("mode,mib", [("cloud", 20), ("local", 888)])
def test_connector_upload_applies_mode_limit(mode, mib, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.bots_gateway import gateway

    monkeypatch.setenv("TELEGRAM_API_MODE", mode)
    secret = "test-secret-" + "x" * 40  # pragma: allowlist secret
    monkeypatch.setenv("BOTS_MEDIA_SECRET_TELEGRAM", secret)
    monkeypatch.setattr(gateway, "MEDIA_DIR", tmp_path)
    real_limit = media.provider_attachment_limit("telegram")
    assert real_limit == mib * 1024 ** 2
    # Exercise the streaming boundary without allocating hundreds of MiB.
    monkeypatch.setattr(gateway, "provider_attachment_limit", lambda platform: 4)
    app = FastAPI()
    app.state.bots_gateway = SimpleNamespace(platforms=("telegram",))
    app.include_router(gateway.router)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + secret}
        path = "/internal/bots/media/telegram/inbound/"
        assert client.put(path + "ok", content=b"1234", headers=headers).json() == {"size": 4}
        assert client.put(path + "big", content=b"12345", headers=headers).status_code == 413
        assert not gateway.media_path("telegram", "big")[0].exists()
        assert not list(tmp_path.rglob("*.part"))
