"""Vacancy lifecycle: CRUD, spec/grade links, competences (HRP-136),
attachments (HRP-135) and funnel stages (tenant defaults + per-vacancy
override, HRP-181 REDO Stage 2).

Split out of ``service.py`` (project-review #7); ``service.py`` keeps
delegating attribute access here, so ``service.create_vacancy`` still
resolves - including any billing/audit wrapper installed on this module.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.position.models import Position
from app.modules.recruitment.common import (
    _get_applicable_stages,
    _get_vacancy,
    _publish_event,
    _stage_to_read_dict,
)
from app.modules.recruitment.models import (
    AssessmentInvite,
    CandidateVacancy,
    Vacancy,
    VacancyAttachment,
    VacancyCompetence,
    VacancyProfile,
    VacancyStage,
)
from app.modules.recruitment.schemas import (
    VacancyCloseData,
    VacancyCompetencesUpdate,
    VacancyCreate,
    VacancyStageCreate,
    VacancyStagesReplace,
    VacancyStageUpdate,
    VacancyUpdate,
)

logger = logging.getLogger(__name__)


def _vacancy_to_read(
    vacancy: Vacancy,
    *,
    has_profile: bool = False,
    active_invites_count: int = 0,
    position_title: str | None = None,
    owner_name: str | None = None,
    hiring_manager_name: str | None = None,
    division_name: str | None = None,
) -> dict:
    """Convert Vacancy ORM to API response dict with joined fields."""
    specializations = [
        {"id": item.id, "title": getattr(item, "title", None)}
        for item in (vacancy.specializations or [])
    ]
    grades = [
        {"id": item.id, "title": getattr(item, "title", None)}
        for item in (vacancy.grades or [])
    ]
    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "description": vacancy.description,
        "position_id": vacancy.position_id,
        "position_title": position_title,
        "specializations": specializations,
        "grades": grades,
        "specialization_id": vacancy.specialization_id,
        "grade_id": vacancy.grade_id,
        "division_id": vacancy.division_id,
        "status": vacancy.status,
        "owner_id": vacancy.owner_id,
        "hiring_manager_id": vacancy.hiring_manager_id,
        "tasks_main": vacancy.tasks_main,
        "tasks_additional": vacancy.tasks_additional,
        "tasks_kpi": vacancy.tasks_kpi,
        "employment_type": vacancy.employment_type,
        "location": vacancy.location,
        "salary_min": (
            float(vacancy.salary_min) if vacancy.salary_min is not None else None
        ),
        "salary_max": (
            float(vacancy.salary_max) if vacancy.salary_max is not None else None
        ),
        "salary_currency": vacancy.salary_currency,
        "language": vacancy.language,
        "requirements": vacancy.requirements,
        "responsibilities": vacancy.responsibilities,
        "conditions": vacancy.conditions,
        "close_resolution": vacancy.close_resolution,
        "close_reason": vacancy.close_reason,
        "closed_at": vacancy.closed_at,
        "archived_at": vacancy.archived_at,
        "archived_by": vacancy.archived_by,
        "version": vacancy.version,
        "assessment_scale_id": vacancy.assessment_scale_id,
        "assessment_scale_snapshot": vacancy.assessment_scale_snapshot,
        "created_at": vacancy.created_at,
        "updated_at": vacancy.updated_at,
        # Joined fields
        "owner_name": owner_name,
        "hiring_manager_name": hiring_manager_name,
        "specialization_title": None,
        "grade_title": None,
        "division_name": division_name,
        "candidates_count": len(vacancy.candidates) if vacancy.candidates else 0,
        "has_profile": has_profile,
        "active_invites_count": active_invites_count,
    }


def vacancy_etag(vacancy: Vacancy | dict) -> str:
    """Weak ETag derived from ``vacancies.version``.

    Weak (``W/``) — bytes-identical comparison is not meaningful here
    because the joined fields drift between responses; what matters is
    the row's monotonic write counter for ``If-Match`` checks.
    """
    version = vacancy.version if isinstance(vacancy, Vacancy) else vacancy["version"]
    return f'W/"{version}"'


# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------


async def _load_position_for_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
):
    """Load a tenant Position by id or raise 422 if not found.

    Used by both create/update flows to validate the FK before assigning
    it (the DB SET NULL on delete would silently swallow a stale UUID).
    """

    pos = (
        await db.execute(
            select(Position).where(
                Position.id == position_id, Position.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if pos is None:
        raise AppError(
            "position_id_wrong_tenant",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return pos


async def _validate_division_for_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> None:
    """HRP-338: reject a division UUID from another tenant (or a stale one)
    — mirrors the position_id check above."""
    exists = (
        await db.execute(
            select(Division.id).where(
                Division.id == division_id, Division.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise AppError(
            "division_id_wrong_tenant",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


def _position_spec_grade_pool(position) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Return the spec/grade IDs the vacancy form is allowed to pick from
    when the user has chosen ``position``.

    Mirrors the (specialization_id, grade_id) on the Position row. Returns
    empty sets when neither side is set — caller treats that as "no pool"
    and rejects any non-empty selection.
    """
    specs = {position.specialization_id} if position.specialization_id else set()
    grades = {position.grade_id} if position.grade_id else set()
    return specs, grades


def _validate_spec_grade_against_position(
    position,
    specialization_ids: list[uuid.UUID] | None,
    grade_ids: list[uuid.UUID] | None,
) -> None:
    """HRP-180: each spec/grade ID must come from the Position's pool."""
    allowed_specs, allowed_grades = _position_spec_grade_pool(position)
    if specialization_ids:
        for spec_id in specialization_ids:
            if spec_id not in allowed_specs:
                raise AppError(
                    "specialization_ids_not_in_position",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
    if grade_ids:
        for grade_id in grade_ids:
            if grade_id not in allowed_grades:
                raise AppError(
                    "grade_ids_not_in_position",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )


async def _set_vacancy_spec_grade_links(
    db: AsyncSession,
    vacancy: Vacancy,
    specialization_ids: list[uuid.UUID] | None,
    grade_ids: list[uuid.UUID] | None,
) -> None:
    """Replace junction rows for the vacancy's specializations / grades.

    ``None`` means "do not touch" — the caller did not supply the field.
    An empty list clears the selection.

    Writes go directly against the junction Tables so we don't trigger
    SQLAlchemy's eager-load of the existing relationship collection
    (which would crash inside a sync getter when the collection is not
    yet loaded — see HRP-180).
    """
    from sqlalchemy import delete, insert

    from app.modules.recruitment.models import (
        vacancy_grades_table,
        vacancy_specializations_table,
    )

    if specialization_ids is not None:
        await db.execute(
            delete(vacancy_specializations_table).where(
                vacancy_specializations_table.c.vacancy_id == vacancy.id
            )
        )
        unique = list(dict.fromkeys(specialization_ids))
        if unique:
            await db.execute(
                insert(vacancy_specializations_table),
                [
                    {"vacancy_id": vacancy.id, "specialization_id": spec_id}
                    for spec_id in unique
                ],
            )
    if grade_ids is not None:
        await db.execute(
            delete(vacancy_grades_table).where(
                vacancy_grades_table.c.vacancy_id == vacancy.id
            )
        )
        unique = list(dict.fromkeys(grade_ids))
        if unique:
            await db.execute(
                insert(vacancy_grades_table),
                [
                    {"vacancy_id": vacancy.id, "grade_id": grade_id}
                    for grade_id in unique
                ],
            )


def _eligible_hiring_manager_query(tenant_id: uuid.UUID):
    """Active users of the tenant — the single SQL definition of
    hiring-manager eligibility, shared by the picker and the validators.

    HRP-441: eligibility used to be the admin tier (HRP-360), which left
    the actual hiring managers — heads of department, team leads, anyone
    holding the ``hiring_manager``/``hr``/``recruiter`` role — out of the
    picker. Any active member of the tenant can now own a vacancy. The
    role still governs what they may *do*; it no longer governs whether
    a recruiter may name them on the requisition.

    Somebody who has left is filtered out through their Employee card.
    The card cannot be *required*, though: it is only created when an
    invitation named a division or a position, and the self-registered
    owner of the workspace never gets one — requiring it would drop the
    very users who were the only eligible managers before HRP-441 and
    would 422 every edit of the vacancies they already own.
    """
    from app.modules.employee.models import Employee

    terminated_staff = select(Employee.user_id).where(
        Employee.tenant_id == tenant_id,
        Employee.status != "active",
    )
    return (
        select(User.id, User.first_name, User.last_name, User.email)
        .where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.id.not_in(terminated_staff),
        )
        .distinct()
    )


async def _is_hiring_manager_eligible(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    row = (
        await db.execute(
            _eligible_hiring_manager_query(tenant_id).where(User.id == user_id).limit(1)
        )
    ).first()
    return row is not None


async def _validate_hiring_manager(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Reject a hiring manager who is not an active user of this tenant
    (HRP-360, widened past the admin tier in HRP-441)."""
    if not await _is_hiring_manager_eligible(db, tenant_id, user_id):
        raise AppError(
            "hiring_manager_invalid",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


async def list_hiring_manager_options(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict]:
    """Active tenant users eligible as vacancy hiring manager (HRP-441)."""
    rows = await db.execute(
        _eligible_hiring_manager_query(tenant_id).order_by(
            User.first_name, User.last_name
        )
    )
    return [
        {
            "id": row.id,
            "full_name": f"{row.first_name} {row.last_name}".strip(),
            "email": row.email,
        }
        for row in rows
    ]


async def create_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, data: VacancyCreate
) -> dict:
    """Create a new vacancy. Status defaults to 'draft'. owner_id = user_id.

    When ``library_refs`` is set (HRP-131), aggregate competences from
    the linked positions / specialization-grade pairs and pre-fill
    ``vacancy_competences`` with ``source="library"`` rows. The form
    can still extend the list later via PATCH /competences (HRP-136).
    """
    # ``mode="json"`` flattens nested UUID/datetime fields to strings so
    # the JSONB column accepts them without a custom encoder.
    payload = data.model_dump(mode="json")
    library_refs = payload.pop("library_refs", None)
    specialization_ids = payload.pop("specialization_ids", None)
    grade_ids = payload.pop("grade_ids", None)
    for col in (
        "specialization_id",
        "grade_id",
        "division_id",
        "position_id",
        "hiring_manager_id",
    ):
        val = payload.get(col)
        if isinstance(val, str):
            payload[col] = uuid.UUID(val)

    # HRP-360: default the hiring manager to the creating user, as long as
    # the picker can show them (HRP-441: any active tenant member). Explicit
    # values are validated uniformly, including self-assignment.
    if payload.get("hiring_manager_id") is None:
        if await _is_hiring_manager_eligible(db, tenant_id, user_id):
            payload["hiring_manager_id"] = user_id
    else:
        await _validate_hiring_manager(db, tenant_id, payload["hiring_manager_id"])

    # HRP-338: a caller-supplied division must belong to this tenant (the
    # HRP-131 autofill below copies from a tenant-validated Position, so it
    # needs no re-check).
    if payload.get("division_id") is not None:
        await _validate_division_for_vacancy(db, tenant_id, payload["division_id"])

    # HRP-180: validate Position FK and constrain spec/grade pool.
    position = None
    if payload.get("position_id"):
        position = await _load_position_for_vacancy(
            db, tenant_id, payload["position_id"]
        )
        _validate_spec_grade_against_position(
            position,
            [
                uuid.UUID(s) if isinstance(s, str) else s
                for s in (specialization_ids or [])
            ],
            [uuid.UUID(g) if isinstance(g, str) else g for g in (grade_ids or [])],
        )
        # HRP-131 autofill: copy division from Position when caller didn't.
        if payload.get("division_id") is None and position.division_id is not None:
            payload["division_id"] = position.division_id
    elif specialization_ids or grade_ids:
        # No position chosen → reject any non-empty multi-select. The
        # form disables the controls in this state, so a real caller
        # never hits this branch.
        raise AppError(
            "spec_grade_require_position",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    vacancy = Vacancy(
        tenant_id=tenant_id,
        owner_id=user_id,
        status="draft",
        library_refs=library_refs,
        **payload,
    )
    db.add(vacancy)
    await db.flush()

    # HRP-180: when Position is selected and the caller did not pick any
    # spec/grade, default to the Position's own pair so the page shows
    # something meaningful out of the box (HRP-131 autofill).
    if position is not None:
        if specialization_ids is None and position.specialization_id is not None:
            specialization_ids = [position.specialization_id]
        if grade_ids is None and position.grade_id is not None:
            grade_ids = [position.grade_id]

    normalised_specs = (
        [uuid.UUID(s) if isinstance(s, str) else s for s in (specialization_ids or [])]
        if specialization_ids is not None
        else None
    )
    normalised_grades = (
        [uuid.UUID(g) if isinstance(g, str) else g for g in (grade_ids or [])]
        if grade_ids is not None
        else None
    )
    await _set_vacancy_spec_grade_links(
        db, vacancy, normalised_specs, normalised_grades
    )

    await db.commit()
    await db.refresh(vacancy, ["candidates", "specializations", "grades"])

    if library_refs:
        await _seed_competences_from_library(db, tenant_id, vacancy.id, library_refs)
        await db.commit()
        # Refresh salary from a linked Position when caller didn't set it.
        await _backfill_salary_from_positions(db, tenant_id, vacancy, library_refs)
        await db.commit()
        await db.refresh(
            vacancy, ["candidates", "specializations", "grades", "updated_at"]
        )

    has_profile, invites = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=invites
    )


async def _backfill_salary_from_positions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy: Vacancy,
    library_refs: dict,
) -> None:
    """HRP-131: pull salary from the first attached Position with one set
    when the form hasn't supplied salary_min/max explicitly."""
    if vacancy.salary_min is not None or vacancy.salary_max is not None:
        return
    position_ids = library_refs.get("position_ids") or []
    if not position_ids:
        return

    rows = (
        (
            await db.execute(
                select(Position).where(
                    Position.id.in_(position_ids), Position.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    for pos in rows:
        salary_min = getattr(pos, "salary_min", None)
        salary_max = getattr(pos, "salary_max", None)
        currency = getattr(pos, "salary_currency", None)
        if salary_min is not None or salary_max is not None:
            vacancy.salary_min = salary_min
            vacancy.salary_max = salary_max
            if currency:
                vacancy.salary_currency = currency
            break


async def _seed_competences_from_library(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    library_refs: dict,
) -> None:
    """HRP-131: pre-fill vacancy_competences from the attached positions /
    specialization-grade pairs. Deduplicates by (competence_id) — the
    earliest match wins for ``skill_level_ids``.
    """

    aggregated: dict[uuid.UUID, set[uuid.UUID]] = {}

    # Positions → look up their specialization/grade GradeSpecialization
    position_ids = library_refs.get("position_ids") or []
    if position_ids:
        positions = (
            (
                await db.execute(
                    select(Position).where(
                        Position.id.in_(position_ids),
                        Position.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for pos in positions:
            if pos.specialization_id and pos.grade_id:
                await _collect_grade_spec_links(
                    db,
                    tenant_id,
                    pos.specialization_id,
                    [pos.grade_id],
                    aggregated,
                )

    # Specialization+grade pairs
    for pair in library_refs.get("specialization_grade_pairs") or []:
        spec_id = pair.get("specialization_id")
        grade_ids = pair.get("grade_ids") or []
        if spec_id and grade_ids:
            await _collect_grade_spec_links(
                db,
                tenant_id,
                uuid.UUID(spec_id) if isinstance(spec_id, str) else spec_id,
                [uuid.UUID(g) if isinstance(g, str) else g for g in grade_ids],
                aggregated,
            )

    for competence_id, skill_levels in aggregated.items():
        existing = (
            await db.execute(
                select(VacancyCompetence).where(
                    VacancyCompetence.vacancy_id == vacancy_id,
                    VacancyCompetence.competence_id == competence_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            VacancyCompetence(
                tenant_id=tenant_id,
                vacancy_id=vacancy_id,
                competence_id=competence_id,
                skill_level_ids=[str(sl) for sl in skill_levels],
                source="library",
            )
        )


async def _collect_grade_spec_links(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    grade_ids: list[uuid.UUID],
    aggregated: dict[uuid.UUID, set[uuid.UUID]],
) -> None:
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    gs_rows = (
        (
            await db.execute(
                select(GradeSpecialization).where(
                    GradeSpecialization.tenant_id == tenant_id,
                    GradeSpecialization.specialization_id == specialization_id,
                    GradeSpecialization.grade_id.in_(grade_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    if not gs_rows:
        return
    gs_ids = [g.id for g in gs_rows]
    links = (
        (
            await db.execute(
                select(GradeCompetenceLink).where(
                    GradeCompetenceLink.grade_specialization_id.in_(gs_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        aggregated.setdefault(link.competence_id, set()).add(link.skill_level_id)


# ---------------------------------------------------------------------------
# HRP-136: vacancy competences CRUD
# ---------------------------------------------------------------------------


async def list_vacancy_competences(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[dict]:
    await _get_vacancy(db, tenant_id, vacancy_id)
    rows = (
        (
            await db.execute(
                select(VacancyCompetence)
                .where(
                    VacancyCompetence.vacancy_id == vacancy_id,
                    VacancyCompetence.tenant_id == tenant_id,
                )
                .order_by(VacancyCompetence.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "vacancy_id": r.vacancy_id,
            "competence_id": r.competence_id,
            "skill_level_ids": list(r.skill_level_ids or []),
            "source": r.source,
        }
        for r in rows
    ]


async def set_vacancy_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyCompetencesUpdate,
) -> list[dict]:
    """Replace the full competence list for a vacancy (HRP-136).

    Caller sends the desired final set; rows not present are removed.
    Existing rows for the same ``competence_id`` are updated in place so
    audit and history stay attached.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    incoming: dict[uuid.UUID, dict] = {}
    for spec in data.competences:
        incoming[spec.competence_id] = {
            "skill_level_ids": [str(sl) for sl in spec.skill_level_ids],
            "source": spec.source,
        }

    existing = (
        (
            await db.execute(
                select(VacancyCompetence).where(
                    VacancyCompetence.vacancy_id == vacancy_id,
                    VacancyCompetence.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_id = {row.competence_id: row for row in existing}

    for competence_id, payload in incoming.items():
        row = existing_by_id.get(competence_id)
        if row is None:
            db.add(
                VacancyCompetence(
                    tenant_id=tenant_id,
                    vacancy_id=vacancy_id,
                    competence_id=competence_id,
                    skill_level_ids=payload["skill_level_ids"],
                    source=payload["source"],
                )
            )
        else:
            row.skill_level_ids = payload["skill_level_ids"]
            row.source = payload["source"]

    for competence_id, row in existing_by_id.items():
        if competence_id not in incoming:
            await db.delete(row)

    await db.commit()
    return await list_vacancy_competences(db, tenant_id, vacancy_id)


# ---------------------------------------------------------------------------
# HRP-135: vacancy attachments
# ---------------------------------------------------------------------------


# Sourced from config (review P2-34) so ceilings are deployment-tunable;
# kept as module constants for the service, ee/billing, and test references.
MAX_ATTACHMENT_BYTES = settings.recruitment_max_attachment_mb * 1024 * 1024

MAX_ATTACHMENTS_PER_VACANCY = 10

ALLOWED_ATTACHMENT_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/zip",
    "application/epub+zip",
    "text/html",
    "text/xml",
    "application/xml",
    "text/x-python",
    "application/x-python-code",
    "text/javascript",
    "application/javascript",
    "text/x-typescript",
    "application/typescript",
    "text/x-go",
    "text/x-java-source",
    "text/x-rust",
    "text/x-c",
    "text/x-csrc",
    "text/x-c++",
    "text/x-c++src",
    "text/x-csharp",
    "text/x-ruby",
    "text/x-shellscript",
    "application/x-sh",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "application/toml",
}


async def list_vacancy_attachments(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[dict]:
    await _get_vacancy(db, tenant_id, vacancy_id)
    rows = (
        (
            await db.execute(
                select(VacancyAttachment)
                .where(
                    VacancyAttachment.vacancy_id == vacancy_id,
                    VacancyAttachment.tenant_id == tenant_id,
                )
                .order_by(VacancyAttachment.uploaded_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "vacancy_id": r.vacancy_id,
            "file_id": r.file_id,
            "filename": r.filename,
            "mime_type": r.mime_type,
            "size_bytes": r.size_bytes,
            "uploaded_at": r.uploaded_at,
        }
        for r in rows
    ]


async def upload_vacancy_attachment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    file: UploadFile,
) -> dict:
    await _get_vacancy(db, tenant_id, vacancy_id)

    if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
        raise AppError(
            "vacancy_attachment_too_large",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            max_mb=MAX_ATTACHMENT_BYTES // (1024 * 1024),
        )
    if file.content_type and file.content_type not in ALLOWED_ATTACHMENT_MIMES:
        raise AppError(
            "vacancy_attachment_unsupported_type",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content_type=file.content_type,
        )

    existing_count = (
        await db.execute(
            select(func.count(VacancyAttachment.id)).where(
                VacancyAttachment.vacancy_id == vacancy_id,
                VacancyAttachment.tenant_id == tenant_id,
            )
        )
    ).scalar() or 0
    if existing_count >= MAX_ATTACHMENTS_PER_VACANCY:
        raise AppError(
            "vacancy_attachment_limit_reached",
            status.HTTP_409_CONFLICT,
            max_attachments=MAX_ATTACHMENTS_PER_VACANCY,
        )

    contents = await file.read()
    size = len(contents)
    if size > MAX_ATTACHMENT_BYTES:
        raise AppError(
            "vacancy_attachment_too_large",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            max_mb=MAX_ATTACHMENT_BYTES // (1024 * 1024),
        )

    file_id: uuid.UUID | None = None
    try:
        from io import BytesIO

        from starlette.datastructures import Headers

        from app.modules.storage.service import upload as storage_upload

        wrapped = UploadFile(
            file=BytesIO(contents),
            filename=file.filename or "attachment",
            headers=Headers(
                {"content-type": file.content_type or "application/octet-stream"}
            ),
        )
        file_row = await storage_upload(
            db,
            tenant_id,
            user_id,
            wrapped,
            entity_type="vacancy_attachment",
            entity_id=vacancy_id,
        )
        file_id = file_row["id"]
    except Exception:  # noqa: BLE001
        # Storage backend not configured in dev/tests — keep metadata only
        # so the API still records the attachment.
        file_id = None

    row = VacancyAttachment(
        tenant_id=tenant_id,
        vacancy_id=vacancy_id,
        file_id=file_id,
        filename=file.filename or "attachment",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        uploaded_by=user_id,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "vacancy_id": row.vacancy_id,
        "file_id": row.file_id,
        "filename": row.filename,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "uploaded_at": row.uploaded_at,
    }


async def delete_vacancy_attachment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> None:
    await _get_vacancy(db, tenant_id, vacancy_id)
    row = (
        await db.execute(
            select(VacancyAttachment).where(
                VacancyAttachment.id == attachment_id,
                VacancyAttachment.vacancy_id == vacancy_id,
                VacancyAttachment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("vacancy_attachment_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(row)
    await db.commit()


async def _vacancy_extras(db: AsyncSession, vacancy: Vacancy) -> tuple[bool, int]:
    """Return ``(has_profile, active_invites_count)`` for list/get reads."""
    has_profile = (
        await db.execute(
            select(func.count(VacancyProfile.id)).where(
                VacancyProfile.vacancy_id == vacancy.id,
                VacancyProfile.tenant_id == vacancy.tenant_id,
            )
        )
    ).scalar() or 0
    invites = (
        await db.execute(
            select(func.count(AssessmentInvite.id))
            .join(
                CandidateVacancy,
                AssessmentInvite.candidate_vacancy_id == CandidateVacancy.id,
            )
            .where(
                CandidateVacancy.vacancy_id == vacancy.id,
                AssessmentInvite.tenant_id == vacancy.tenant_id,
                AssessmentInvite.status == "pending",
            )
        )
    ).scalar() or 0
    return bool(has_profile), int(invites)


async def _joined_display_names(
    db: AsyncSession, tenant_id: uuid.UUID, vacancies: list[Vacancy]
) -> tuple[
    dict[uuid.UUID | None, str],
    dict[uuid.UUID | None, str],
    dict[uuid.UUID | None, str],
]:
    """Batch-resolve user, position and division display names (HRP-363).

    The first map covers both ``owner_id`` and ``hiring_manager_id``
    (HRP-360) — they point at the same ``users`` table.
    """
    user_ids = {v.owner_id for v in vacancies if v.owner_id is not None} | {
        v.hiring_manager_id for v in vacancies if v.hiring_manager_id is not None
    }
    position_ids = {v.position_id for v in vacancies if v.position_id is not None}
    division_ids = {v.division_id for v in vacancies if v.division_id is not None}

    # Keyed Optional so ``.get(vacancy.owner_id)`` type-checks on nullable FKs.
    users: dict[uuid.UUID | None, str] = {}
    if user_ids:
        rows = await db.execute(
            select(User.id, User.first_name, User.last_name).where(
                User.id.in_(user_ids), User.tenant_id == tenant_id
            )
        )
        users = {row.id: f"{row.first_name} {row.last_name}".strip() for row in rows}

    positions: dict[uuid.UUID | None, str] = {}
    if position_ids:
        rows = await db.execute(
            select(Position.id, Position.title).where(
                Position.id.in_(position_ids), Position.tenant_id == tenant_id
            )
        )
        positions = {row.id: row.title for row in rows}

    divisions: dict[uuid.UUID | None, str] = {}
    if division_ids:
        rows = await db.execute(
            select(Division.id, Division.name).where(
                Division.id.in_(division_ids), Division.tenant_id == tenant_id
            )
        )
        divisions = {row.id: row.name for row in rows}

    return users, positions, divisions


async def _vacancy_to_read_joined(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy: Vacancy,
    *,
    has_profile: bool,
    active_invites_count: int,
) -> dict:
    """Serialize one vacancy with all joined display names resolved —
    the single-row counterpart of the batched ``list_vacancies`` path,
    used by every endpoint that returns a full ``VacancyRead``."""
    users, positions, divisions = await _joined_display_names(db, tenant_id, [vacancy])
    return _vacancy_to_read(
        vacancy,
        has_profile=has_profile,
        active_invites_count=active_invites_count,
        position_title=positions.get(vacancy.position_id),
        owner_name=users.get(vacancy.owner_id),
        hiring_manager_name=users.get(vacancy.hiring_manager_id),
        division_name=divisions.get(vacancy.division_id),
    )


async def list_vacancies(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 25,
    status: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
) -> tuple[list[dict], int]:
    """List vacancies with optional status filter and search by title.

    ``archived_only`` returns only soft-deleted rows (`archived_at IS NOT
    NULL`). ``include_archived=False`` (default) hides them.
    """
    query = (
        select(Vacancy)
        .options(
            selectinload(Vacancy.candidates),
            selectinload(Vacancy.specializations),
            selectinload(Vacancy.grades),
        )
        .where(Vacancy.tenant_id == tenant_id)
    )
    count_query = select(func.count(Vacancy.id)).where(Vacancy.tenant_id == tenant_id)

    if archived_only:
        query = query.where(Vacancy.archived_at.is_not(None))
        count_query = count_query.where(Vacancy.archived_at.is_not(None))
    elif not include_archived:
        query = query.where(Vacancy.archived_at.is_(None))
        count_query = count_query.where(Vacancy.archived_at.is_(None))

    if status:
        query = query.where(Vacancy.status == status)
        count_query = count_query.where(Vacancy.status == status)
    if search:
        query = query.where(Vacancy.title.ilike(f"%{search}%"))
        count_query = count_query.where(Vacancy.title.ilike(f"%{search}%"))

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Vacancy.created_at.desc()).offset(skip).limit(limit)
    )
    vacancies = list(result.scalars().unique().all())
    users, positions, divisions = await _joined_display_names(db, tenant_id, vacancies)
    items: list[dict] = []
    for v in vacancies:
        has_profile, invites = await _vacancy_extras(db, v)
        items.append(
            _vacancy_to_read(
                v,
                has_profile=has_profile,
                active_invites_count=invites,
                owner_name=users.get(v.owner_id),
                hiring_manager_name=users.get(v.hiring_manager_id),
                position_title=positions.get(v.position_id),
                division_name=divisions.get(v.division_id),
            )
        )
    return items, total


async def get_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> dict:
    """Get single vacancy with stats."""
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)
    has_profile, invites = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=invites
    )


async def update_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyUpdate,
    *,
    if_match: str | None = None,
) -> dict:
    """Update vacancy fields (``exclude_unset``).

    When ``if_match`` is supplied, the request is rejected unless its
    weak ETag matches ``vacancies.version`` — 428 when missing, 412 when
    stale. Successful writes increment ``version`` so the next ETag is
    different.
    """
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    if vacancy.archived_at is not None:
        raise AppError(
            "vacancy_archived_readonly",
            status.HTTP_409_CONFLICT,
        )

    current_etag = vacancy_etag(vacancy)
    if if_match is not None and if_match != current_etag:
        raise AppError(
            "vacancy_etag_mismatch",
            status.HTTP_412_PRECONDITION_FAILED,
        )

    updates = data.model_dump(exclude_unset=True)
    # ``library_refs`` is a JSONB column — nested UUIDs must be strings
    # before asyncpg's ``json.dumps``. Other UUID fields stay native because
    # their columns are typed UUID.
    if "library_refs" in updates:
        updates["library_refs"] = (
            data.library_refs.model_dump(mode="json")
            if data.library_refs is not None
            else None
        )

    # HRP-180: pull the multi-select arrays out of the attribute updates
    # — they map to junction tables, not Vacancy columns. Validate against
    # the (new or existing) position pool before writing.
    spec_ids_provided = "specialization_ids" in updates
    grade_ids_provided = "grade_ids" in updates
    new_spec_ids = updates.pop("specialization_ids", None)
    new_grade_ids = updates.pop("grade_ids", None)

    position_obj = None
    target_position_id = updates.get("position_id", vacancy.position_id)
    if target_position_id is not None:
        position_obj = await _load_position_for_vacancy(
            db, tenant_id, target_position_id
        )

    if position_obj is not None and (spec_ids_provided or grade_ids_provided):
        _validate_spec_grade_against_position(
            position_obj,
            new_spec_ids if spec_ids_provided else None,
            new_grade_ids if grade_ids_provided else None,
        )
    elif position_obj is None and (
        (spec_ids_provided and new_spec_ids) or (grade_ids_provided and new_grade_ids)
    ):
        # Vacancy is not linked to a position — only an empty list is
        # acceptable (mirrors the form, which disables the multi-selects).
        raise AppError(
            "spec_grade_require_position",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # HRP-338: an explicit division change must stay inside the tenant.
    if (
        updates.get("division_id") is not None
        and updates["division_id"] != vacancy.division_id
    ):
        await _validate_division_for_vacancy(db, tenant_id, updates["division_id"])

    # HRP-360: an explicit hiring manager change must point at an active
    # admin-tier user of this tenant. Unchanged values skip the check so a
    # manager who has since lost the admin role does not block other edits.
    if (
        updates.get("hiring_manager_id") is not None
        and updates["hiring_manager_id"] != vacancy.hiring_manager_id
    ):
        await _validate_hiring_manager(db, tenant_id, updates["hiring_manager_id"])

    old_owner_id = vacancy.owner_id
    for field, value in updates.items():
        setattr(vacancy, field, value)

    if spec_ids_provided or grade_ids_provided:
        await _set_vacancy_spec_grade_links(
            db,
            vacancy,
            new_spec_ids if spec_ids_provided else None,
            new_grade_ids if grade_ids_provided else None,
        )

    vacancy.version = vacancy.version + 1
    await db.commit()
    await db.refresh(
        vacancy,
        attribute_names=["candidates", "specializations", "grades", "updated_at"],
    )

    new_owner_id = vacancy.owner_id
    if "owner_id" in updates and new_owner_id and new_owner_id != old_owner_id:
        await _publish_event(
            "recruitment.vacancy.assigned",
            {
                "tenant_id": str(tenant_id),
                "vacancy_id": str(vacancy.id),
                "vacancy_title": vacancy.title,
                "old_owner_id": str(old_owner_id) if old_owner_id else None,
                "new_owner_id": str(new_owner_id),
            },
        )

    has_profile, invites = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=invites
    )


async def archive_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> dict:
    """Soft-delete a vacancy and deactivate its pending reviewer invites."""
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)
    if vacancy.archived_at is not None:
        raise AppError("vacancy_already_archived", status.HTTP_409_CONFLICT)

    vacancy.archived_at = datetime.now(timezone.utc)
    vacancy.archived_by = user_id
    vacancy.version = vacancy.version + 1

    # Deactivate any pending evaluator invites tied to this vacancy so
    # external reviewers stop receiving canvas access.
    invites = (
        (
            await db.execute(
                select(AssessmentInvite)
                .join(
                    CandidateVacancy,
                    AssessmentInvite.candidate_vacancy_id == CandidateVacancy.id,
                )
                .where(
                    CandidateVacancy.vacancy_id == vacancy.id,
                    AssessmentInvite.tenant_id == tenant_id,
                    AssessmentInvite.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for invite in invites:
        invite.status = "inactive"

    await db.commit()
    await db.refresh(vacancy, attribute_names=["candidates", "updated_at"])
    has_profile, active = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=active
    )


async def restore_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> dict:
    """Restore a previously archived vacancy."""
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)
    if vacancy.archived_at is None:
        raise AppError("vacancy_not_archived", status.HTTP_409_CONFLICT)

    vacancy.archived_at = None
    vacancy.archived_by = None
    vacancy.version = vacancy.version + 1

    await db.commit()
    await db.refresh(vacancy, attribute_names=["candidates", "updated_at"])
    has_profile, invites = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=invites
    )


async def delete_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> None:
    """Hard-delete a draft vacancy.

    Allowed only when ``status='draft'`` AND no candidates AND no
    generated profile — same guard the UI uses to gate the "Delete
    permanently" menu item.
    """
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    if vacancy.status != "draft":
        raise AppError(
            "vacancy_delete_requires_draft",
            status.HTTP_409_CONFLICT,
        )
    if vacancy.candidates:
        raise AppError(
            "vacancy_delete_has_candidates",
            status.HTTP_409_CONFLICT,
        )
    has_profile, _ = await _vacancy_extras(db, vacancy)
    if has_profile:
        raise AppError(
            "vacancy_delete_has_profile",
            status.HTTP_409_CONFLICT,
        )

    await db.delete(vacancy)
    await db.commit()


async def close_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyCloseData,
) -> dict:
    """Close vacancy with resolution.

    Set status='closed', closed_at=now(), close_resolution, close_reason.
    If resolution='hired' and hired_candidate_id provided, set that
    candidate_vacancy status to 'hired' and move it onto the funnel's
    terminal-positive stage (HRP-425 — the analytics tiles count stages,
    so closing a vacancy has to leave the funnel telling the same story).
    """
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    vacancy.status = "closed"
    vacancy.closed_at = datetime.now(timezone.utc)
    vacancy.close_resolution = data.resolution
    vacancy.close_reason = data.close_reason

    if data.resolution == "hired" and data.hired_candidate_id:
        result = await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.candidate_id == data.hired_candidate_id,
                CandidateVacancy.vacancy_id == vacancy_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
        cv = result.scalar_one_or_none()
        if cv:
            cv.status = "hired"
            stages = await _get_applicable_stages(db, tenant_id, vacancy_id)
            hired_stage = next(
                (s for s in stages if s.stage_type == "terminal_positive"), None
            )
            if hired_stage is not None and cv.stage_id != hired_stage.id:
                history = list(cv.status_history or [])
                history.append(
                    {
                        "from_stage_id": str(cv.stage_id) if cv.stage_id else None,
                        "to_stage_id": str(hired_stage.id),
                        "changed_at": datetime.now(timezone.utc).isoformat(),
                        "comment": "vacancy closed as hired",
                    }
                )
                cv.stage_id = hired_stage.id
                cv.status_history = history
            # The row's ETag is W/"{version}". Closing the vacancy edits
            # the link (status, and usually the stage), so the version has
            # to move or a request holding the pre-close ETag would pass
            # its If-Match check and quietly overwrite the Hired stage.
            cv.version = (cv.version or 1) + 1

    await db.commit()
    # See update_vacancy comment — refresh both ``updated_at`` (server
    # onupdate) and ``candidates`` so post-commit reads neither lazy-load
    # nor pay an extra SELECT in production.
    await db.refresh(vacancy, attribute_names=["candidates", "updated_at"])
    has_profile, invites = await _vacancy_extras(db, vacancy)
    return await _vacancy_to_read_joined(
        db, tenant_id, vacancy, has_profile=has_profile, active_invites_count=invites
    )


# ---------------------------------------------------------------------------
# Funnel Stages
# ---------------------------------------------------------------------------


# HRP-181 REDO: canonical default funnel (FR-08). Order, names, codes,
# colors and terminal classification are spec-mandated — keep aligned
# with the seed in ``hrp181redo02_seed_default_stages``. Tuples are
# ``(code, name, sort_order, stage_type, color)``.
DEFAULT_RECRUITMENT_STAGES: tuple[tuple[str, str, int, str, str], ...] = (
    ("new", "New", 10, "active", "slate"),
    ("screening", "Screening", 20, "active", "blue"),
    ("tech_interview", "Tech interview", 30, "active", "indigo"),
    ("manager_interview", "Interview with manager", 40, "active", "violet"),
    ("final_interview", "Final interview", 50, "active", "purple"),
    ("offer", "Offer", 60, "active", "amber"),
    ("hired", "Hired", 70, "terminal_positive", "emerald"),
    ("rejected", "Rejected", 80, "terminal_negative", "rose"),
    ("withdrew", "Withdrew", 90, "terminal_neutral", "gray"),
)


async def seed_default_recruitment_stages(
    db: AsyncSession, tenant_id: uuid.UUID
) -> int:
    """Seed the 9 spec-mandated recruitment stages for a tenant.

    Idempotent: skips any ``(tenant_id, code)`` pair that already
    exists. Called from ``auth.service.register`` for new tenants; the
    migration ``hrp181redo02`` populates the existing fleet.

    Returns the number of stages actually inserted (0 on a re-run).
    """
    result = await db.execute(
        select(VacancyStage.code).where(
            VacancyStage.tenant_id == tenant_id,
            VacancyStage.vacancy_id.is_(None),
        )
    )
    existing_codes = {row[0] for row in result.all()}

    inserted = 0
    for code, name, sort_order, stage_type, color in DEFAULT_RECRUITMENT_STAGES:
        if code in existing_codes:
            continue
        db.add(
            VacancyStage(
                tenant_id=tenant_id,
                vacancy_id=None,
                name=name,
                code=code,
                sort_order=sort_order,
                is_terminal=stage_type != "active",
                stage_type=stage_type,
                color=color,
            )
        )
        inserted += 1
    if inserted:
        await db.flush()
    return inserted


async def list_stages(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID | None = None,
) -> list[dict]:
    """List stages: system defaults (tenant_id IS NULL) + tenant custom stages.

    If vacancy_id provided, include vacancy-specific overrides.
    """
    stages = await _get_applicable_stages(db, tenant_id, vacancy_id)
    return [
        {
            "id": s.id,
            "tenant_id": s.tenant_id,
            "vacancy_id": s.vacancy_id,
            "name": s.name,
            "code": s.code,
            "sort_order": s.sort_order,
            "is_terminal": s.is_terminal,
            "color": s.color,
        }
        for s in stages
    ]


async def create_stage(
    db: AsyncSession, tenant_id: uuid.UUID, data: VacancyStageCreate
) -> dict:
    """Create a tenant-level stage."""
    stage = VacancyStage(
        tenant_id=tenant_id,
        vacancy_id=None,
        **data.model_dump(),
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return {
        "id": stage.id,
        "tenant_id": stage.tenant_id,
        "vacancy_id": stage.vacancy_id,
        "name": stage.name,
        "code": stage.code,
        "sort_order": stage.sort_order,
        "is_terminal": stage.is_terminal,
        "color": stage.color,
    }


async def update_stage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stage_id: uuid.UUID,
    data: VacancyStageUpdate,
) -> dict:
    """Update a tenant-level stage."""
    result = await db.execute(
        select(VacancyStage).where(
            VacancyStage.id == stage_id,
            VacancyStage.tenant_id == tenant_id,
        )
    )
    stage = result.scalar_one_or_none()
    if not stage:
        raise AppError("vacancy_stage_not_found", status.HTTP_404_NOT_FOUND)

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(stage, field, value)
    await db.commit()
    await db.refresh(stage)
    return {
        "id": stage.id,
        "tenant_id": stage.tenant_id,
        "vacancy_id": stage.vacancy_id,
        "name": stage.name,
        "code": stage.code,
        "sort_order": stage.sort_order,
        "is_terminal": stage.is_terminal,
        "color": stage.color,
    }


async def delete_stage(
    db: AsyncSession, tenant_id: uuid.UUID, stage_id: uuid.UUID
) -> None:
    """Delete tenant stage. Cannot delete system stages (tenant_id IS NULL)."""
    result = await db.execute(select(VacancyStage).where(VacancyStage.id == stage_id))
    stage = result.scalar_one_or_none()
    if not stage:
        raise AppError("vacancy_stage_not_found", status.HTTP_404_NOT_FOUND)

    if stage.tenant_id is None:
        raise AppError("vacancy_stage_system_delete_forbidden", status.HTTP_403_FORBIDDEN)
    if stage.tenant_id != tenant_id:
        raise AppError("vacancy_stage_not_found", status.HTTP_404_NOT_FOUND)

    await db.delete(stage)
    await db.commit()


async def create_vacancy_stage_override(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyStageCreate,
) -> dict:
    """Create a vacancy-specific stage override."""
    await _get_vacancy(db, tenant_id, vacancy_id)

    stage = VacancyStage(
        tenant_id=tenant_id,
        vacancy_id=vacancy_id,
        **data.model_dump(),
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return {
        "id": stage.id,
        "tenant_id": stage.tenant_id,
        "vacancy_id": stage.vacancy_id,
        "name": stage.name,
        "code": stage.code,
        "sort_order": stage.sort_order,
        "is_terminal": stage.is_terminal,
        "color": stage.color,
    }


# ---------------------------------------------------------------------------
# HRP-181 REDO Stage 2 — stages funnel (tenant defaults + per-vacancy override)
# ---------------------------------------------------------------------------


async def get_tenant_default_stages(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict]:
    """List the tenant's nine default funnel stages (FR-08).

    Rows are seeded at tenant create (``auth.service.register`` calls
    ``seed_default_recruitment_stages``). Returns them in ``sort_order``.
    """
    rows = (
        (
            await db.execute(
                select(VacancyStage)
                .where(
                    VacancyStage.tenant_id == tenant_id,
                    VacancyStage.vacancy_id.is_(None),
                )
                .order_by(VacancyStage.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [_stage_to_read_dict(s) for s in rows]  # type: ignore[misc]


async def get_effective_vacancy_stages(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[dict]:
    """Stages the vacancy actually uses: per-vacancy override if present,
    otherwise tenant defaults.

    The override is all-or-nothing per FR-08 — a vacancy either rides on
    the tenant funnel or replaces it wholesale, no merging.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    overrides = (
        (
            await db.execute(
                select(VacancyStage)
                .where(
                    VacancyStage.tenant_id == tenant_id,
                    VacancyStage.vacancy_id == vacancy_id,
                )
                .order_by(VacancyStage.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if overrides:
        return [_stage_to_read_dict(s) for s in overrides]  # type: ignore[misc]
    return await get_tenant_default_stages(db, tenant_id)


async def replace_vacancy_stages_override(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyStagesReplace,
) -> list[dict]:
    """Replace the per-vacancy funnel with ``data.stages`` (FR-08).

    - Existing override rows not referenced in the payload are deleted —
      blocked with 409 + ``affected_candidate_count`` if any candidate
      sits on a soon-to-be-deleted stage.
    - Rows with ``id`` set get their fields updated in place; rows
      without an ``id`` are inserted.
    - On the very first override, copies of tenant defaults are *not*
      synthesised — the client sends whatever stages the funnel should
      have. Anything previously on the tenant defaults remains attached
      to the funnel only via ``CandidateVacancy.stage_id`` history.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    # HRP-181 REDO: validate payload-level invariants before touching the
    # DB. Without these guards a client could ship an all-terminal funnel
    # (every subsequent attach lands with ``stage_id=NULL`` because
    # ``_first_non_terminal_stage_id`` returns None), or duplicate codes
    # that silently coexist on the same vacancy.
    if not data.stages:
        raise AppError(
            "vacancy_funnel_empty",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    active_count = sum(1 for item in data.stages if item.stage_type == "active")
    if active_count == 0:
        raise AppError(
            "vacancy_funnel_no_active_stage",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    submitted_codes = [item.code for item in data.stages]
    if len(set(submitted_codes)) != len(submitted_codes):
        raise AppError(
            "vacancy_stage_codes_not_unique",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    existing = (
        (
            await db.execute(
                select(VacancyStage).where(
                    VacancyStage.tenant_id == tenant_id,
                    VacancyStage.vacancy_id == vacancy_id,
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_id = {s.id: s for s in existing}

    submitted_ids = {item.id for item in data.stages if item.id is not None}
    to_delete = [s for s in existing if s.id not in submitted_ids]
    if to_delete:
        affected = (
            await db.execute(
                select(
                    CandidateVacancy.stage_id,
                    func.count(CandidateVacancy.id),
                )
                .where(
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                    CandidateVacancy.stage_id.in_([s.id for s in to_delete]),
                )
                .group_by(CandidateVacancy.stage_id)
            )
        ).all()
        if affected:
            total = sum(count for _, count in affected)
            raise AppError(
                "stage_has_candidates",
                status.HTTP_409_CONFLICT,
                detail_extra={
                    "affected_candidate_count": int(total),
                    "stage_ids": [str(stage_id) for stage_id, _ in affected],
                },
            )
        for s in to_delete:
            await db.delete(s)

    out: list[VacancyStage] = []
    for item in data.stages:
        is_terminal = item.stage_type != "active"
        if item.id is not None and item.id in existing_by_id:
            stage = existing_by_id[item.id]
            stage.name = item.name
            stage.code = item.code
            stage.sort_order = item.sort_order
            stage.stage_type = item.stage_type
            stage.is_terminal = is_terminal
            stage.color = item.color
            out.append(stage)
        else:
            stage = VacancyStage(
                tenant_id=tenant_id,
                vacancy_id=vacancy_id,
                name=item.name,
                code=item.code,
                sort_order=item.sort_order,
                stage_type=item.stage_type,
                is_terminal=is_terminal,
                color=item.color,
            )
            db.add(stage)
            out.append(stage)

    await db.commit()
    for s in out:
        await db.refresh(s)
    out.sort(key=lambda s: s.sort_order)
    return [_stage_to_read_dict(s) for s in out]  # type: ignore[misc]
