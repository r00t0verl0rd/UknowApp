"""JSON representation shared by both message tables."""

import json

from sqlalchemy import JSON, Text, cast, func, literal
from sqlalchemy.dialects.postgresql import JSONB


def encode_message_metadata(metadata: dict) -> str:
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


def metadata_value(db, column, key):
    """Read a string field from JSON stored in a text column."""
    if db.get_bind().dialect.name == "postgresql":
        return cast(column, JSON)[key].as_string()
    return func.json_extract(column, "$." + key)


def metadata_with_field(db, column, key, value):
    """Update one top-level JSON field atomically, retaining concurrent read/delivery updates."""
    if db.get_bind().dialect.name == "postgresql":
        return cast(cast(column, JSONB).op("||")(cast(literal(encode_message_metadata({key: value}), type_=Text), JSONB)), Text)
    return func.json_set(column, "$." + key, func.json(json.dumps(value, ensure_ascii=False)))
