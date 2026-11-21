"""Persistent Web Push VAPID key management; invoked explicitly at startup/restore."""

import os
from pathlib import Path
from app.core.config import ROOT_DIR


_VAPID_PUBLIC_KEY_OVERRIDE = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_VAPID_PRIVATE_KEY_OVERRIDE = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_PUBLIC_KEY = ""
VAPID_PRIVATE_KEY = ""
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


