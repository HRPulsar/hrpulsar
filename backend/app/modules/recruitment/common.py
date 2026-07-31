"""Shared internal helpers for the recruitment services.

Canonical home of the cross-service primitives that used to live in
``service.py``: tenant-scoped entity fetchers, the best-effort event
publisher, role constants and the slug->uuid5 competence-id mapper.
Import from here inside the recruitment package instead of reaching
into a sibling service module.
"""

import logging
import uuid

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.recruitment.models import (
    Candidate,
    Vacancy,
    VacancyStage,
)

logger = logging.getLogger(__name__)

# Stable namespace for slug → uuid5 conversion. Fixed value so the same slug
# (e.g. "senior-python-skills") always maps to the same UUID across regenerations
# and across the canvas API. Do NOT change once data is in production.
COMPETENCE_NS = uuid.UUID("a4f1c2e3-0000-5000-8000-000000000001")


def normalize_competence_id(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert a competence id slug or UUID string to a stable UUID.

    AI-generated profiles emit kebab-case slugs as competence ids. We map
    each slug deterministically via uuid5 so the same competence stays
    addressable across regenerations and across question/score writes.
    """
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return uuid.UUID(s)
    except (ValueError, TypeError):
        return uuid.uuid5(COMPETENCE_NS, s)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _publish_event(event: str, payload: dict) -> None:
    """Best-effort event publish. Swallow errors so notifications never
    block business mutations — the same invariant the audit hook enforces.
    """
    try:
        from app.core.events import publish

        await publish(event, payload)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "recruitment event publish failed: %s", event
        )


async def _get_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> Vacancy:
    """Fetch vacancy with tenant check, raise 404 if not found."""
    result = await db.execute(
        select(Vacancy)
        .options(
            selectinload(Vacancy.candidates),
            selectinload(Vacancy.specializations),
            selectinload(Vacancy.grades),
        )
        .where(Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id)
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise AppError("vacancy_not_found", status.HTTP_404_NOT_FOUND)
    return vacancy


async def _get_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> Candidate:
    """Fetch candidate with tenant check, raise 404 if not found."""
    result = await db.execute(
        select(Candidate)
        .options(selectinload(Candidate.person), selectinload(Candidate.files))
        .where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    return candidate


async def _get_applicable_stages(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID | None = None
) -> list[VacancyStage]:
    """Return the funnel for a vacancy or tenant per FR-08.

    HRP-181 REDO: the override is **all-or-nothing** — a vacancy with any
    override rows replaces the tenant defaults wholesale (no merging).
    Without this guard ``_first_non_terminal_stage_id`` could land a new
    candidate on a tenant-default stage that the vacancy funnel doesn't
    even display.
    """
    base = select(VacancyStage).where(
        or_(
            VacancyStage.tenant_id.is_(None),
            VacancyStage.tenant_id == tenant_id,
        )
    )

    if vacancy_id:
        override_q = base.where(VacancyStage.vacancy_id == vacancy_id)
        overrides = list(
            (await db.execute(override_q.order_by(VacancyStage.sort_order)))
            .scalars()
            .all()
        )
        if overrides:
            return overrides

    defaults_q = base.where(VacancyStage.vacancy_id.is_(None))
    result = await db.execute(defaults_q.order_by(VacancyStage.sort_order))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Role helpers (R3a) — see RECRUITING_MODULE.md §13
# ---------------------------------------------------------------------------


_HM_ROLES = {"hiring_manager"}

_FULL_ROLES = {"admin", "recruiter", "hr", "hrd"}


def candidate_display_name(
    candidate: Candidate | None, *, fallback: str = "Unknown"
) -> str:
    """Display name for a candidate row (HRP-361).

    Prefers the denormalised ``Candidate.full_name`` — resume-sourced
    candidates have no Person row (``person_id`` optional since HRP-181
    REDO) — and falls back to the linked person's first/last name. Both
    ``candidate`` and ``candidate.person`` are ``lazy="selectin"``
    relationships, so callers holding a loaded row pay no extra query.
    """
    if candidate is None:
        return fallback
    name = (candidate.full_name or "").strip()
    if not name and candidate.person is not None:
        person = candidate.person
        name = (
            f"{(person.first_name or '').strip()} "
            f"{(person.last_name or '').strip()}"
        ).strip()
    return name or fallback


def resolve_user_role(user) -> str | None:
    """Pick the highest-privilege recruitment role code for ``user``.

    ``User`` has a many-to-many ``roles`` relation, not a scalar ``role``
    field. Read paths in the recruitment services accept a single role
    string; this
    helper centralises the "which role wins" decision so admin/recruiter/
    hrd/hr land on the full payload before hiring_manager is checked.
    Returns ``None`` for users with none of the recruitment roles — the
    role filter then strips the AI payload (defence in depth on top of
    ``require_role``).
    """

    codes = {r.code for r in (getattr(user, "roles", None) or [])}
    for full_role in ("admin", "recruiter", "hrd", "hr"):
        if full_role in codes:
            return full_role
    if "hiring_manager" in codes:
        return "hiring_manager"
    return None


def _stage_to_read_dict(stage: VacancyStage | None) -> dict | None:
    if stage is None:
        return None
    return {
        "id": stage.id,
        "tenant_id": stage.tenant_id,
        "vacancy_id": stage.vacancy_id,
        "name": stage.name,
        "code": stage.code,
        "sort_order": stage.sort_order,
        "is_terminal": stage.is_terminal,
        "stage_type": stage.stage_type,
        "color": stage.color,
    }
