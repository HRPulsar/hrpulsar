"""Pydantic schemas for the moderated signup flow."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

SIGNUP_ROLE_CHOICES = ("hr", "recruiter", "manager", "founder", "other")


class SignupRequestCreate(BaseModel):
    """Landing-form payload posted by an anonymous visitor."""

    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    company_name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, max_length=100)
    turnstile_token: str | None = None


class SignupRequestRead(BaseModel):
    """Confirmation surface returned to the caller — purposely thin so
    we don't leak the verify token or anything moderator-only.
    """

    id: uuid.UUID
    email: EmailStr
    status: str
    created_at: datetime


class SignupVerifyRequest(BaseModel):
    """Body of POST /api/signup-request/verify."""

    token: str


class SignupVerifyResponse(BaseModel):
    """Response after a verify-link click. ``already_verified`` is True
    when the visitor clicks the link a second time — the SPA shows the
    same waiting screen rather than treating it as an error.
    """

    id: uuid.UUID
    email: EmailStr
    status: str
    already_verified: bool = False
