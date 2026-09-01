from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# --- Auth ---


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    company_name: str = Field(max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class MagicLoginRequest(BaseModel):
    """Body of POST /api/auth/magic-login."""

    token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TenantInfo(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    roles: list[str] = []


class TenantSelectionRequired(BaseModel):
    requires_tenant_selection: bool = True
    tenants: list[TenantInfo]


class SelectTenantRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: uuid.UUID


class SwitchTenantRequest(BaseModel):
    tenant_id: uuid.UUID


class RegisterResponse(BaseModel):
    pending_verification: bool = True
    email: str
    # HRP-390: self-hosted installs without an email provider verify the
    # account at registration time so the flow doesn't dead-end waiting
    # for an email that can never arrive.
    auto_verified: bool = False


class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    user: UserRead
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# --- User ---


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool
    tenant_id: uuid.UUID
    created_at: datetime
    email_verified_at: datetime | None = None
    roles: list[str] = []
    # Populated by the enterprise RBAC extension (ee/rbac.py via the
    # app/core/rbac_hooks.py seam); always False in community builds.
    is_platform_admin: bool = False
    avatar_url: str | None = None
    deployment_mode: str = "onprem"
    # Demo session metadata — populated by /auth/me for is_demo tenants so the
    # SPA can render <DemoBanner/> + the countdown without an extra request.
    tenant_is_demo: bool = False
    tenant_expires_at: datetime | None = None
    # HRP-676: which "View as" persona the demo session is currently in.
    # The banner's switcher must not re-derive this from the email domain.
    # None outside a demo session.
    demo_persona: Literal["admin", "employee"] | None = None
    # i18n (F0): personal interface locale; None → tenant/deployment default.
    language: str | None = None
    # Tenant-default interface locale — populated by /auth/me (tenant row is
    # already loaded there) so the SPA resolves the locale without an extra
    # company-profile request.
    tenant_default_locale: str | None = None
    # HRP-637: the tenant's grade-visibility switch, carried here for the
    # same reason as the locale above — the tenant row is already loaded,
    # and the SPA has to know whether the positions catalogue will arrive
    # with its grade columns. Inferring that from the rows on the current
    # page guesses wrong on any page whose rows happen to have no pair.
    tenant_directory_show_grades: bool = False

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """Self-update payload for PUT /auth/me. Strict allowlist — any extra field is rejected."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    # Interface locale from AVAILABLE_LOCALES; explicit null clears the
    # personal choice (falls back to tenant/deployment default).
    language: str | None = Field(default=None, max_length=10)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# --- Role ---


class RoleCreate(BaseModel):
    name: str = Field(max_length=100)
    code: str = Field(max_length=50)
    description: str | None = Field(default=None, max_length=500)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RoleRead(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    description: str | None
    is_system: bool
    tenant_id: uuid.UUID | None
    permissions: list[str] = []
    # HRP-634: how many users of the tenant hold this role. Only the list
    # endpoint counts — single-role responses answer ``null`` rather than a
    # confident 0 they never computed.
    user_count: int | None = None

    model_config = {"from_attributes": True}


# --- Invitations (GF3) ---


class InvitationCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role_code: str = Field(default="employee", max_length=50)
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None


class InvitationBulkCreate(BaseModel):
    invitations: list[InvitationCreate] = Field(min_length=1, max_length=100)


class InvitationUpdate(BaseModel):
    """Edit pending invitation. All fields optional; field-level RBAC enforced in service."""

    model_config = ConfigDict(extra="forbid")

    role_code: str | None = Field(default=None, min_length=1, max_length=50)
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None


class InvitationEmailUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role_code: str
    invited_by: uuid.UUID
    inviter_name: str | None = None
    division_id: uuid.UUID | None
    division_name: str | None = None
    position_id: uuid.UUID | None = None
    position_title: str | None = None
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationBulkFailure(BaseModel):
    """One address the bulk create refused, and why."""

    email: str
    error_code: str


class InvitationBulkResult(BaseModel):
    """Multi-status answer of ``POST /invitations/bulk`` (HRP-593).

    The endpoint used to answer with a bare list of what it managed to
    create: an address refused as a duplicate and one refused because the
    role sits above the inviter both simply vanished from the response, so
    no caller could tell them apart — or notice at all.

    ``error_code`` carries the ``AppError`` code rather than a message; the
    client translates it, the same way it does for a single create.
    """

    created: list[InvitationRead]
    failed: list[InvitationBulkFailure]


class InvitationList(BaseModel):
    items: list[InvitationRead]
    total: int


class InvitationPreview(BaseModel):
    """Token-scoped public view of a pending invitation (HRP-435).

    Deliberately narrow — only what the accept form needs to introduce itself
    and pre-fill its fields. Holding the token is the authorisation, so no
    tenant, role or inviter detail is exposed.
    """

    email: str
    name: str


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
