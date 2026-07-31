from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field

# --- Tenant ---


class TenantRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    description: str | None = None
    logo_file_id: uuid.UUID | None = None
    onboarding_completed: bool = False
    # i18n (F0): tenant-default interface locale; None → deployment default.
    default_locale: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


# --- GF10: Company Profile ---


COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]


class CompanyProfileUpdate(BaseModel):
    industry: str | None = Field(default=None, max_length=255)
    company_size: str | None = Field(
        default=None, pattern="^(1-10|11-50|51-200|201-500|501-1000|1001-5000|5000\\+)$"
    )
    website: str | None = Field(default=None, max_length=500)
    description: str | None = None
    # Interface locale from AVAILABLE_LOCALES (validated in the service);
    # written by the onboarding "Language" step and company settings.
    default_locale: str | None = Field(default=None, max_length=10)


class CompanyProfileRead(TenantRead):
    logo_url: str | None = None
    activity_fields: list[ActivityFieldRead] = []


class LogoUrlIn(BaseModel):
    """HRP-53: import a company logo from a public URL."""

    url: AnyHttpUrl


class ActivityFieldRead(BaseModel):
    id: uuid.UUID
    activity_field_id: uuid.UUID
    title: str | None = None
    tenant_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityFieldAdd(BaseModel):
    activity_field_id: uuid.UUID


# --- Division ---


class DivisionCreate(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    deputy_manager_id: uuid.UUID | None = None


class DivisionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    deputy_manager_id: uuid.UUID | None = None


class PendingRoleDowngrade(BaseModel):
    employee_id: uuid.UUID
    user_id: uuid.UUID
    current_role: str
    user_name: str | None = None
    # HRP-196: per ticket §5 the previous manager is auto-downgraded to
    # Employee on losing their last division. `downgraded=True` lets the
    # client show a one-shot toast ("N managers downgraded to employee")
    # without a confirm dialog.
    downgraded: bool = False


class RoleUpgrade(BaseModel):
    # HRP-196: emitted when an Employee is just installed as Manager or
    # Deputy Manager so the client can show a "promoted to Manager" toast
    # without forcing the operator to navigate elsewhere to verify.
    employee_id: uuid.UUID
    user_id: uuid.UUID
    new_role: str
    user_name: str | None = None


class DivisionRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    manager_id: uuid.UUID | None = None
    manager_name: str | None = None
    deputy_manager_id: uuid.UUID | None = None
    deputy_manager_name: str | None = None
    tenant_id: uuid.UUID
    created_at: datetime
    pending_role_downgrade: list[PendingRoleDowngrade] = Field(default_factory=list)
    role_upgrades: list[RoleUpgrade] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DivisionTree(DivisionRead):
    children: list[DivisionTree] = []


class DivisionScopeItem(BaseModel):
    """Compact division reference returned by ``GET /api/divisions/scope``."""

    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


# --- GF7: Specialization-Division ---


class SpecializationDivisionCreate(BaseModel):
    specialization_id: uuid.UUID


class SpecializationDivisionRead(BaseModel):
    id: uuid.UUID
    division_id: uuid.UUID
    specialization_id: uuid.UUID
    specialization_title: str | None = None
    tenant_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# --- H3: Onboarding ---


class OnboardingStatusRead(BaseModel):
    needs_onboarding: bool
    onboarding_completed: bool
    employee_count: int
    division_count: int
    has_invitations: bool
