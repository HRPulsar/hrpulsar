"""Public-demo sandbox schemas (HRP-251 — D3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class DemoStartRequest(BaseModel):
    """Body of ``POST /api/demo/start``.

    The Turnstile token is optional at the schema layer — the service
    enforces it iff ``DEMO_TURNSTILE_SECRET`` is configured, so dev /
    self-hosted runs can omit it.
    """

    turnstile_token: str | None = Field(
        default=None,
        description="Cloudflare Turnstile token. Required when the server is "
        "configured with DEMO_TURNSTILE_SECRET.",
    )
    # Intl.DateTimeFormat().resolvedOptions().timeZone. Untrusted input on
    # a public endpoint that only ever lands in a Slack field, so it is
    # bounded to the IANA shape here rather than resolved against the tz
    # database — a zone name we don't know yet is still worth showing.
    timezone: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$",
        description="IANA time zone reported by the visitor's browser. "
        "Optional — the session is provisioned either way.",
    )


class DemoStartResponse(BaseModel):
    """Body of a successful ``POST /api/demo/start``.

    The refresh token is set as an httpOnly cookie by the router; only
    the access token leaks into the body for the SPA to send back as a
    Bearer header.
    """

    access_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
    expires_at: datetime
    redirect_url: str
    credits_granted: int
    # True when /demo/start handed back a still-live session associated
    # with the visitor's bearer token instead of provisioning a new
    # tenant. The SPA can use this to skip the "welcome / credits
    # granted" UI on resume.
    resumed: bool = False


class DemoSaveAccessRequest(BaseModel):
    """Body of ``POST /api/demo/save-access`` (HRP-256 — D8).

    A demo-session visitor captures their email so they can come back
    into a real account once a moderator approves the request. Same
    fields as the public /signup-request form but with email + name
    pre-filled by the SPA from the demo session.
    """

    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    company_name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, max_length=100)
    turnstile_token: str | None = None
    # Keep the sandbox data: on approve the demo tenant is converted into
    # the real workspace instead of provisioning an empty one.
    keep_demo_data: bool = False


class DemoSaveAccessResponse(BaseModel):
    signup_request_id: uuid.UUID
    email: EmailStr
    status: str


class DemoSwitchViewRequest(BaseModel):
    """Body of ``POST /api/demo/switch-view`` (HRP-612 wave 2).

    Swaps the demo session between the admin persona (the throw-away
    demo user) and the employee persona (a seeded employee with a
    personal dashboard story).
    """

    persona: Literal["admin", "employee"]


class DemoSwitchViewResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
    expires_at: datetime
    persona: Literal["admin", "employee"]
