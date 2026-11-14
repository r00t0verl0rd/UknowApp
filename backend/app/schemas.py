from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    role: Literal["teacher", "student"]
    telegram_id: Optional[int] = None
    web_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    role: Optional[Literal["teacher", "student"]] = None
    telegram_id: Optional[int] = None
    active: Optional[bool] = None
    web_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class AssignmentCreate(BaseModel):
    teacher_id: int
    student_id: int


class PanelMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
