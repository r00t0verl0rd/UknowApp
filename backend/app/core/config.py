import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_BOT_ENABLED = os.getenv("TELEGRAM_BOT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip()
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "local").strip().lower()
if TELEGRAM_MODE not in {"local", "remote"}:
    raise ValueError("TELEGRAM_MODE must be local or remote")
TELEGRAM_GATEWAY_URL = os.getenv("TELEGRAM_GATEWAY_URL", "").strip()
TELEGRAM_GATEWAY_TOKEN = os.getenv("TELEGRAM_GATEWAY_TOKEN", "").strip()
_VAPID_PUBLIC_KEY_OVERRIDE = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_VAPID_PRIVATE_KEY_OVERRIDE = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_PUBLIC_KEY = ""
VAPID_PRIVATE_KEY = ""
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com").strip()


def reload_vapid_keys(data_dir: Path | None = None) -> None:
    """Load the persistent VAPID key after data restoration or at startup."""
    global VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY

    if _VAPID_PUBLIC_KEY_OVERRIDE and _VAPID_PRIVATE_KEY_OVERRIDE:
        VAPID_PUBLIC_KEY = _VAPID_PUBLIC_KEY_OVERRIDE
        VAPID_PRIVATE_KEY = _VAPID_PRIVATE_KEY_OVERRIDE
        return

    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    vapid_dir = data_dir or (ROOT_DIR / "data")
    vapid_dir.mkdir(parents=True, exist_ok=True)
    vapid_path = vapid_dir / "vapid_private.pem"
    if vapid_path.exists():
        vapid_key = serialization.load_pem_private_key(
            vapid_path.read_bytes(),
            password=None,
        )
    else:
        vapid_key = ec.generate_private_key(ec.SECP256R1())
        vapid_pem = vapid_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        vapid_path.write_bytes(vapid_pem)
    os.chmod(vapid_path, 0o600)

    vapid_public = vapid_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(vapid_public).rstrip(b"=").decode("ascii")
    VAPID_PRIVATE_KEY = str(vapid_path)


reload_vapid_keys()

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


TRUSTED_PROXY_IPS = {
    item.strip() for item in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1,172.31.255.2").split(",") if item.strip()
}

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
