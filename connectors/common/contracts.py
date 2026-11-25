"""Provider-independent NATS envelope. Kept dependency-free."""
import json

STREAM = "UKNOW_BOTS_V1"
PREFIX = "uknow.v1"


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
