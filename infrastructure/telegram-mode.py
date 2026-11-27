#!/usr/bin/env python3
"""Switch the single-VPS Telegram API mode without exposing credentials."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
MODES = ("cloud", "local")
SECRET_KEYS = ("BOTS_NATS_CORE_PASSWORD", "BOTS_NATS_TELEGRAM_PASSWORD", "BOTS_MEDIA_SECRET_TELEGRAM")
MANAGED = ("TELEGRAM_API_MODE", "COMPOSE_PROFILES", "BOTS_PLATFORMS", *SECRET_KEYS)
LOCAL_URL = "http://telegram-bot-api:8081"
API_HELPER = r'''
import json, os, sys, time, urllib.error, urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(NoRedirect())
mode = os.environ["TELEGRAM_API_MODE"]
base = "https://api.telegram.org" if mode == "cloud" else os.environ["TELEGRAM_API_URL"].rstrip("/")
token = os.environ["TELEGRAM_BOT_TOKEN"]
method = sys.argv[1]
deadline = time.monotonic() + (660 if method == "getMe" else 0)
while True:
    try:
        req = urllib.request.Request(base + "/bot" + token + "/" + method, data=b"", method="POST")
        with opener.open(req, timeout=15) as response:
            result = json.load(response)
        if result.get("ok") and (method != "logOut" or result.get("result") is True):
            print("Telegram " + method + ": OK", flush=True)
            break
        code = result.get("error_code", 0)
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception:
        code = 0
    # После выхода Telegram может блокировать вход до 10 минут.
    # Не повторяем выход, если результат запроса неизвестен.
    if method != "getMe" or code not in (0, 401, 429, 500, 502, 503, 504) or time.monotonic() >= deadline:
        sys.exit("Telegram " + method + " failed (code " + str(code) + "). No token printed.")
    time.sleep(5)
'''


def compose(*args, envfile=ENV, capture=False):
    cmd = ["docker", "compose", "--env-file", str(envfile), "-f", str(ROOT / "docker-compose.yml"), *args]
    result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        # Не выводим конфигурацию с паролями и токенами.
        raise RuntimeError("Docker Compose command failed: " + args[0])
    return result.stdout if capture else ""


def resolved_env():
    return dict(line.split("=", 1) for line in compose("config", "--environment", capture=True).splitlines()
                if "=" in line)


def values_for(mode, current):
    profiles = [p.strip() for p in current.get("COMPOSE_PROFILES", "").split(",") if p.strip()]
    profiles = list(dict.fromkeys(p for p in profiles if p != "telegram"))
    for p in ("gateway", "bots"):
        if p not in profiles:
            profiles.append(p)
    if mode == "local":
        profiles.append("telegram")
    platforms = list(dict.fromkeys(p.strip() for p in current.get("BOTS_PLATFORMS", "").split(",") if p.strip()))
    if "telegram" not in platforms:
        platforms.append("telegram")
    values = {"TELEGRAM_API_MODE": mode, "COMPOSE_PROFILES": ",".join(profiles),
              "BOTS_PLATFORMS": ",".join(platforms)}
    for key in SECRET_KEYS:
        if not current.get(key):
            values[key] = secrets.token_hex(32)
        elif len(current[key]) < 32:
            raise RuntimeError(key + " is too short; fix it before switching.")
    return values


def rewrite_env(original, values):
    lines = []
    seen = set()
    for line in original.splitlines(keepends=True):
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key not in values:
            lines.append(line)
        elif key not in seen:
            lines.append(key + "=" + values[key] + "\n")
            seen.add(key)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.extend(k + "=" + v + "\n" for k, v in values.items() if k not in seen)
    return "".join(lines)


def protected_file(content, prefix):
    fd, path = tempfile.mkstemp(prefix=prefix, dir=ROOT)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return Path(path)


def running(service):
    return compose("--profile", "gateway", "--profile", "bots", "--profile", "telegram",
                   "ps", "--status", "running", "-q", service, capture=True).strip()


def inspect_env(container):
    result = subprocess.run(["docker", "inspect", "--format", "{{json .Config.Env}}", container],
                            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return dict(v.split("=", 1) for v in json.loads(result.stdout) if "=" in v)


def api(method):
    compose("--profile", "bots", "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "tg_bot", "-c", API_HELPER, method)


def switch(mode):
    if not ENV.is_file() or ENV.is_symlink():
        raise RuntimeError("Create a regular .env file first.")
    overrides = [k for k in (*MANAGED, "TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
                             "TELEGRAM_API_URL", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME")
                 if k in os.environ]
    if overrides:
        raise RuntimeError("Unset shell overrides first: " + ", ".join(overrides))
    current = resolved_env()
    if current.get("COMPOSE_FILE"):
        raise RuntimeError("Custom/remote Compose setups require the documented manual procedure.")
    old_mode = current.get("TELEGRAM_API_MODE") or "cloud"
    if old_mode not in MODES:
        raise RuntimeError("Invalid existing TELEGRAM_API_MODE.")
    if not current.get("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env first.")
    if (mode == "local" or old_mode == "local") and (
        current.get("TELEGRAM_API_URL") or LOCAL_URL).rstrip("/") != LOCAL_URL:
        raise RuntimeError("Remote Bot API is not supported by this single-VPS command.")
    if mode == "local" and (not current.get("TELEGRAM_API_ID", "").isdigit() or
                              not current.get("TELEGRAM_API_HASH")):
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first (my.telegram.org/apps).")
    bot = running("tg_bot")
    if bot:
        actual = inspect_env(bot)
        if actual.get("TELEGRAM_API_MODE", "cloud") != old_mode or actual.get("TELEGRAM_BOT_TOKEN") != current["TELEGRAM_BOT_TOKEN"]:
            raise RuntimeError("Running tg_bot differs from .env; reconcile its mode/token before switching.")
    old_local = running("telegram-bot-api")
    if old_local and old_mode != "local":
        raise RuntimeError("Local API is running although .env says cloud; reconcile before switching.")
    # Проверяем новые настройки до остановки бота.
    original = ENV.read_text()
    values = values_for(mode, current)
    candidate = protected_file(rewrite_env(original, values), ".env.telegram-candidate-")
    try:
        compose("config", "--quiet", envfile=candidate)
        compose("build", "core", "web_panel", "tg_bot", envfile=candidate)
        if mode == "local":
            compose("pull", "telegram-bot-api", envfile=candidate)
        backup = protected_file(original, ".env.telegram-backup-")
        print("Protected .env backup: " + backup.name, flush=True)
        if old_mode != mode and old_mode == "local" and not old_local:
            raise RuntimeError("Old local API is not running; start it before migrating to cloud.")
        if old_mode != mode:
            print("Stopping polling before API migration...", flush=True)
            compose("--profile", "bots", "stop", "tg_bot")
            # Явный профиль нужен и для веб-установки без ботов.
            api("logOut")
        # Сохраняем режим после успешного выхода; повторный запуск безопасен.
        os.replace(candidate, ENV)
        if mode == "cloud":
            compose("--profile", "telegram", "stop", "telegram-bot-api")
        else:
            compose("up", "-d", "--no-deps", "telegram-bot-api")
        if "postgres" in values["COMPOSE_PROFILES"].split(","):
            compose("up", "-d", "--wait", "--wait-timeout", "180", "postgres")
        compose("up", "-d", "nats", "core", "web_panel")
        if old_mode != mode or not bot:
            print("Checking target Telegram API (cloud may have a 10-minute cooldown)...", flush=True)
            api("getMe")
        compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "tg_bot")
        compose("exec", "-T", "core", "python", "-c",
                'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/api/ready", timeout=10).status)')
        compose("ps")
        print("Telegram mode: " + mode + " | attachment limit: " + ("20" if mode == "cloud" else "888") + " MiB")
    finally:
        candidate.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=MODES + ("status",))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("VPS administrator only: run via SSH as root or with sudo.")
    if args.mode == "status":
        current = resolved_env()
        print("Configured Telegram mode: " + (current.get("TELEGRAM_API_MODE") or "cloud"))
        compose("--profile", "gateway", "--profile", "bots", "--profile", "telegram", "ps")
        return
    with (ROOT / ".env.telegram-switch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Telegram mode switch is running.") from None
        switch(args.mode)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        # Не выводим аргументы и настройки с секретами.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise SystemExit("Switch stopped: " + message +
                         "\nInspect .env mode and docker compose ps; fix the issue before rerunning.") from None
