import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-now")
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes"}

_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url:
    DATABASE_URL = _database_url
else:
    (ROOT_DIR / "data").mkdir(parents=True, exist_ok=True)
    DATABASE_URL = "sqlite:///" + str(ROOT_DIR / "data" / "uknowapp.db")

import warnings

if ADMIN_PASSWORD in {"change-me-now", "replace-with-a-long-random-password"}:
    warnings.warn(
        "Using a placeholder admin password. Set a unique ADMIN_PASSWORD in .env before exposing UknowApp.",
        stacklevel=1,
    )
elif len(ADMIN_PASSWORD) < 16:
    warnings.warn(
        "ADMIN_PASSWORD is shorter than 16 characters. Use a long, unique random password.",
        stacklevel=1,
    )


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:22222,http://127.0.0.1:22222",
    ).split(",")
    if origin.strip()
]

if "*" in ALLOWED_ORIGINS:
    raise ValueError("ALLOWED_ORIGINS must list explicit trusted origins; wildcard origins are unsafe with cookie sessions.")
