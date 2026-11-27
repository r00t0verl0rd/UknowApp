import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("telegram_mode", Path(__file__).parents[1] / "telegram-mode.py")
switcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switcher)

def test_preserve_profiles_and_existing_secrets():
    current = {"COMPOSE_PROFILES": "postgres,gateway,bots,telegram",
               "BOTS_PLATFORMS": "telegram,other",
               **{key: "x" * 40 for key in switcher.SECRET_KEYS}}
    cloud = switcher.values_for("cloud", current)
    assert cloud["COMPOSE_PROFILES"] == "postgres,gateway,bots"
    assert cloud["BOTS_PLATFORMS"] == "telegram,other"
    assert not any(key in cloud for key in switcher.SECRET_KEYS)
    assert switcher.values_for("local", {**current, **cloud})["COMPOSE_PROFILES"] == "postgres,gateway,bots,telegram"

def test_missing_secrets_generated_and_env_preserved():
    values = switcher.values_for("cloud", {})
    assert len({values[key] for key in switcher.SECRET_KEYS}) == 3
    assert all(len(values[key]) == 64 for key in switcher.SECRET_KEYS)
    original = "# keep\nTELEGRAM_API_MODE=local\nTELEGRAM_API_MODE=cloud\nTELEGRAM_BOT_TOKEN=example\nDATABASE_URL=sqlite:///data.db"
    text = switcher.rewrite_env(original, values)
    assert text.count("TELEGRAM_API_MODE=") == 1
    assert "TELEGRAM_API_MODE=cloud\n" in text
    assert "TELEGRAM_BOT_TOKEN=example\n" in text
    assert "DATABASE_URL=sqlite:///data.db\n" in text
    assert text.startswith("# keep\n")

def test_non_admin_cannot_run(monkeypatch):
    monkeypatch.setattr(switcher.os, "geteuid", lambda: 1000)
    monkeypatch.setattr("sys.argv", ["telegram-mode.py", "cloud"])
    with pytest.raises(RuntimeError, match="VPS administrator only"):
        switcher.main()

@pytest.mark.parametrize("old,new", [("cloud", "local"), ("local", "cloud"), ("cloud", "cloud")])
def test_switch_order(old, new, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_API_MODE=" + old + "\n")
    monkeypatch.setattr(switcher, "ROOT", tmp_path)
    monkeypatch.setattr(switcher, "ENV", env)
    for key in (*switcher.MANAGED, "TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
                "TELEGRAM_API_URL", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME"):
        monkeypatch.delenv(key, raising=False)
    current = {"TELEGRAM_API_MODE": old, "TELEGRAM_BOT_TOKEN": "example", "TELEGRAM_API_ID": "123",
               "TELEGRAM_API_HASH": "example", "COMPOSE_PROFILES": "postgres,gateway,bots"}
    monkeypatch.setattr(switcher, "resolved_env", lambda: current)
    monkeypatch.setattr(switcher, "running", lambda service: "id" if service == "tg_bot" or old == "local" else "")
    monkeypatch.setattr(switcher, "inspect_env", lambda container: current)
    calls = []
    monkeypatch.setattr(switcher, "compose", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(switcher, "api", lambda method: calls.append(("api", method, env.read_text().splitlines()[0])))
    switcher.switch(new)
    assert "TELEGRAM_API_MODE=" + new in env.read_text()
    assert "postgres" in env.read_text()
    start = next(i for i, c in enumerate(calls) if c[0] == "up" and c[-1] == "tg_bot")
    if old != new:
        stop = calls.index(("--profile", "bots", "stop", "tg_bot"))
        logout = calls.index(("api", "logOut", "TELEGRAM_API_MODE=" + old))
        login = calls.index(("api", "getMe", "TELEGRAM_API_MODE=" + new))
        assert stop < logout < login < start
    else:
        assert not any(c[0] == "api" for c in calls)
    assert len(list(tmp_path.glob(".env.telegram-backup-*"))) == 1
