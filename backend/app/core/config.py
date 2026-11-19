import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip()
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com").strip()

# Generate a stable key pair on first startup when no explicit VAPID pair is supplied.
# The private key lives in the persistent data volume and is never stored in the repository.
if not (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY):
    import base64
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    _vapid_dir = ROOT_DIR / "data"
    _vapid_dir.mkdir(parents=True, exist_ok=True)
    _vapid_path = _vapid_dir / "vapid_private.pem"
    if _vapid_path.exists():
        _vapid_key = serialization.load_pem_private_key(_vapid_path.read_bytes(), password=None)
    else:
        _vapid_key = ec.generate_private_key(ec.SECP256R1())
        _vapid_pem = _vapid_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _vapid_path.write_bytes(_vapid_pem)
        os.chmod(_vapid_path, 0o600)
    _vapid_public = _vapid_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(_vapid_public).rstrip(b"=").decode("ascii")
    VAPID_PRIVATE_KEY = str(_vapid_path)

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
