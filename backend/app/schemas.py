from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    role: Literal["teacher", "student"]
    telegram_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    telegram_id: int | None = None
    active: bool | None = None


class AssignmentCreate(BaseModel):
    teacher_id: int
    student_id: int
