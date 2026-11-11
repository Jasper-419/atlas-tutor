from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator
import re


class Register(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("请输入有效邮箱")
        return value


class Login(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class Profile(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    preferences: dict[str, Any] | None = None


class DeleteAccount(BaseModel):
    password: str = Field(max_length=128)


class CreateCourse(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    background: str = Field(default="", max_length=4000)
    minutes_per_day: int = Field(default=30, ge=5, le=480)
    deadline: str | None = Field(default=None, max_length=40)
    level: str = Field(default="beginner", max_length=100)


class Replan(BaseModel):
    reason: str = Field(min_length=3, max_length=4000)


class Research(BaseModel):
    query: str = Field(min_length=3, max_length=4000)


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=120)


class SubmitAttempt(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=120)


class RateReview(BaseModel):
    rating: int = Field(ge=1, le=5)


class SourceText(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=12, max_length=400000)
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        if value:
            from urllib.parse import urlsplit

            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("仅支持不含凭据的 HTTP(S) URL")
        return value


class CreateMemory(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    category: str = Field(default="note", min_length=1, max_length=60)
    course_id: str | None = None
    facet: str | None = Field(default=None, min_length=1, max_length=80)


class EditMemory(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    expected_revision: int | None = Field(default=None, ge=1)


class EditNode(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, min_length=1, max_length=3000)
    objective: str | None = Field(default=None, min_length=1, max_length=3000)
    estimated_minutes: int | None = Field(default=None, ge=5, le=240)


class Edge(BaseModel):
    source: str
    target: str


class EditGraph(BaseModel):
    edges: list[Edge] = Field(max_length=500)
