import pytest
from connectors.common.commands import callback_action, panel_revision, recipient_ready
from connectors.common.media_formats import max_inbound_kind, max_upload_kind, telegram_upload_kind, delivery_text
from connectors.common.panel_text import teacher_panel_text
from connectors.common.spool import EventSpool


@pytest.mark.parametrize("kind,mime,name,expected", [
    ("image", "image/gif", "a.gif", "animation"),
    ("audio", "audio/ogg", "a.ogg", "voice"),
    ("sticker", "image/png", "a.png", "sticker"),
    ("video", "video/mp4", "a.mp4", "video"),
])
def test_max_inbound_types(kind, mime, name, expected):
    assert max_inbound_kind(kind, mime, name) == expected


@pytest.mark.parametrize("kind,mime,name,max_kind,tg_kind", [
    ("voice", "audio/ogg", "a.ogg", "file", "voice"),
    ("voice", "audio/mpeg", "a.mp3", "audio", "voice"),
    ("sticker", "image/webp", "a.webp", "file", "document"),
    ("sticker", "image/png", "a.png", "image", "photo"),
    ("sticker", "application/octet-stream", "a.tgs", "file", "document"),
    ("video_note", "video/mp4", "a.mp4", "video", "video"),
    ("animation", "image/gif", "a.gif", "image", "animation"),
    ("animation", "video/mp4", "a.mp4", "video", "animation"),
])
def test_portable_media(kind, mime, name, max_kind, tg_kind):
    media = {"mime_type": mime, "file_name": name}
    assert max_upload_kind(kind, media) == max_kind
    assert telegram_upload_kind(kind, media) == tg_kind
    assert delivery_text({"kind": kind, "text": "Teacher", "media": media}).startswith("Teacher\n[")


def test_revision_and_recipient_guard(tmp_path):
    spool = EventSpool(tmp_path / "spool.db", "bot")
    try:
        actions = ["open:1", "open:2", "back", "refresh"]
        rev, state = panel_revision({}, 0, {"id": 1}, actions)
        panel = {"revision": rev, "navigation_state": state, "actions": actions, "role": "teacher", "recipient": 1}
        spool.save_panel("42", panel)
        spool.select_conversation("42", 1)
        assert recipient_ready(spool, "42", [{"id": 1}, {"id": 2}])
        assert callback_action(rev + ":open:2", panel) == "open:2"
        assert callback_action(rev + ":open:99", panel) is None
        assert panel_revision(panel, 0, {"id": 1}, actions)[0] == rev
        new_rev, _ = panel_revision(panel, 0, {"id": 2}, actions)
        assert new_rev != rev
        spool.select_conversation("42", 2)
        assert not recipient_ready(spool, "42", [{"id": 1}, {"id": 2}])
        assert callback_action(rev + ":open:2", {**panel, "revision": new_rev}) is None
    finally:
        spool.close()


def test_panel_keeps_recipient_and_latest_history():
    chat = {"id": 1, "name": "Ученик", "total": 12,
            "messages": [{"name": "Вы", "preview": "😀" * 400} for _ in range(11)] +
                        [{"name": "Ученик", "preview": "Последнее сообщение"}]}
    text = teacher_panel_text(chat, [], 0, 1)
    assert text.startswith("🔸 Получатель: Ученик")
    assert text.endswith("Последнее сообщение")
    assert len(text.encode("utf-16-le")) <= 7800


@pytest.mark.parametrize("text,page", [("/menu", 0), ("Menu", 0), ("меню", 0), ("/menu 2", 1), ("/start", 0), ("hello", None)])
def test_shared_menu_commands(text, page):
    from connectors.common.commands import menu_page
    assert menu_page(text) == page


def test_unavailable_special_attachment_is_marked():
    assert "файл недоступен" in delivery_text({"kind": "sticker", "text": "Teacher"})
