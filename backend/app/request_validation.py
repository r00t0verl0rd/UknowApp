"""Проверки входных данных HTTP API."""

import re
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException


def _invalid(field: str, message: str) -> None:
    raise HTTPException(
        status_code=422,
        detail=[{"type": "value_error", "loc": ["body", field], "msg": message, "input": None}],
    )


def _object(payload: Any) -> dict:
    if not isinstance(payload, Mapping):
        _invalid("body", "Input should be a valid dictionary")
    return dict(payload)


def _string(data: dict, field: str, *, required: bool = False, minimum: int = 0, maximum: int | None = None) -> None:
    value = data.get(field)
    if value is None:
        if required:
            _invalid(field, "Field required")
        return
    if not isinstance(value, str):
        _invalid(field, "Input should be a valid string")
    if len(value) < minimum:
        _invalid(field, f"String should have at least {minimum} character(s)")
    if maximum is not None and len(value) > maximum:
        _invalid(field, f"String should have at most {maximum} character(s)")


def _integer(data: dict, field: str, *, required: bool = False, minimum: int | None = None) -> None:
    value = data.get(field)
    if value is None:
        if required:
            _invalid(field, "Field required")
        return
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(field, "Input should be a valid integer")
    if minimum is not None and value < minimum:
        _invalid(field, f"Input should be greater than or equal to {minimum}")


def login_payload(payload: Any) -> dict:
    data = _object(payload)
    _string(data, "username", required=True, minimum=1, maximum=160)
    _string(data, "password", required=True, minimum=1, maximum=256)
    return {key: data[key] for key in ("username", "password")}


def _messenger_account(data):
    if "messenger_account" not in data:
        return
    account = _object(data["messenger_account"])
    platform = account.get("platform")
    ident = account.get("external_user_id")
    if not isinstance(platform, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", platform):
        _invalid("messenger_account", "Invalid platform")
    if ident is not None and (not isinstance(ident, str) or not ident.strip() or len(ident) > 255):
        _invalid("messenger_account", "Invalid external user ID")
    data["messenger_account"] = {"platform": platform, "external_user_id": ident}


def user_create_payload(payload: Any) -> dict:
    data = _object(payload)
    _string(data, "full_name", required=True, minimum=2, maximum=160)
    _string(data, "additional_info", maximum=500)
    if data.get("role") not in {"teacher", "student"}:
        _invalid("role", "Input should be 'teacher' or 'student'")
    _string(data, "web_username", minimum=2, maximum=160)
    _messenger_account(data)
    fields = ("full_name", "additional_info", "role", "web_username", "messenger_account")
    return {key: data[key] for key in fields if key in data}


def user_update_payload(payload: Any) -> dict:
    data = _object(payload)
    _string(data, "full_name", minimum=2, maximum=160)
    _string(data, "additional_info", maximum=500)
    if data.get("role") is not None and data["role"] not in {"teacher", "student"}:
        _invalid("role", "Input should be 'teacher' or 'student'")
    _string(data, "web_username", minimum=2, maximum=160)
    _messenger_account(data)
    fields = ("full_name", "additional_info", "role", "web_username", "messenger_account")
    return {key: data[key] for key in fields if key in data}


def assignment_payload(payload: Any) -> dict:
    data = _object(payload)
    _integer(data, "teacher_id", required=True)
    _integer(data, "student_id", required=True)
    return {"teacher_id": data["teacher_id"], "student_id": data["student_id"]}


def personal_conversation_payload(payload: Any) -> dict:
    data = _object(payload)
    _integer(data, "user_id", required=True, minimum=1)
    return {"user_id": data["user_id"]}


def message_payload(payload: Any) -> dict:
    data = _object(payload)
    _string(data, "text", required=True, minimum=1, maximum=3900)
    _string(data, "client_message_id", maximum=64)
    result = {"text": data["text"]}
    if data.get("client_message_id"):
        result["client_message_id"] = data["client_message_id"]
    return result
