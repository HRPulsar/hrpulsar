import asyncio
import contextlib
import ipaddress
import logging
import socket
import uuid
from io import BytesIO
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.core.errors import AppError
from app.modules.auth.models import Invitation, Role, User, user_roles
from app.modules.company.models import (
    CompanyActivityField,
    Division,
    SpecializationDivision,
    Tenant,
)
from app.modules.company.schemas import (
    CompanyProfileUpdate,
    DivisionCreate,
    DivisionTree,
    DivisionUpdate,
    OnboardingStatusRead,
    SpecializationDivisionCreate,
    TenantUpdate,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee

logger = logging.getLogger(__name__)

# Role codes that already imply manager-level (or higher) access — never
# auto-upgraded, never auto-considered for downgrade.
_NON_DOWNGRADABLE_ROLES = frozenset({"admin", "hr", "platform_admin"})
_MANAGER_OR_HIGHER = frozenset({"manager", "admin", "hr", "platform_admin"})

# --- Tenant ---


async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    return tenant


async def update_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, data: TenantUpdate
) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant


# --- Division ---


def _employee_name(emp) -> str | None:
    if emp and emp.user:
        return f"{emp.user.first_name} {emp.user.last_name}"
    return None


def _division_to_read(div: Division) -> dict:
    return {
        "id": div.id,
        "name": div.name,
        "description": div.description,
        "parent_id": div.parent_id,
        "manager_id": div.manager_id,
        "manager_name": _employee_name(div.manager if div.manager_id else None),
        "deputy_manager_id": div.deputy_manager_id,
        "deputy_manager_name": _employee_name(
            div.deputy_manager if div.deputy_manager_id else None
        ),
        "tenant_id": div.tenant_id,
        "created_at": div.created_at,
        "pending_role_downgrade": [],
        "role_upgrades": [],
    }


def _dedupe_upgrades(upgrades: list[dict]) -> list[dict]:
    """Collapse upgrade entries by employee_id.

    The same person can sit as both Manager and Deputy Manager of one
    division — we only want one "promoted to Manager" toast on the
    client even though `_sync_role_on_assign` is called twice.
    """
    seen: set[uuid.UUID] = set()
    out: list[dict] = []
    for entry in upgrades:
        eid = entry.get("employee_id")
        if eid is None or eid in seen:
            continue
        seen.add(eid)
        out.append(entry)
    return out


async def _validate_manager(
    db: AsyncSession, tenant_id: uuid.UUID, manager_id: uuid.UUID | None
) -> None:
    if manager_id:
        emp = await db.get(Employee, manager_id)
        if not emp or emp.tenant_id != tenant_id:
            raise AppError("division_invalid_manager", status.HTTP_400_BAD_REQUEST)


async def _user_role_codes(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == user_id)
    )
    return {code for (code,) in rows.all()}


async def _employee_user_id(
    db: AsyncSession, employee_id: uuid.UUID | None
) -> uuid.UUID | None:
    if employee_id is None:
        return None
    emp = await db.get(Employee, employee_id)
    return emp.user_id if emp else None


async def _sync_role_on_assign(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID | None
) -> dict | None:
    """Add `manager` role to the assigned user if they only have `employee`.

    Skips users who already have manager-or-higher role. Caller is responsible
    for committing the surrounding transaction.

    HRP-196: returns a dict describing the upgrade when one actually
    happens (so callers can surface a toast / log entry) — `None`
    otherwise. Skipping the upgrade (admin already, no matching role,
    etc.) returns `None`.
    """
    if employee_id is None:
        return None
    user_id = await _employee_user_id(db, employee_id)
    if user_id is None:
        return None
    codes = await _user_role_codes(db, user_id)
    if codes & _MANAGER_OR_HIGHER:
        return None
    role_row = await db.execute(
        select(Role).where(Role.code == "manager", Role.is_system == True)  # noqa: E712
    )
    manager_role = role_row.scalar_one_or_none()
    if manager_role is None:
        return None
    await db.execute(
        user_roles.insert().values(user_id=user_id, role_id=manager_role.id)
    )
    user = await db.get(User, user_id)
    logger.info(
        "division.role_auto_upgraded",
        extra={
            "event": "division.role_auto_upgraded",
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "employee_id": str(employee_id),
            "role": "manager",
        },
    )
    return {
        "employee_id": employee_id,
        "user_id": user_id,
        "new_role": "manager",
        "user_name": (f"{user.first_name} {user.last_name}".strip() if user else None),
    }


async def _still_manages_any_division(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> bool:
    query = select(func.count(Division.id)).where(
        Division.tenant_id == tenant_id,
        or_(
            Division.manager_id == employee_id,
            Division.deputy_manager_id == employee_id,
        ),
    )
    count = (await db.execute(query)).scalar() or 0
    return count > 0


async def _compute_pending_downgrades(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    removed_employee_ids: list[uuid.UUID],
) -> list[dict]:
    """Build the `pending_role_downgrade` list for employees just unassigned.

    Caller must `db.flush()` first so the post-update division row is visible
    in this transaction — that flushed state is the source of truth, no need
    to exclude the division being edited (that would miss the case where the
    same employee remains as deputy of the very same division).

    Each entry returned to the API only if the user has the `manager` role
    *and* no Division still references them as manager/deputy_manager.
    Admin / hr / platform_admin never appear here.
    """
    pending: list[dict] = []
    seen: set[uuid.UUID] = set()
    for emp_id in removed_employee_ids:
        if emp_id is None or emp_id in seen:
            continue
        seen.add(emp_id)
        if await _still_manages_any_division(db, tenant_id, emp_id):
            continue
        emp = await db.get(Employee, emp_id)
        if emp is None:
            continue
        codes = await _user_role_codes(db, emp.user_id)
        if codes & _NON_DOWNGRADABLE_ROLES:
            continue
        if "manager" not in codes:
            continue
        user = await db.get(User, emp.user_id)
        pending.append(
            {
                "employee_id": emp.id,
                "user_id": emp.user_id,
                "current_role": "manager",
                "user_name": (
                    f"{user.first_name} {user.last_name}".strip() if user else None
                ),
            }
        )
    return pending


async def _auto_downgrade_to_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    entries: list[dict],
) -> list[dict]:
    """HRP-196: strip the `manager` role from each entry in-place.

    The spec ("set role=Employeer") is unambiguous — no
    confirmation dialog. Caller has already validated each entry via
    `_compute_pending_downgrades`, which guarantees the user holds
    `manager` and no longer manages any division of the tenant. Admin /
    hr / platform_admin are filtered upstream and never reach this fn.
    """
    if not entries:
        return entries
    manager_role_row = await db.execute(
        select(Role).where(
            Role.code == "manager",
            Role.is_system == True,  # noqa: E712
        )
    )
    manager_role = manager_role_row.scalar_one_or_none()
    if manager_role is None:
        # No `manager` role exists in the role table — nothing to remove.
        return entries
    for entry in entries:
        await db.execute(
            user_roles.delete().where(
                user_roles.c.user_id == entry["user_id"],
                user_roles.c.role_id == manager_role.id,
            )
        )
        entry["downgraded"] = True
        logger.info(
            "division.role_auto_downgraded",
            extra={
                "event": "division.role_auto_downgraded",
                "tenant_id": str(tenant_id),
                "user_id": str(entry["user_id"]),
                "employee_id": str(entry["employee_id"]),
                "from_role": "manager",
                "to_role": "employee",
            },
        )
    return entries


async def create_division(
    db: AsyncSession, tenant_id: uuid.UUID, data: DivisionCreate
) -> dict:
    if data.parent_id:
        parent = await db.get(Division, data.parent_id)
        if not parent or parent.tenant_id != tenant_id:
            raise AppError("invalid_parent_division", status.HTTP_400_BAD_REQUEST)

    await _validate_manager(db, tenant_id, data.manager_id)
    await _validate_manager(db, tenant_id, data.deputy_manager_id)

    division = Division(tenant_id=tenant_id, **data.model_dump())
    db.add(division)
    await db.flush()

    upgrades: list[dict] = []
    for emp_id in (data.manager_id, data.deputy_manager_id):
        result = await _sync_role_on_assign(db, tenant_id, emp_id)
        if result is not None:
            upgrades.append(result)

    await db.commit()
    await db.refresh(division)
    payload = _division_to_read(division)
    payload["pending_role_downgrade"] = []
    payload["role_upgrades"] = _dedupe_upgrades(upgrades)
    return payload


async def get_division(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> dict:
    division = await _get_division(db, tenant_id, division_id)
    return _division_to_read(division)


async def _get_division(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> Division:
    division = await db.get(Division, division_id)
    if not division or division.tenant_id != tenant_id:
        raise AppError("division_not_found", status.HTTP_404_NOT_FOUND)
    return division


async def get_division_tree(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[DivisionTree]:
    result = await db.execute(select(Division).where(Division.tenant_id == tenant_id))
    divisions = result.scalars().all()

    # Build tree in memory from flat list (avoid lazy-loading children relationship)
    nodes: dict[uuid.UUID, DivisionTree] = {}
    for div in divisions:
        d = _division_to_read(div)
        nodes[div.id] = DivisionTree(
            **d,
            children=[],
        )

    roots: list[DivisionTree] = []
    for node in nodes.values():
        if node.parent_id and node.parent_id in nodes:
            nodes[node.parent_id].children.append(node)
        else:
            roots.append(node)

    return roots


async def update_division(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    division_id: uuid.UUID,
    data: DivisionUpdate,
) -> dict:
    division = await _get_division(db, tenant_id, division_id)

    updates = data.model_dump(exclude_unset=True)
    if "parent_id" in updates and updates["parent_id"]:
        if updates["parent_id"] == division_id:
            raise AppError("division_own_parent", status.HTTP_400_BAD_REQUEST)
        parent = await db.get(Division, updates["parent_id"])
        if not parent or parent.tenant_id != tenant_id:
            raise AppError("invalid_parent_division", status.HTTP_400_BAD_REQUEST)

    if "manager_id" in updates:
        await _validate_manager(db, tenant_id, updates["manager_id"])
    if "deputy_manager_id" in updates:
        await _validate_manager(db, tenant_id, updates["deputy_manager_id"])

    removed_employee_ids: list[uuid.UUID] = []
    if (
        "manager_id" in updates
        and division.manager_id != updates["manager_id"]
        and division.manager_id is not None
    ):
        removed_employee_ids.append(division.manager_id)
    if (
        "deputy_manager_id" in updates
        and division.deputy_manager_id != updates["deputy_manager_id"]
        and division.deputy_manager_id is not None
    ):
        removed_employee_ids.append(division.deputy_manager_id)

    for field, value in updates.items():
        setattr(division, field, value)
    await db.flush()

    upgrades: list[dict] = []
    if "manager_id" in updates:
        result = await _sync_role_on_assign(db, tenant_id, updates["manager_id"])
        if result is not None:
            upgrades.append(result)
    if "deputy_manager_id" in updates:
        result = await _sync_role_on_assign(db, tenant_id, updates["deputy_manager_id"])
        if result is not None:
            upgrades.append(result)

    pending = await _compute_pending_downgrades(db, tenant_id, removed_employee_ids)
    # HRP-196: spec mandates the previous manager is set to Employee when
    # they lose their last division — no confirm dialog. We still return
    # the list so the UI can show a one-shot "Role downgraded" toast.
    pending = await _auto_downgrade_to_employee(db, tenant_id, pending)

    await db.commit()
    await db.refresh(division)
    payload = _division_to_read(division)
    payload["pending_role_downgrade"] = pending
    # HRP-196: surface the auto-upgrade so the UI can confirm to the
    # operator that the selected user actually became a manager.
    payload["role_upgrades"] = _dedupe_upgrades(upgrades)
    return payload


async def delete_division(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> None:
    division = await _get_division(db, tenant_id, division_id)
    await db.delete(division)
    await db.commit()


# ---------------------------------------------------------------------------
# GF7: Specialization-Division Mapping
# ---------------------------------------------------------------------------


def _spec_div_to_read(sd: SpecializationDivision) -> dict:
    return {
        "id": sd.id,
        "division_id": sd.division_id,
        "specialization_id": sd.specialization_id,
        "specialization_title": sd.specialization.title if sd.specialization else None,
        "tenant_id": sd.tenant_id,
        "created_at": sd.created_at,
    }


async def list_division_specializations(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> list[dict]:
    await _get_division(db, tenant_id, division_id)
    result = await db.execute(
        select(SpecializationDivision).where(
            SpecializationDivision.division_id == division_id,
        )
    )
    return [_spec_div_to_read(sd) for sd in result.scalars().all()]


async def add_division_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    division_id: uuid.UUID,
    data: SpecializationDivisionCreate,
) -> dict:
    await _get_division(db, tenant_id, division_id)

    # Validate specialization exists and belongs to tenant (or is origin)
    spec = await db.get(DictionaryItem, data.specialization_id)
    if not spec or spec.type != "specialization":
        raise AppError("invalid_specialization", status.HTTP_400_BAD_REQUEST)
    if spec.tenant_id is not None and spec.tenant_id != tenant_id:
        raise AppError("invalid_specialization", status.HTTP_400_BAD_REQUEST)

    # Check for duplicate
    existing = await db.execute(
        select(SpecializationDivision).where(
            SpecializationDivision.division_id == division_id,
            SpecializationDivision.specialization_id == data.specialization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise AppError(
            "specialization_already_assigned_to_division", status.HTTP_409_CONFLICT
        )

    sd = SpecializationDivision(
        tenant_id=tenant_id,
        division_id=division_id,
        specialization_id=data.specialization_id,
    )
    db.add(sd)
    await db.commit()
    await db.refresh(sd)
    return _spec_div_to_read(sd)


async def remove_division_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    division_id: uuid.UUID,
    specialization_id: uuid.UUID,
) -> dict:
    await _get_division(db, tenant_id, division_id)
    result = await db.execute(
        select(SpecializationDivision).where(
            SpecializationDivision.division_id == division_id,
            SpecializationDivision.specialization_id == specialization_id,
        )
    )
    sd = result.scalar_one_or_none()
    if not sd or sd.tenant_id != tenant_id:
        raise AppError(
            "specialization_division_mapping_not_found", status.HTTP_404_NOT_FOUND
        )
    data = _spec_div_to_read(sd)
    await db.delete(sd)
    await db.commit()
    return data


# ---------------------------------------------------------------------------
# GF10: Company Profile & Activity Fields
# ---------------------------------------------------------------------------


def _activity_field_to_read(af: CompanyActivityField) -> dict:
    return {
        "id": af.id,
        "activity_field_id": af.activity_field_id,
        "title": af.activity_field.title if af.activity_field else None,
        "tenant_id": af.tenant_id,
        "created_at": af.created_at,
    }


async def _get_logo_url(db: AsyncSession, tenant: Tenant) -> str | None:
    """Get presigned URL for tenant logo if set."""
    if not tenant.logo_file_id:
        return None
    from app.core.s3 import get_presigned_url
    from app.modules.storage.models import File

    f = await db.get(File, tenant.logo_file_id)
    if not f:
        return None
    return get_presigned_url(f.path)


async def get_company_profile(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    tenant = await get_tenant(db, tenant_id)
    result = await db.execute(
        select(CompanyActivityField).where(
            CompanyActivityField.tenant_id == tenant_id,
        )
    )
    fields = [_activity_field_to_read(af) for af in result.scalars().all()]
    logo_url = await _get_logo_url(db, tenant)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "is_active": tenant.is_active,
        "industry": tenant.industry,
        "company_size": tenant.company_size,
        "website": tenant.website,
        "description": tenant.description,
        "logo_file_id": tenant.logo_file_id,
        "logo_url": logo_url,
        "default_locale": tenant.default_locale,
        "created_at": tenant.created_at,
        "activity_fields": fields,
    }


async def update_company_profile(
    db: AsyncSession, tenant_id: uuid.UUID, data: CompanyProfileUpdate
) -> dict:
    tenant = await get_tenant(db, tenant_id)
    payload = data.model_dump(exclude_unset=True)
    if payload.get("default_locale") is not None:
        from app.config import settings

        payload["default_locale"] = payload["default_locale"].strip().lower()
        if payload["default_locale"] not in settings.available_locales_list:
            raise AppError("unsupported_default_locale", status.HTTP_400_BAD_REQUEST)
    for field, value in payload.items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return await get_company_profile(db, tenant_id)


# SVG is deliberately excluded: it can carry <script>/on* handlers and S3/R2
# presigned URLs serve it inline (image/svg+xml) from our origin → stored XSS.
# Raster formats only until uploads are served from a sandboxed origin or
# SVGs are sanitised. Matches the generic storage allowlist.
ALLOWED_LOGO_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_LOGO_BYTES = 5 * 1024 * 1024


async def upload_logo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    file: UploadFile,
) -> dict:
    """Upload company logo. Replaces existing logo if set.

    Browsers occasionally label images ``application/octet-stream`` (notably
    files dragged out of macOS Preview); trusting the header alone lost the
    correct ``Content-Type`` in S3 and broke the eventual ``<img>`` render
    (HRP-53). We now sniff magic bytes and persist the detected MIME.
    """
    from app.modules.storage import service as storage_service
    from app.modules.storage.mime import detect_image_mime

    data = await file.read()
    if len(data) > MAX_LOGO_BYTES:
        raise AppError("logo_too_large", status.HTTP_400_BAD_REQUEST)
    if not data:
        raise AppError("logo_empty_file", status.HTTP_400_BAD_REQUEST)

    sniffed = detect_image_mime(data)
    effective = sniffed or file.content_type
    if effective not in ALLOWED_LOGO_TYPES:
        raise AppError(
            "logo_invalid_file_type",
            status.HTTP_400_BAD_REQUEST,
            allowed=", ".join(sorted(ALLOWED_LOGO_TYPES)),
        )

    tenant = await get_tenant(db, tenant_id)

    # Delete old logo if exists
    if tenant.logo_file_id:
        with contextlib.suppress(HTTPException):
            await storage_service.delete(db, tenant_id, tenant.logo_file_id)
        tenant.logo_file_id = None

    # Rewind so storage_service.upload re-reads the same bytes we sniffed.
    await file.seek(0)
    file_data = await storage_service.upload(
        db,
        tenant_id,
        user_id,
        file,
        entity_type="logo",
        content_type_override=effective,
    )

    tenant.logo_file_id = file_data["id"]
    await db.commit()
    await db.refresh(tenant)

    return await get_company_profile(db, tenant_id)


MAX_LOGO_REDIRECTS = 3


async def _assert_safe_url(url: str) -> tuple[str, str]:
    """Reject anything that isn't a public http(s) URL.

    Returns the parsed (scheme, hostname) for callers that want to log it.
    Runs the DNS lookup on the default executor so we don't stall the event
    loop on slow resolvers (HRP-53 review note).
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError("logo_url_only_public_http", status.HTTP_400_BAD_REQUEST)

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise AppError(
            "logo_url_cannot_resolve_host",
            status.HTTP_400_BAD_REQUEST,
            host=parsed.hostname,
        ) from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise AppError("logo_url_not_public_host", status.HTTP_400_BAD_REQUEST)
    return parsed.scheme, parsed.hostname


async def upload_logo_from_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    url: str,
) -> dict:
    """Fetch an image from a public URL and store it as the company logo.

    Manual redirect loop with per-hop host validation — the naive
    ``follow_redirects=True`` would let an attacker bounce admins from
    ``evil.example`` to ``169.254.169.254`` via a 3xx Location header
    (HRP-53 review fix).
    """
    current = url.strip()
    response: httpx.Response | None = None

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        for _ in range(MAX_LOGO_REDIRECTS + 1):
            await _assert_safe_url(current)
            try:
                response = await client.get(current)
            except httpx.HTTPError as exc:
                raise AppError(
                    "logo_url_download_failed",
                    status.HTTP_400_BAD_REQUEST,
                    error=str(exc),
                ) from exc
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise AppError(
                        "logo_url_redirect_without_location",
                        status.HTTP_400_BAD_REQUEST,
                    )
                current = urljoin(current, location)
                continue
            break
        else:
            raise AppError("logo_url_too_many_redirects", status.HTTP_400_BAD_REQUEST)

    assert response is not None  # loop body always assigns before break
    if response.is_error:
        raise AppError(
            "logo_url_download_http_error",
            status.HTTP_400_BAD_REQUEST,
            http_status=response.status_code,
        )

    body = response.content
    if not body:
        raise AppError("logo_url_downloaded_empty", status.HTTP_400_BAD_REQUEST)
    if len(body) > MAX_LOGO_BYTES:
        raise AppError("logo_too_large", status.HTTP_400_BAD_REQUEST)

    final_parsed = urlparse(current)
    filename = (final_parsed.path.rsplit("/", 1)[-1] or "logo")[:120]
    if "." not in filename:
        filename = f"{filename}.bin"

    upload = UploadFile(
        file=BytesIO(body),
        filename=filename,
        headers=Headers({"content-type": response.headers.get("content-type", "")}),
    )
    return await upload_logo(db, tenant_id, user_id, upload)


async def delete_logo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict:
    """Remove company logo."""
    from app.modules.storage import service as storage_service

    tenant = await get_tenant(db, tenant_id)
    if not tenant.logo_file_id:
        raise AppError("logo_not_set", status.HTTP_404_NOT_FOUND)

    with contextlib.suppress(HTTPException):
        await storage_service.delete(db, tenant_id, tenant.logo_file_id)

    tenant.logo_file_id = None
    await db.commit()
    await db.refresh(tenant)

    return await get_company_profile(db, tenant_id)


async def add_activity_field(
    db: AsyncSession, tenant_id: uuid.UUID, activity_field_id: uuid.UUID
) -> dict:
    # Validate activity field exists in dictionary
    item = await db.get(DictionaryItem, activity_field_id)
    if not item or item.type != "activity_field":
        raise AppError("invalid_activity_field", status.HTTP_400_BAD_REQUEST)
    if item.tenant_id is not None and item.tenant_id != tenant_id:
        raise AppError("invalid_activity_field", status.HTTP_400_BAD_REQUEST)

    # Check duplicate
    existing = await db.execute(
        select(CompanyActivityField).where(
            CompanyActivityField.tenant_id == tenant_id,
            CompanyActivityField.activity_field_id == activity_field_id,
        )
    )
    if existing.scalar_one_or_none():
        raise AppError("activity_field_already_assigned", status.HTTP_409_CONFLICT)

    af = CompanyActivityField(
        tenant_id=tenant_id,
        activity_field_id=activity_field_id,
    )
    db.add(af)
    await db.commit()
    await db.refresh(af)
    return _activity_field_to_read(af)


async def get_public_company_profile(db: AsyncSession, slug: str) -> dict | None:
    """GF10 Improve: Public company profile for SaaS."""
    result = await db.execute(
        select(Tenant).where(
            Tenant.slug == slug, Tenant.is_active == True  # noqa: E712
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return None

    # Get activity fields
    af_result = await db.execute(
        select(CompanyActivityField).where(
            CompanyActivityField.tenant_id == tenant.id,
        )
    )
    fields = [_activity_field_to_read(af) for af in af_result.scalars().all()]

    # Get division count
    div_count_result = await db.execute(
        select(func.count(Division.id)).where(Division.tenant_id == tenant.id)
    )
    division_count = div_count_result.scalar() or 0

    # Get employee count
    from app.modules.employee.models import Employee

    emp_count_result = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.tenant_id == tenant.id, Employee.status == "active"
        )
    )
    employee_count = emp_count_result.scalar() or 0

    logo_url = await _get_logo_url(db, tenant)
    return {
        "name": tenant.name,
        "slug": tenant.slug,
        "industry": tenant.industry,
        "company_size": tenant.company_size,
        "website": tenant.website,
        "description": tenant.description,
        "logo_url": logo_url,
        "activity_fields": fields,
        "division_count": division_count,
        "employee_count": employee_count,
    }


async def remove_activity_field(
    db: AsyncSession, tenant_id: uuid.UUID, activity_field_id: uuid.UUID
) -> dict:
    result = await db.execute(
        select(CompanyActivityField).where(
            CompanyActivityField.tenant_id == tenant_id,
            CompanyActivityField.activity_field_id == activity_field_id,
        )
    )
    af = result.scalar_one_or_none()
    if not af:
        raise AppError("activity_field_not_found", status.HTTP_404_NOT_FOUND)
    data = _activity_field_to_read(af)
    await db.delete(af)
    await db.commit()
    return data


# ---------------------------------------------------------------------------
# H3: Onboarding Wizard
# ---------------------------------------------------------------------------


async def get_onboarding_status(
    db: AsyncSession, tenant_id: uuid.UUID
) -> OnboardingStatusRead:
    tenant = await get_tenant(db, tenant_id)

    emp_count = (
        await db.execute(
            select(func.count(Employee.id)).where(Employee.tenant_id == tenant_id)
        )
    ).scalar() or 0

    div_count = (
        await db.execute(
            select(func.count(Division.id)).where(Division.tenant_id == tenant_id)
        )
    ).scalar() or 0

    inv_count = (
        await db.execute(
            select(func.count(Invitation.id)).where(
                Invitation.tenant_id == tenant_id,
                Invitation.status == "pending",
            )
        )
    ).scalar() or 0

    needs = not tenant.onboarding_completed and emp_count == 0

    return OnboardingStatusRead(
        needs_onboarding=needs,
        onboarding_completed=tenant.onboarding_completed,
        employee_count=emp_count,
        division_count=div_count,
        has_invitations=inv_count > 0,
    )


async def complete_onboarding(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    tenant.onboarding_completed = True
    await db.commit()
    await db.refresh(tenant)
    return tenant
