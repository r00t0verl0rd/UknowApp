from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    role: Literal["teacher", "student"]
    web_username: Optional[str] = Field(default=None, min_length=2, max_length=160)
    telegram_id: Optional[int] = Field(default=None, gt=0)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    role: Optional[Literal["teacher", "student"]] = None
    web_username: Optional[str] = Field(default=None, min_length=2, max_length=160)
    telegram_id: Optional[int] = Field(default=None, gt=0)
    active: Optional[bool] = None


class AssignmentCreate(BaseModel):
    teacher_id: int
    student_id: int


class PanelMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=3900)


class PersonalConversationCreate(BaseModel):
    user_id: int = Field(gt=0)


class PersonalMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=3900)
