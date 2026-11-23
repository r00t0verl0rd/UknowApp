"""JSON representation shared by both message tables."""

import json


def encode_message_metadata(metadata: dict) -> str:
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
