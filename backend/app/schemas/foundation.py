"""Validated company, account, team and cookie-session boundaries."""
from datetime import datetime
from typing import Annotated
import re
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.network import CompanyPolicy, StrictModel


class LoginInput(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        value = value.casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class RegisterInput(LoginInput):
    company_name: str = Field(min_length=1, max_length=160)
    company_slug: str | None = Field(default=None, min_length=1, max_length=90)
    name: str = Field(min_length=1, max_length=160)
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=12, max_length=1024)


class CompanyInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, min_length=1, max_length=90)


class CompanyUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slug: str | None = Field(default=None, min_length=1, max_length=90)
    network_opt_in: bool | None = None
    policy: CompanyPolicy | None = None

    @model_validator(mode="after")
    def no_null(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one company field to update")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Company fields cannot be null")
        return self


class SettingsInput(StrictModel):
    description: str = Field(default="", max_length=2000)
    website: str = Field(default="", max_length=2000)
    industry: str = Field(default="", max_length=120)
    onboarding_complete: bool = False

    @field_validator("website")
    @classmethod
    def website_url(cls, value):
        if value:
            url = urlsplit(value)
            if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
                raise ValueError("Use an HTTP or HTTPS website without credentials")
        return value


class SettingsRead(SettingsInput):
    pass


class CompanyRead(StrictModel):
    id: int
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime
    network_opt_in: bool
    policy: dict
    policy_version: int
    role: str
    role_id: int | None
    permissions: list[str]
    settings: SettingsRead


class UserRead(StrictModel):
    id: int
    email: str
    name: str
    status: str
    created_at: datetime
    last_login_at: datetime | None


class SessionRead(StrictModel):
    user: UserRead
    companies: list[CompanyRead]
    selected_company_id: int | None
    csrf_token: str


class WorkspaceInput(StrictModel):
    company_id: int = Field(gt=0)


class AccountInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)


class RoleInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    permissions: list[str] = Field(max_length=100)


class RoleRead(StrictModel):
    id: int
    name: str
    slug: str
    is_builtin: bool
    permissions: list[str]


class MemberInput(StrictModel):
    role_id: int = Field(gt=0)


class MemberRead(StrictModel):
    id: int
    user_id: int
    email: str
    name: str
    status: str
    role: str
    role_id: int | None
    created_at: datetime


class InvitationInput(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role_id: int = Field(gt=0)
    normalize_email = field_validator("email")(LoginInput.email_address.__func__)


class InvitationAccept(StrictModel):
    token: str = Field(min_length=20, max_length=256)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    password: Annotated[str | None, StringConstraints(strip_whitespace=False)] = Field(default=None, min_length=12, max_length=1024)


class InvitationRead(StrictModel):
    id: int
    email: str
    role_id: int
    role: str
    status: str
    expires_at: datetime
    delivery: str | None = None
    development_token: str | None = None


class CsrfRead(StrictModel):
    csrf_token: str


class PermissionRead(StrictModel):
    key: str
    description: str


class InvitationPreview(StrictModel):
    company_name: str
    email: str
    role: str
    expires_at: datetime


class OkRead(StrictModel):
    ok: bool
