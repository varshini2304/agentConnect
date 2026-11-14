"""Agent request and response schemas."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterestType = Literal["category", "keyword", "exclude"]


class AgentInterestInput(BaseModel):
    interest_type: InterestType
    value: str = Field(min_length=1, max_length=160)
    weight: float = Field(default=1.0, ge=0)

    @field_validator("value")
    @classmethod
    def clean_value(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("interest value cannot be blank")
        return value


class AgentCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80)
    company_name: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    is_active: bool = True
    interests: list[AgentInterestInput] = Field(default_factory=list, max_length=100)

    @field_validator("slug")
    @classmethod
    def clean_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("slug must contain lowercase letters, numbers, and hyphens")
        return value

    @field_validator("company_name", "role", "industry", "description")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class AgentPatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=160)
    role: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    is_active: bool | None = None
    interests: list[AgentInterestInput] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def reject_null_fields(self):
        for name in ("company_name", "role", "industry", "description", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @field_validator("company_name", "role", "industry", "description")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class AgentInterestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    interest_type: InterestType
    value: str
    weight: float


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    company_name: str
    role: str
    industry: str
    description: str
    is_active: bool
    created_at: datetime
    interests: list[AgentInterestRead]
