from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    role: Literal["teacher", "student"]
    telegram_id: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    role: Optional[Literal["teacher", "student"]] = None
    telegram_id: Optional[int] = None
    active: Optional[bool] = None


class AssignmentCreate(BaseModel):
    teacher_id: int
    student_id: int
