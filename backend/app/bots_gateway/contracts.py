"""Provider-neutral version 1 wire protocol."""
import json
import re

STREAM = "UKNOW_BOTS_V1"
PREFIX = "uknow.v1"
PLATFORM_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MAX_FRAME = 256 * 1024


def platforms(value):
    result = tuple(dict.fromkeys(s.strip() for s in value.split(",") if s.strip()))
    if any(not PLATFORM_RE.fullmatch(p) for p in result):
        raise ValueError("invalid connector platform")
    return result


def encode(value):
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(data) > MAX_FRAME:
        raise ValueError("connector event too large")
    return data


def decode(data):
    if len(data) > MAX_FRAME:
        raise ValueError("connector event too large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise TypeError("invalid connector payload")
    return value


def identifier(value):
    if not isinstance(value, str) or not 0 < len(value) <= 255:
        raise ValueError("invalid external identifier")
    return value
