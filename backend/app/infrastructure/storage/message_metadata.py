"""JSON representation shared by both message tables."""

import json

from sqlalchemy import JSON, cast, func


def encode_message_metadata(metadata: dict) -> str:
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


def metadata_value(db, column, key):
    """Read a string field from JSON stored in a text column."""
    if db.get_bind().dialect.name == "postgresql":
        return cast(column, JSON)[key].as_string()
    return func.json_extract(column, "$." + key)
