"""Candidates: person-dedup CRUD, candidate-vacancy links, resumes,
canonical candidate API (HRP-181 REDO Stage 2), enriched vacancy
candidate rows with matrix aggregates (HRP-267) and bulk resume upload
(HRP-181 REDO Stage 3).

Split out of ``service.py`` (project-review #7); see ``service.py`` for
the delegating namespace.
"""

import copy
import logging
import re
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import UploadFile, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import AppError
from app.models import Person
from app.modules.auth.models import User
from app.modules.demo.utils import is_demo_tenant
from app.modules.employee.models import Employee
from app.modules.recruitment.assessment_service import (
    get_assessment_matrix,
)
from app.modules.recruitment.common import (
    _get_applicable_stages,
    _get_candidate,
    _get_vacancy,
    _publish_event,
    _stage_to_read_dict,
    candidate_display_name,
)
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    Vacancy,
    VacancyStage,
)
from app.modules.recruitment.schemas import (
    BatchFinalizeRequest,
    CandidateCanonicalPatch,
    CandidateCreate,
    CandidateManualCreate,
    CandidateUpdate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    CandidateVacancyStatusUpdate,
    PersonUpdate,
)
from app.modules.storage.models import File

logger = logging.getLogger(__name__)


def _candidate_to_read(candidate: Candidate, is_employee: bool = False) -> dict:
    """Convert Candidate ORM to API response dict with person data.

    HRP-181 REDO: ``person`` is None for externally-sourced candidates
    (person_id NULL). Always emit the denormalised canonical fields
    (``full_name``, ``email``, ``phone``) so the legacy list/card UI can
    fall back when ``person`` is missing.
    """
    person = candidate.person
    return {
        "id": candidate.id,
        "person_id": candidate.person_id,
        "full_name": candidate.full_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "person": (
            {
                "id": person.id,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "middle_name": person.middle_name,
                "email": person.email,
                "phone": person.phone,
            }
            if person
            else None
        ),
        "source": candidate.source,
        "notes": candidate.notes,
        "resumes_count": (
            sum(1 for f in candidate.files if f.file_type == "resume")
            if candidate.files
            else 0
        ),
        "is_employee": is_employee,
        "created_at": candidate.created_at,
    }


# ---------------------------------------------------------------------------
# Candidates (with person dedup)
# ---------------------------------------------------------------------------


async def _employee_person_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    person_ids: Iterable[uuid.UUID | None],
) -> set[uuid.UUID]:
    """Which of these persons are employees of this tenant.

    HRP-663: one statement for a whole page. The per-row twin below used
    to be called inside the list loop and cost two queries per candidate.

    HRP-181 REDO: externally-sourced candidates have ``person_id=None``.
    Dropping the NULLs is the safe answer — without it the
    ``User.person_id IN (...)`` predicate would carry a NULL and, in the
    single-id form this replaced, matched every tenant user with a NULL
    person_id, falsely flagging external candidates as employees.
    """
    ids = {p for p in person_ids if p is not None}
    if not ids:
        return set()
    rows = await db.execute(
        select(User.person_id)
        .join(Employee, Employee.user_id == User.id)
        .where(
            User.person_id.in_(ids),
            User.tenant_id == tenant_id,
            Employee.tenant_id == tenant_id,
        )
    )
    return {row[0] for row in rows}


async def _check_is_employee(
    db: AsyncSession, tenant_id: uuid.UUID, person_id: uuid.UUID | None
) -> bool:
    """Is this person an employee of this tenant (single-row form)."""
    return bool(await _employee_person_ids(db, tenant_id, [person_id]))


async def create_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, data: CandidateCreate
) -> dict:
    """Create candidate with person dedup logic.

    1. If email provided, search persons table by email (case-insensitive)
    2. If person found, check if already a candidate in this tenant -> raise 409
    3. If person found but not a candidate here -> create candidate linked to existing person
    4. If person not found -> create new person, then create candidate
    5. Check if person is linked to a user who is an employee in this tenant -> set is_employee flag
    """
    existing_person = None
    if data.email and not await is_demo_tenant(db, tenant_id):
        # Cross-tenant Person dedup is disabled for demo tenants: a public
        # demo session must never resolve emails to real users' Person rows
        # (that would leak their first/last name + phone via the candidate
        # response). Demo always gets a fresh Person.
        result = await db.execute(
            select(Person).where(func.lower(Person.email) == data.email.lower())
        )
        existing_person = result.scalar_one_or_none()

    if existing_person:
        # Check if already a candidate in this tenant
        result = await db.execute(
            select(Candidate).where(
                Candidate.person_id == existing_person.id,
                Candidate.tenant_id == tenant_id,
            )
        )
        if result.scalar_one_or_none():
            raise AppError(
                "person_already_candidate",
                status.HTTP_409_CONFLICT,
            )
        person = existing_person
    else:
        # Create new person
        person = Person(
            first_name=data.first_name,
            last_name=data.last_name,
            middle_name=data.middle_name,
            email=data.email,
            phone=data.phone,
        )
        db.add(person)
        await db.flush()

    full_name = (
        " ".join(
            part
            for part in (person.first_name, person.middle_name, person.last_name)
            if part
        ).strip()
        or "Unnamed candidate"
    )

    candidate = Candidate(
        tenant_id=tenant_id,
        person_id=person.id,
        full_name=full_name,
        email=person.email,
        phone=person.phone,
        source=data.source,
        notes=data.notes,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate, ["person", "files"])

    is_employee = await _check_is_employee(db, tenant_id, person.id)
    return _candidate_to_read(candidate, is_employee=is_employee)


async def list_candidates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 25,
    search: str | None = None,
    vacancy_id: uuid.UUID | None = None,
    scope_filter: ColumnElement[bool] | None = None,
) -> tuple[list[dict], int]:
    """List candidates.

    ``scope_filter`` (HRP-629) keeps only candidates attached to at least
    one vacancy the caller may see; ``None`` means no restriction.

    HRP-181 REDO: ``person_id`` is now nullable — externally-sourced
    candidates (manual add + bulk-upload finalize) have no linked Person
    row. Use a LEFT OUTER JOIN so they stay visible in the list, and
    apply text search against both Person fields and the denormalised
    canonical columns on Candidate.
    """
    query = (
        select(Candidate)
        .options(selectinload(Candidate.person), selectinload(Candidate.files))
        .outerjoin(Person, Candidate.person_id == Person.id)
        .where(Candidate.tenant_id == tenant_id)
    )
    count_query = (
        select(func.count(Candidate.id))
        .outerjoin(Person, Candidate.person_id == Person.id)
        .where(Candidate.tenant_id == tenant_id)
    )

    if vacancy_id:
        query = query.join(
            CandidateVacancy, CandidateVacancy.candidate_id == Candidate.id
        ).where(CandidateVacancy.vacancy_id == vacancy_id)
        count_query = count_query.join(
            CandidateVacancy, CandidateVacancy.candidate_id == Candidate.id
        ).where(CandidateVacancy.vacancy_id == vacancy_id)

    if scope_filter is not None:
        in_scope = (
            select(1)
            .select_from(CandidateVacancy)
            .join(Vacancy, Vacancy.id == CandidateVacancy.vacancy_id)
            .where(CandidateVacancy.candidate_id == Candidate.id, scope_filter)
            .exists()
        )
        query = query.where(in_scope)
        count_query = count_query.where(in_scope)

    if search:
        like = f"%{search}%"
        search_filter = or_(
            Person.first_name.ilike(like),
            Person.last_name.ilike(like),
            Person.email.ilike(like),
            Candidate.full_name.ilike(like),
            Candidate.email.ilike(like),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Candidate.created_at.desc()).offset(skip).limit(limit)
    )
    candidates = result.scalars().unique().all()

    # HRP-663: one lookup for the page, not two queries per row.
    employee_person_ids = await _employee_person_ids(
        db, tenant_id, [c.person_id for c in candidates]
    )
    items = [
        _candidate_to_read(c, is_employee=c.person_id in employee_person_ids)
        for c in candidates
    ]
    return items, total


async def get_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> dict:
    """Get single candidate with person data."""
    candidate = await _get_candidate(db, tenant_id, candidate_id)
    is_emp = await _check_is_employee(db, tenant_id, candidate.person_id)
    return _candidate_to_read(candidate, is_employee=is_emp)


async def update_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    data: CandidateUpdate,
) -> dict:
    """Update candidate fields (exclude_unset)."""
    candidate = await _get_candidate(db, tenant_id, candidate_id)
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(candidate, field, value)
    await db.commit()
    await db.refresh(candidate, ["person", "files"])
    is_emp = await _check_is_employee(db, tenant_id, candidate.person_id)
    return _candidate_to_read(candidate, is_employee=is_emp)


async def update_person(
    db: AsyncSession, person_id: uuid.UUID, data: PersonUpdate
) -> dict:
    """Update person fields (name, email, phone) for inline edits on candidate card.

    HRP-181 REDO: Candidate.full_name/email/phone are denormalised from
    Person for the canonical list and partial unique index — propagate
    the Person edit to every linked Candidate row so the list stays in
    sync and the dedup index keeps working.
    """
    person = await db.get(Person, person_id)
    if not person:
        raise AppError("person_not_found", status.HTTP_404_NOT_FOUND)

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(person, field, value)

    linked_q = await db.execute(
        select(Candidate).where(Candidate.person_id == person.id)
    )
    full_name = (
        " ".join(
            part
            for part in (person.first_name, person.middle_name, person.last_name)
            if part
        ).strip()
        or "Unnamed candidate"
    )
    for cand in linked_q.scalars().all():
        cand.full_name = full_name
        if "email" in updates:
            cand.email = person.email
        if "phone" in updates:
            cand.phone = person.phone

    await db.commit()
    await db.refresh(person)
    return {
        "id": person.id,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "middle_name": person.middle_name,
        "email": person.email,
        "phone": person.phone,
    }


# ---------------------------------------------------------------------------
# Candidate-Vacancy
# ---------------------------------------------------------------------------


async def attach_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CandidateVacancyCreate,
) -> dict:
    """Link candidate to vacancy.

    Create CandidateVacancy with default stage (first non-terminal).
    """
    # Validate candidate and vacancy belong to tenant
    await _get_candidate(db, tenant_id, data.candidate_id)
    await _get_vacancy(db, tenant_id, data.vacancy_id)

    # Check not already linked
    result = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.candidate_id == data.candidate_id,
            CandidateVacancy.vacancy_id == data.vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none():
        raise AppError(
            "candidate_already_linked_to_vacancy",
            status.HTTP_409_CONFLICT,
        )

    # Resolve stage: use provided or find first non-terminal stage
    stage_id = data.stage_id
    if not stage_id:
        stages = await _get_applicable_stages(db, tenant_id, data.vacancy_id)
        non_terminal = [s for s in stages if not s.is_terminal]
        if non_terminal:
            non_terminal.sort(key=lambda s: s.sort_order)
            stage_id = non_terminal[0].id

    cv = CandidateVacancy(
        tenant_id=tenant_id,
        candidate_id=data.candidate_id,
        vacancy_id=data.vacancy_id,
        stage_id=stage_id,
        status="new",
        status_history=[],
        attached_by=user_id,
    )
    db.add(cv)
    await db.commit()
    await db.refresh(cv, ["candidate", "vacancy", "stage"])

    candidate_name = None
    if cv.candidate and cv.candidate.person:
        person = cv.candidate.person
        candidate_name = f"{person.first_name} {person.last_name}".strip()
    await _publish_event(
        "recruitment.candidate.attached",
        {
            "tenant_id": str(tenant_id),
            "cv_id": str(cv.id),
            "candidate_id": str(cv.candidate_id),
            "vacancy_id": str(cv.vacancy_id),
            "vacancy_title": cv.vacancy.title if cv.vacancy else None,
            "candidate_name": candidate_name,
            "owner_id": (
                str(cv.vacancy.owner_id) if cv.vacancy and cv.vacancy.owner_id else None
            ),
            "actor_id": str(user_id),
        },
    )
    return _cv_to_read(cv)


async def change_candidate_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: CandidateVacancyStatusUpdate,
) -> dict:
    """Change candidate-vacancy status.

    Append to status_history JSONB array:
    {"from_stage_id": old, "to_stage_id": new, "changed_at": now, "comment": data.comment}
    """
    result = await db.execute(
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate),
            selectinload(CandidateVacancy.vacancy),
            selectinload(CandidateVacancy.stage),
        )
        .where(
            CandidateVacancy.id == cv_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    old_stage_id = cv.stage_id

    history_entry = {
        "from_stage_id": str(old_stage_id) if old_stage_id else None,
        "to_stage_id": str(data.stage_id),
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "comment": data.comment,
    }

    # Must create a new list to trigger JSONB update detection
    updated_history = list(cv.status_history or [])
    updated_history.append(history_entry)
    cv.status_history = updated_history
    cv.stage_id = data.stage_id

    await db.commit()
    await db.refresh(cv, ["candidate", "vacancy", "stage"])

    stage_changed = str(old_stage_id) != str(data.stage_id)
    if stage_changed:
        candidate_name = None
        if cv.candidate and cv.candidate.person:
            person = cv.candidate.person
            candidate_name = f"{person.first_name} {person.last_name}".strip()
        await _publish_event(
            "recruitment.candidate.stage_changed",
            {
                "tenant_id": str(tenant_id),
                "cv_id": str(cv.id),
                "candidate_id": str(cv.candidate_id),
                "vacancy_id": str(cv.vacancy_id),
                "candidate_name": candidate_name,
                "vacancy_title": cv.vacancy.title if cv.vacancy else None,
                "stage_name": cv.stage.name if cv.stage else None,
                "owner_id": (
                    str(cv.vacancy.owner_id)
                    if cv.vacancy and cv.vacancy.owner_id
                    else None
                ),
                "actor_id": str(cv.attached_by) if cv.attached_by else None,
            },
        )
    return _cv_to_read(cv)


def _cv_to_read(cv: CandidateVacancy) -> dict:
    """Convert CandidateVacancy ORM to API response dict."""
    # HRP-504: the name used to come from the linked HR Person only, but
    # ``Candidate.person_id`` is optional (HRP-181 REDO) — every candidate
    # added from a resume or by hand has none, so this returned NULL and
    # callers printed the raw UUID. ``full_name`` is the denormalised
    # source of truth, same as the enriched listing uses.
    candidate_name = candidate_display_name(cv.candidate) if cv.candidate else None

    return {
        "id": cv.id,
        "candidate_id": cv.candidate_id,
        "vacancy_id": cv.vacancy_id,
        "stage_id": cv.stage_id,
        "status": cv.status,
        "status_history": cv.status_history or [],
        "ranking_score": cv.ranking_score,
        "stage_name": cv.stage.name if cv.stage else None,
        "candidate_name": candidate_name,
        "vacancy_title": cv.vacancy.title if cv.vacancy else None,
        "created_at": cv.created_at,
    }


async def get_candidate_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
) -> dict:
    """Return a single candidate-vacancy link with candidate + vacancy names.

    Used by the interview detail page to render breadcrumbs and labels
    without an extra round-trip per related entity.
    """

    cv = (
        await db.execute(
            select(CandidateVacancy)
            .options(
                selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
                selectinload(CandidateVacancy.vacancy),
                selectinload(CandidateVacancy.stage),
            )
            .where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)
    return _cv_to_read(cv)


async def list_vacancy_candidates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    skip: int = 0,
    limit: int = 25,
) -> tuple[list[dict], int]:
    """List candidates linked to a specific vacancy with their stages/scores."""
    await _get_vacancy(db, tenant_id, vacancy_id)

    count_query = select(func.count(CandidateVacancy.id)).where(
        CandidateVacancy.vacancy_id == vacancy_id,
        CandidateVacancy.tenant_id == tenant_id,
    )
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
            selectinload(CandidateVacancy.vacancy),
            selectinload(CandidateVacancy.stage),
        )
        .where(
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
        .order_by(CandidateVacancy.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    cvs = result.scalars().unique().all()
    return [_cv_to_read(cv) for cv in cvs], total


# ---------------------------------------------------------------------------
# Candidate files (resume) — list, inline-edit parsed payload, signed URL
# ---------------------------------------------------------------------------


def _resume_to_read(resume: CandidateFile) -> dict:
    return {
        "id": resume.id,
        "candidate_id": resume.candidate_id,
        "file_id": resume.file_id,
        "file_type": resume.file_type,
        "original_filename": resume.original_filename,
        "mime_type": resume.mime_type,
        "file_size": resume.file_size,
        "parsed_data": resume.parsed_data,
        "raw_text": resume.raw_text,
        "parse_status": resume.parse_status,
        "created_at": resume.created_at,
    }


async def list_candidate_resumes(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> list[dict]:
    """List all resumes for a candidate, latest first.

    HRP-181 REDO: ``candidate_files`` is polymorphic (resumes + interview
    media). Filter on ``file_type='resume'`` so an interview audio/video
    row attached to the same candidate doesn't surface through the
    resume endpoint.
    """
    await _get_candidate(db, tenant_id, candidate_id)
    result = await db.execute(
        select(CandidateFile)
        .where(
            CandidateFile.candidate_id == candidate_id,
            CandidateFile.tenant_id == tenant_id,
            CandidateFile.file_type == "resume",
        )
        .order_by(CandidateFile.created_at.desc())
    )
    return [_resume_to_read(r) for r in result.scalars().all()]


async def update_resume_parsed_data(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    resume_id: uuid.UUID,
    parsed_data: dict,
) -> dict:
    """Update parsed_data on a resume (inline-edit on extracted fields).

    HRP-181 REDO: refuse non-resume rows so an interview audio file id
    accidentally routed here cannot have its ``parsed_data`` overwritten
    with resume JSON.
    """
    result = await db.execute(
        select(CandidateFile).where(
            CandidateFile.id == resume_id,
            CandidateFile.tenant_id == tenant_id,
            CandidateFile.file_type == "resume",
        )
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise AppError("resume_not_found", status.HTTP_404_NOT_FOUND)
    resume.parsed_data = parsed_data
    await db.commit()
    await db.refresh(resume)
    return _resume_to_read(resume)


def _attachment_disposition(filename: str) -> str:
    """Content-Disposition for a forced download, RFC 5987-encoded."""
    ascii_name = (
        unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    )
    # Header value: no quotes/backslashes/control chars in the fallback.
    ascii_name = re.sub(r'["\\\x00-\x1f\x7f]', "", ascii_name).strip()
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = "resume" + ascii_name
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


async def get_resume_download_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    resume_id: uuid.UUID,
    disposition: str = "inline",
) -> dict:
    """Return a presigned download URL for a resume file.

    HRP-347: ``disposition="attachment"`` makes the presigned URL force a
    browser download with the original filename; the default keeps the
    inline behaviour the resume preview iframe relies on.
    """
    from app.core.s3 import get_presigned_url

    result = await db.execute(
        select(CandidateFile).where(
            CandidateFile.id == resume_id,
            CandidateFile.tenant_id == tenant_id,
            CandidateFile.file_type == "resume",
        )
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise AppError("resume_not_found", status.HTTP_404_NOT_FOUND)
    if not resume.file_id:
        raise AppError("resume_file_missing", status.HTTP_404_NOT_FOUND)

    file_record = await db.get(File, resume.file_id)
    if not file_record:
        raise AppError("file_record_not_found", status.HTTP_404_NOT_FOUND)
    content_disposition = (
        _attachment_disposition(resume.original_filename or "resume")
        if disposition == "attachment"
        else None
    )
    url = get_presigned_url(file_record.path, content_disposition=content_disposition)
    if url is None:
        raise AppError("s3_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
    return {
        "url": url,
        "mime_type": resume.mime_type,
        "filename": resume.original_filename,
    }


async def list_candidate_vacancies(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    scope_filter: ColumnElement[bool] | None = None,
) -> list[dict]:
    """List candidate-vacancy links for a single candidate.

    ``scope_filter`` (HRP-629) hides applications to vacancies outside the
    caller's scope: reaching the candidate through one division's vacancy
    must not reveal that they also applied to another division's.
    """
    await _get_candidate(db, tenant_id, candidate_id)
    query = (
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
            selectinload(CandidateVacancy.vacancy),
            selectinload(CandidateVacancy.stage),
        )
        .where(
            CandidateVacancy.candidate_id == candidate_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if scope_filter is not None:
        query = query.join(Vacancy, Vacancy.id == CandidateVacancy.vacancy_id).where(
            scope_filter
        )
    result = await db.execute(query.order_by(CandidateVacancy.created_at.desc()))
    return [_cv_to_read(cv) for cv in result.scalars().unique().all()]


# ---------------------------------------------------------------------------
# HRP-181 REDO Stage 2 — canonical candidate API
# ---------------------------------------------------------------------------


def candidate_vacancy_etag(cv: CandidateVacancy | dict) -> str:
    """Weak ETag derived from ``candidate_vacancies.version``.

    Mirrors :func:`vacancy_etag` (HRP-177): clients send ``If-Match`` on
    PATCH and a stale token returns 412 so concurrent stage moves never
    silently clobber each other.
    """
    version = cv.version if isinstance(cv, CandidateVacancy) else cv["version"]
    return f'W/"{version}"'


def candidate_etag(candidate: Candidate | dict) -> str:
    """Weak ETag for candidates. Reuses the same updated_at-derived counter
    as the rest of the module — the canonical Candidate table does not have
    a ``version`` column (yet), so the ISO updated_at is used as the cache
    key. Stage 5 may swap this for a real bump counter."""

    ts: datetime | None
    if isinstance(candidate, Candidate):
        ts = candidate.updated_at
    else:
        ts = candidate.get("updated_at")
    return f'W/"{ts.isoformat() if ts is not None else "0"}"'


def _normalised_parsed_resume(parsed: dict | None) -> dict | None:
    """Read-time HRP-346 / HRP-686 mapping for payloads parsed before the fix.

    Stored payloads keep legacy keys forever — ``period`` / ``achievements``
    on experience, ``year`` on education, ``title`` / ``year`` on
    certificates. Normalise a copy on the way out so old candidates render
    dates, descriptions and certificate names without a re-parse. The
    stored JSONB is not mutated.
    """
    if not isinstance(parsed, dict):
        return parsed
    from app.modules.recruitment.ai_service import _normalise_resume_entries

    parsed = copy.deepcopy(parsed)
    _normalise_resume_entries(parsed)
    return parsed


def _candidate_canonical_to_read(candidate: Candidate, *, is_employee: bool) -> dict:
    """Serialise canonical Candidate row for ``CandidateCanonicalRead``.

    HRP-663: ``is_employee`` is required, not defaulted. The flag lives on
    no column of this row, and every client merges the body it gets back
    into the card it already shows — a silent ``False`` here wipes the
    internal-candidate badge on save. Making the caller state it keeps the
    next surface from inheriting that bug.
    """
    return {
        "id": candidate.id,
        "tenant_id": candidate.tenant_id,
        "full_name": candidate.full_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "linkedin_url": candidate.linkedin_url,
        "location": candidate.location,
        "current_position": candidate.current_position,
        "years_of_experience": candidate.years_of_experience,
        "source": candidate.source,
        "notes": candidate.notes,
        "parsed_resume_jsonb": _normalised_parsed_resume(candidate.parsed_resume_jsonb),
        "is_employee": is_employee,
        "archived_at": candidate.archived_at,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }


def _last_position_from_parsed(parsed: dict | None) -> str | None:
    """Pull the most recent role title off the LLM payload.

    ``parsed_resume_jsonb.experience`` is a list ordered newest-first by
    the parser; the first entry's ``position`` (or legacy ``title``) is
    what the table column displays.
    """
    if not parsed:
        return None
    exp = parsed.get("experience") if isinstance(parsed, dict) else None
    if not exp or not isinstance(exp, list):
        return None
    head = exp[0]
    if not isinstance(head, dict):
        return None
    return head.get("position") or head.get("title")


def _candidate_vacancy_enriched_dict(cv: CandidateVacancy) -> dict:
    """Build a CandidateVacancyEnrichedRead-shaped dict from an ORM row.

    HRP-267 aggregates (manager_percent / ai_percent / divergence_count
    / divergence_top) are left at their schema defaults here — they need
    a vacancy-wide async lookup (the Compact matrix). Use
    :func:`apply_matrix_aggregates` to populate them after this helper.
    """
    candidate = cv.candidate
    full_name = candidate.full_name if candidate else ""
    parsed = candidate.parsed_resume_jsonb if candidate else None
    last_position = _last_position_from_parsed(parsed)
    if last_position is None and candidate is not None:
        last_position = candidate.current_position

    return {
        "id": cv.id,
        "candidate_id": cv.candidate_id,
        "vacancy_id": cv.vacancy_id,
        "candidate_name": full_name,
        # HRP-663: default False; filled in bulk by the list route (and
        # per-row by the PATCH route) so a page costs one lookup.
        "is_employee": False,
        "last_position": last_position,
        "years_of_experience": (candidate.years_of_experience if candidate else None),
        "stage_id": cv.stage_id,
        "stage": _stage_to_read_dict(cv.stage),
        "status": cv.status,
        "manager_score": cv.manager_score,
        "ai_score": cv.ai_score,
        # HRP-274: surfaced for the candidates-table toggle. NULL until the
        # finalizer writes both (raw 0..1 + tenant-scale normalized) on
        # completion.
        "ai_score_normalized": cv.ai_score_normalized,
        # HRP-662: divergence has exactly one definition in the product —
        # the per-competence comparison ``get_assessment_matrix`` makes
        # against the tenant threshold. This row-level flag is derived
        # from that count in :func:`apply_matrix_aggregates`; the old
        # second opinion (a hard-coded 1.0 gap between ``manager_score``
        # and ``ai_score_normalized``) could contradict the divergence
        # count printed in the very same row.
        "score_divergence": False,
        # HRP-267 — populated by apply_matrix_aggregates; defaults match
        # the schema so a non-aggregating caller still validates.
        "manager_percent": None,
        "ai_percent": None,
        "divergence_count": 0,
        "divergence_top": [],
        "ai_readiness": cv.ai_readiness,
        "ai_verdict": cv.ai_verdict,
        "ai_verdict_summary": cv.ai_verdict_summary,
        "ai_key_strength": cv.ai_key_strength,
        "ai_key_risk": cv.ai_key_risk,
        "ai_risk_mitigation": cv.ai_risk_mitigation,
        # HRP-204: surface the active analysis mode + data completeness
        # so the candidates table can render the ``[resume only]`` /
        # ``[full]`` sub-badge next to the verdict.
        "ai_analysis_mode": cv.ai_analysis_mode,
        "ai_data_completeness": cv.ai_data_completeness,
        "version": cv.version,
        "added_at": cv.added_at,
    }


# ---------------------------------------------------------------------------
# HRP-267: % match + Compact-matrix divergence on the candidates table
# ---------------------------------------------------------------------------

# Tooltip rows on the Divergence badge — keep it small so a recruiter
# scanning the table does not get a wall of text on hover.
_DIVERGENCE_TOOLTIP_LIMIT = 5


async def apply_matrix_aggregates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    payloads: list[dict],
    *,
    only_cv_ids: list[uuid.UUID] | None = None,
) -> None:
    """Mutate enriched-candidate payloads with Compact-matrix aggregates.

    Single source of truth for "what counts as divergent" is the tenant
    threshold loaded inside ``get_assessment_matrix`` — without this
    helper the candidates table would use the global hard-coded 1.0 and
    contradict the Compact matrix's own badge for the same data
    (HRP-265 → HRP-267 consistency). HRP-662 finished the job: the
    row-level ``score_divergence`` flag is derived here too, so the
    boolean and the count in one row can no longer disagree.
    """
    if not payloads:
        return
    matrix = await get_assessment_matrix(
        db, tenant_id, vacancy_id, only_cv_ids=only_cv_ids
    )
    competence_name_by_id: dict[str, str] = {
        str(comp["id"]): comp["name"] for comp in matrix["competences"]
    }
    aggregates_by_cv: dict[str, dict] = {
        str(cand["candidate_vacancy_id"]): cand for cand in matrix["candidates"]
    }
    for payload in payloads:
        cand = aggregates_by_cv.get(str(payload["id"]))
        if cand is None:
            continue
        payload["manager_percent"] = cand["manager_percent"]
        payload["ai_percent"] = cand["ai_percent"]
        payload["divergence_count"] = cand["divergence_count"]
        # HRP-662: the row flag and the row count are now one statement.
        payload["score_divergence"] = cand["divergence_count"] > 0
        # Build the tooltip preview from the divergent cells only. The
        # matrix cells are already in profile order, so the first N are
        # the natural pick — no extra ranking signal beyond "topmost".
        previews: list[dict] = []
        for cell in cand["cells"]:
            if not cell["divergence"]:
                continue
            comp_uuid = cell["competence_id"]
            previews.append(
                {
                    "competence_id": comp_uuid,
                    "competence_name": competence_name_by_id.get(
                        str(comp_uuid), str(comp_uuid)
                    ),
                    "manager_score": cell["manager_score"],
                    "ai_score": cell["ai_score"],
                }
            )
            if len(previews) >= _DIVERGENCE_TOOLTIP_LIMIT:
                break
        payload["divergence_top"] = previews


async def apply_manager_score_rounds(
    db: AsyncSession, tenant_id: uuid.UUID, payloads: list[dict]
) -> None:
    """Name the round each row's ``manager_score`` was computed from.

    HRP-727: the source round is derived on read by the one selector the
    recompute uses (``manager_assessment_service.resolve_score_rounds``),
    so the Manager-score tooltip can never name a round the number no
    longer comes from. Two queries for a whole page.
    """
    if not payloads:
        return
    from app.modules.recruitment.manager_assessment_service import (
        resolve_score_rounds,
        round_ref,
    )

    cv_ids = [p["id"] for p in payloads if p.get("manager_score") is not None]
    sources = await resolve_score_rounds(db, tenant_id, cv_ids)
    for payload in payloads:
        payload["manager_score_round"] = round_ref(sources.get(payload["id"]))


async def find_active_candidate_by_email(
    db: AsyncSession, tenant_id: uuid.UUID, email: str
) -> Candidate | None:
    """Duplicate-detect helper for the Upload-resume / manual-add flows.

    Matches on ``lower(email)`` against active rows only — archived twins
    are intentionally invisible so a soft-deleted candidate's address can
    be re-imported (see ``ux_candidates_tenant_email_active`` partial
    index in ``hrp181redo01``).
    """
    if not email:
        return None
    row = await db.execute(
        select(Candidate).where(
            Candidate.tenant_id == tenant_id,
            func.lower(Candidate.email) == email.lower(),
            Candidate.archived_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _first_non_terminal_stage_id(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> uuid.UUID | None:
    """Resolve the default landing stage for a new attachment.

    Picks the lowest-``sort_order`` ``stage_type='active'`` row from the
    effective list (per-vacancy override beats tenant default).
    """
    stages = await _get_applicable_stages(db, tenant_id, vacancy_id)
    actives = [s for s in stages if s.stage_type == "active"]
    actives.sort(key=lambda s: s.sort_order)
    return actives[0].id if actives else None


async def _load_canonical_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Candidate:
    """Fetch the canonical Candidate row with files preloaded.

    Differs from ``_get_candidate`` only in that it does not require a
    ``Person`` join — Stage 2 candidates can be external. Pass
    ``for_update=True`` to acquire a row-level lock so a concurrent PATCH
    on the same candidate waits instead of racing the ETag check.
    """
    query = (
        select(Candidate)
        .options(selectinload(Candidate.files))
        .where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == tenant_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    row = await db.execute(query)
    candidate = row.scalar_one_or_none()
    if not candidate:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    return candidate


def _denorm_from_parsed(parsed: dict | None) -> dict:
    """Derive denormalised Candidate columns from ``parsed_resume_jsonb``.

    Used by ``finalize_candidates_from_parsed`` at import time and by
    ``patch_candidate`` whenever the recruiter edits the resume payload —
    so the vacancy candidates table 'Last position' / 'Years exp.' /
    location / linkedin columns stay in sync with the source of truth.
    Returns only the keys that could be populated; the caller decides
    whether to clear or keep an existing column on a miss.
    """
    if not isinstance(parsed, dict):
        return {}
    out: dict = {}
    current_position = parsed.get("current_position")
    if not current_position:
        current_position = _last_position_from_parsed(parsed)
    if current_position:
        out["current_position"] = str(current_position)[:255]
    yoe = parsed.get("years_of_experience")
    if isinstance(yoe, (int, float)) and 0 <= yoe <= 80:
        out["years_of_experience"] = int(yoe)
    location = parsed.get("location")
    contacts = parsed.get("contacts") if isinstance(parsed, dict) else None
    if not location and isinstance(contacts, dict):
        location = contacts.get("location")
    if location:
        out["location"] = str(location)[:255]
    if isinstance(contacts, dict):
        linkedin = contacts.get("linkedin")
        if linkedin:
            out["linkedin_url"] = str(linkedin)[:500]
    return out


async def add_candidate_to_vacancy_manual(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: CandidateManualCreate,
) -> dict:
    """Manual candidate add (FR-04 / FR-09).

    Required: ``full_name`` plus ``email`` *or* ``phone``. When the email
    matches an active candidate in the tenant, returns 409 with
    ``existing_candidate_id`` so the client can prompt "link or force
    create"; ``link_candidate_id`` in the payload bypasses the duplicate
    check and attaches the existing row to the vacancy instead.

    Returns a dict with the canonical candidate payload plus the freshly-
    created ``candidate_vacancy_id`` and ``etag``.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    if not data.email and not data.phone:
        raise AppError(
            "candidate_email_or_phone_required",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    candidate: Candidate | None = None

    if data.link_candidate_id is not None:
        candidate = await _load_canonical_candidate(
            db, tenant_id, data.link_candidate_id
        )
        # HRP-181 REDO: refuse to re-link a soft-deleted candidate. The
        # PATCH path already returns 409 for archived rows; the manual-add
        # link path must mirror that or an archived candidate slips back
        # onto a vacancy with no edit affordance.
        if candidate.archived_at is not None:
            raise AppError(
                "candidate_archived",
                status.HTTP_409_CONFLICT,
                detail_extra={"existing_candidate_id": str(candidate.id)},
            )
    elif data.email is not None:
        existing = await find_active_candidate_by_email(db, tenant_id, data.email)
        if existing is not None:
            raise AppError(
                "candidate_email_conflict",
                status.HTTP_409_CONFLICT,
                detail_extra={"existing_candidate_id": str(existing.id)},
            )

    if candidate is None:
        candidate = Candidate(
            tenant_id=tenant_id,
            person_id=None,
            full_name=data.full_name.strip(),
            email=data.email,
            phone=data.phone,
            linkedin_url=data.linkedin_url,
            location=data.location,
            current_position=data.current_position,
            years_of_experience=data.years_of_experience,
            source=data.source,
            notes=data.notes,
        )
        db.add(candidate)
        await db.flush()

    # Refuse to re-link the same candidate to the same vacancy — the spec
    # only allows one row per (candidate, vacancy) pair.
    existing_cv = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.candidate_id == candidate.id,
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if existing_cv.scalar_one_or_none() is not None:
        raise AppError(
            "candidate_already_attached_to_vacancy",
            status.HTTP_409_CONFLICT,
        )

    stage_id = await _first_non_terminal_stage_id(db, tenant_id, vacancy_id)
    cv = CandidateVacancy(
        tenant_id=tenant_id,
        candidate_id=candidate.id,
        vacancy_id=vacancy_id,
        stage_id=stage_id,
        status="new",
        status_history=[],
        attached_by=user_id,
    )
    db.add(cv)
    await db.commit()
    await db.refresh(candidate, ["files"])
    await db.refresh(cv, ["candidate", "vacancy", "stage"])

    payload = _candidate_canonical_to_read(
        candidate,
        is_employee=await _check_is_employee(db, tenant_id, candidate.person_id),
    )
    payload["candidate_vacancy_id"] = cv.id
    payload["etag"] = candidate_vacancy_etag(cv)
    return payload


# ── HRP-711: an internal candidate becomes a real candidate ─────────


def _iso_date(value: date | None) -> str | None:
    """Canonical resume dates are strings; profile dates are ``date``."""
    return value.isoformat() if value else None


async def _employee_parsed_resume(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee: Employee,
    person: Person,
) -> dict:
    """Map an employee profile onto the canonical parsed-resume payload.

    HRP-711 mapping table, in the shape ``prompts.PARSE_RESUME`` asks the
    LLM for, so every reader of ``parsed_resume_jsonb`` (candidate card,
    interview prompt builder, ``_denorm_from_parsed``) works on an
    internal candidate without knowing where the payload came from:

    * Experience → Current + Previous employment  → ``experience``
    * Education → Education                       → ``education``
    * Education → Courses & Certifications        → ``certificates``
    * Competences → Current position + Other      → ``skills``

    ``summary`` stays ``None`` on purpose: no profile field answers it and
    a generated one would read as the parser's opinion of the person.
    """
    # Lazy: ``employee.service`` reaches into assessment/competence, and a
    # top-level import here would tie the recruitment module to that graph.
    from app.modules.company.models import Tenant
    from app.modules.employee import service as employee_service

    tenant = await db.get(Tenant, tenant_id)
    company_name = tenant.name if tenant else None

    work = await employee_service.list_work_experiences(db, tenant_id, employee.id)
    previous = await employee_service.list_previous_employments(
        db, tenant_id, employee.id
    )
    education = await employee_service.list_education(db, tenant_id, employee.id)
    courses = await employee_service.list_courses(db, tenant_id, employee.id)
    overview = await employee_service.get_competence_overview(
        db, tenant_id, employee.id
    )

    experience: list[dict] = []
    spans: list[tuple[date, date | None]] = []
    for we in work:
        # Current employment happens at this company by definition — the
        # row records the division and role, not the employer.
        position = we.get("position_title") or we.get("title") or we.get("role")
        description = " — ".join(
            part for part in (we.get("division_name"), we.get("description")) if part
        )
        experience.append(
            {
                "company": company_name,
                "position": position,
                "role": we.get("role") or position,
                "start_date": _iso_date(we.get("start_date")),
                "end_date": _iso_date(we.get("end_date")),
                "description": description or None,
            }
        )
        if we.get("start_date"):
            spans.append((we["start_date"], we.get("end_date")))
    for pe in previous:
        experience.append(
            {
                "company": pe.get("company_name"),
                "position": pe.get("position"),
                "role": pe.get("position"),
                "start_date": _iso_date(pe.get("start_date")),
                "end_date": _iso_date(pe.get("end_date")),
                "description": pe.get("description"),
            }
        )
        if pe.get("start_date"):
            spans.append((pe["start_date"], pe.get("end_date")))
    # Newest first, the order the whole codebase assumes of this list —
    # ``_last_position_from_parsed`` reads entry 0 as the current role, so
    # an open-ended spell outranks a finished one that started later.
    experience.sort(
        key=lambda e: (e["end_date"] is None, e["start_date"] or ""), reverse=True
    )

    today = date.today()
    total_days = sum(max(((end or today) - start).days, 0) for start, end in spans)

    skills: list[str] = []
    for block in ("current_position", "other"):
        for row in overview.get(block) or []:
            title = row.get("competence_title")
            if not title:
                continue
            level = row.get("skill_level_title")
            skills.append(f"{title} — {level}" if level else title)

    # The Person row is the canonical identity, but it is allowed to be
    # sparse (the seed and the importer both create name-only rows). Fall
    # back to the login so the resume never contradicts the candidate row
    # next to it, which is named and addressed from the User.
    user = employee.user
    first_name = person.first_name or user.first_name
    last_name = person.last_name or user.last_name
    return {
        "full_name": " ".join(p for p in (first_name, last_name) if p).strip() or None,
        "first_name": first_name,
        "last_name": last_name,
        "summary": None,
        "current_position": employee.position_title,
        "years_of_experience": int(total_days // 365) or None,
        "contacts": {"email": person.email or user.email, "phone": person.phone},
        "experience": experience,
        "education": [
            {
                "institution": e.get("institution"),
                "degree": e.get("degree"),
                "field": e.get("field_of_study"),
                "start_date": _iso_date(e.get("start_date")),
                "end_date": _iso_date(e.get("end_date")),
            }
            for e in education
        ],
        # dict.fromkeys: the overview can name the same competence twice
        # (required level in Current, a higher assessed one in Other).
        "skills": list(dict.fromkeys(skills)),
        "certificates": [
            {
                "name": c.get("title"),
                "issuer": c.get("provider"),
                "issued_at": _iso_date(c.get("completed_date")),
            }
            for c in courses
        ],
    }


async def _person_belongs_to_a_user(
    db: AsyncSession, tenant_id: uuid.UUID, person_id: uuid.UUID | None
) -> bool:
    """Is this Person somebody's login in this tenant?

    Guards the rebind in the internal-add path: a Person nobody signs in
    as is bookkeeping (importer rows, the fresh Person a demo tenant
    mints) and may be re-pointed; one that is a user's identity belongs
    to that person and is never taken from them.
    """
    if person_id is None:
        return False
    return bool(
        (
            await db.execute(
                select(User.id).where(
                    User.person_id == person_id, User.tenant_id == tenant_id
                )
            )
        ).first()
    )


async def add_internal_candidate_to_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> dict:
    """Move an employee off the internal shortlist into the pipeline (HRP-711).

    HRP-663 gave a candidate who already works here a badge; HRP-667 gave
    the vacancy a shortlist of such people. Between them sat a gap the
    recruiter had to close by hand: retyping a colleague whose profile the
    system already holds. This closes it — the profile becomes the resume.

    The mirror of ``add_candidate_to_vacancy_manual`` with three
    deliberate differences:

    (a) the employee must be on this vacancy's talent-card roster. The
        endpoint takes an employee id, and without this it would be a
        directory read that a requisition has no business granting.
    (b) an existing candidate on the same Person (or email) is reused
        rather than refused. Manual add answers 409 so the recruiter can
        choose link-or-create; here there is nothing to choose — the
        colleague is the same person either way.
    (c) ``User.person_id`` is backfilled when the employee's user row has
        none. The internal-candidate chip is computed through it
        (``_employee_person_ids``), so a candidate created without it
        would land in the pipeline as an external hire.
    """
    from app.modules.talent_market.models import TalentCandidate

    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    roster = None
    if vacancy.talent_card_id is not None:
        roster = (
            await db.execute(
                select(TalentCandidate)
                .options(selectinload(TalentCandidate.employee))
                .where(
                    TalentCandidate.card_id == vacancy.talent_card_id,
                    TalentCandidate.employee_id == employee_id,
                )
            )
        ).scalar_one_or_none()
    employee = roster.employee if roster is not None else None
    user = employee.user if employee is not None else None
    if employee is None or user is None or employee.tenant_id != tenant_id:
        raise AppError(
            "recruitment_internal_candidate_not_found",
            status.HTTP_404_NOT_FOUND,
        )

    person: Person | None = None
    if user.person_id is not None:
        person = await db.get(Person, user.person_id)
    if person is None and user.email and not await is_demo_tenant(db, tenant_id):
        # Same carve-out as ``create_candidate``: a demo session must not
        # resolve an address onto a real user's Person row.
        person = (
            await db.execute(
                select(Person).where(func.lower(Person.email) == user.email.lower())
            )
        ).scalar_one_or_none()
    if person is None:
        person = Person(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        db.add(person)
        await db.flush()
    if user.person_id != person.id:
        user.person_id = person.id

    # Archived rows count here, unlike the email lookup below.
    # ``uq_candidate_person_tenant`` covers (person_id, tenant_id) in
    # full — no ``archived_at`` in it — and ``archive_candidate`` keeps
    # person_id, so an archived twin still owns this Person. Filtering it
    # out sent the create branch straight into an IntegrityError 500 on
    # the second add of someone who had been archived once.
    candidate = (
        (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.person_id == person.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if candidate is not None and candidate.archived_at is not None:
        # Mirrors the manual-add link path: a soft-deleted candidate does
        # not slip back onto a vacancy, and the recruiter is told which
        # row is in the way instead of getting a 500.
        raise AppError(
            "candidate_archived",
            status.HTTP_409_CONFLICT,
            detail_extra={"existing_candidate_id": str(candidate.id)},
        )
    if candidate is None and user.email:
        candidate = await find_active_candidate_by_email(db, tenant_id, user.email)

    if candidate is None:
        parsed = await _employee_parsed_resume(db, tenant_id, employee, person)
        candidate = Candidate(
            tenant_id=tenant_id,
            person_id=person.id,
            full_name=parsed["full_name"] or user.email,
            email=user.email,
            phone=person.phone,
            source="internal",
            parsed_resume_jsonb=parsed,
            **_denorm_from_parsed(parsed),
        )
        db.add(candidate)
        await db.flush()
    elif candidate.person_id != person.id and not await _person_belongs_to_a_user(
        db, tenant_id, candidate.person_id
    ):
        # An email-matched row whose Person is nobody's — created before
        # this employee had one, or minted fresh by ``create_candidate``
        # in a demo tenant. Rebind it to the employee's Person, or the
        # internal-candidate chip (resolved through ``User.person_id``)
        # stays off for the rest of that row's life and the shortlist
        # keeps offering an Add that can only 409. Safe against the
        # unique constraint: the lookup above proved no row holds this
        # Person already.
        candidate.person_id = person.id

    existing_cv = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.candidate_id == candidate.id,
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if existing_cv.scalar_one_or_none() is not None:
        raise AppError(
            "candidate_already_attached_to_vacancy",
            status.HTTP_409_CONFLICT,
        )

    cv = CandidateVacancy(
        tenant_id=tenant_id,
        candidate_id=candidate.id,
        vacancy_id=vacancy_id,
        stage_id=await _first_non_terminal_stage_id(db, tenant_id, vacancy_id),
        status="new",
        status_history=[],
        attached_by=user_id,
    )
    db.add(cv)
    await db.commit()
    # ``updated_at`` too, not just the relationship: rebinding an existing
    # row's Person makes this an UPDATE, and the server-side onupdate
    # leaves the column expired — reading it back in the serializer would
    # be a lazy load outside the greenlet.
    await db.refresh(candidate, ["files", "updated_at"])
    await db.refresh(cv, ["candidate", "vacancy", "stage"])

    # Computed, not asserted: when the reused row kept a Person of its
    # own (one that does belong to another user), the lists resolve the
    # chip through that Person and would disagree with a hardcoded True.
    payload = _candidate_canonical_to_read(
        candidate,
        is_employee=await _check_is_employee(db, tenant_id, candidate.person_id),
    )
    payload["candidate_vacancy_id"] = cv.id
    payload["etag"] = candidate_vacancy_etag(cv)
    return payload


async def finalize_candidates_from_parsed(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: BatchFinalizeRequest,
) -> dict:
    """Batch-finalise candidates after the Celery parser has run.

    Walks the requested ``files`` (CandidateFile rows already parsed by
    Stage 3), creating one Candidate per file (or linking to the row the
    client picked when the dup prompt fired). Each new Candidate also
    gets a ``CandidateVacancy`` on the vacancy's default landing stage.

    Returns ``{"created": [...], "linked": [...], "skipped": [...]}``
    with per-file outcomes so the modal can render the import summary.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    if not data.files:
        return {"created": [], "linked": [], "skipped": []}

    file_ids = [f.file_id for f in data.files]
    file_rows = (
        (
            await db.execute(
                select(CandidateFile).where(
                    CandidateFile.id.in_(file_ids),
                    CandidateFile.tenant_id == tenant_id,
                    CandidateFile.file_type == "resume",
                )
            )
        )
        .scalars()
        .all()
    )
    files_by_id = {f.id: f for f in file_rows}

    stage_id = await _first_non_terminal_stage_id(db, tenant_id, vacancy_id)

    created: list[dict] = []
    linked: list[dict] = []
    skipped: list[dict] = []
    # HRP-181 REDO: within-batch email dedup. Without this two files in
    # the same import that resolve to the same address would both pass the
    # DB-side ``find_active_candidate_by_email`` check (the first insert
    # isn't visible to the second's SELECT until flush), then collide on
    # ``ux_candidates_tenant_email_active`` at commit time and roll back
    # the entire batch.
    batch_emails_seen: dict[str, uuid.UUID] = {}

    for item in data.files:
        cf = files_by_id.get(item.file_id)
        if cf is None:
            skipped.append({"file_id": str(item.file_id), "reason": "file_not_found"})
            continue

        # HRP-181 REDO Stage 5: refuse files whose parse hasn't reached a
        # terminal state. Without this guard a still-pending file lands as
        # ``Candidate(full_name=<filename>, email=None)`` — email-dedup
        # never triggers because email is None, and there's no path to
        # backfill once the parser eventually completes.
        if cf.parse_status != "completed":
            skipped.append(
                {
                    "file_id": str(item.file_id),
                    "reason": "parse_not_completed",
                    "parse_status": cf.parse_status,
                }
            )
            continue

        candidate: Candidate | None = None
        was_linked = False

        if item.link_candidate_id is not None:
            candidate = await _load_canonical_candidate(
                db, tenant_id, item.link_candidate_id
            )
            if candidate.archived_at is not None:
                skipped.append(
                    {
                        "file_id": str(item.file_id),
                        "reason": "candidate_archived",
                        "existing_candidate_id": str(candidate.id),
                    }
                )
                continue
            was_linked = True
            # Move the parsed file under the linked candidate so the card
            # surfaces it in ``candidate_files``.
            cf.candidate_id = candidate.id
        else:
            parsed = cf.parsed_data or {}
            email = None
            phone = None
            full_name = None
            if isinstance(parsed, dict):
                contacts = (
                    parsed.get("contacts") if isinstance(parsed, dict) else None
                ) or {}
                email = contacts.get("email") if isinstance(contacts, dict) else None
                phone = contacts.get("phone") if isinstance(contacts, dict) else None
                fn = parsed.get("first_name") or ""
                ln = parsed.get("last_name") or ""
                full_name = (
                    f"{fn} {ln}".strip()
                    or parsed.get("full_name")
                    or cf.original_filename
                )
            else:
                full_name = cf.original_filename

            if email:
                lowered_email = email.lower()
                batched_prior = batch_emails_seen.get(lowered_email)
                if batched_prior is not None:
                    skipped.append(
                        {
                            "file_id": str(item.file_id),
                            "reason": "duplicate_email",
                            "existing_candidate_id": str(batched_prior),
                            "email": email,
                        }
                    )
                    continue
                existing = await find_active_candidate_by_email(db, tenant_id, email)
                if existing is not None:
                    skipped.append(
                        {
                            "file_id": str(item.file_id),
                            "reason": "duplicate_email",
                            "existing_candidate_id": str(existing.id),
                            "email": email,
                        }
                    )
                    continue

            denorm = _denorm_from_parsed(parsed if isinstance(parsed, dict) else None)

            candidate = Candidate(
                tenant_id=tenant_id,
                person_id=None,
                full_name=full_name or "Unnamed candidate",
                email=email,
                phone=phone,
                parsed_resume_jsonb=parsed if isinstance(parsed, dict) else None,
                **denorm,
            )
            db.add(candidate)
            await db.flush()
            cf.candidate_id = candidate.id
            if email:
                batch_emails_seen[email.lower()] = candidate.id

        # Attach to the vacancy (idempotent — skip a second attempt at
        # the same pair so re-running the import doesn't double up).
        already = (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.candidate_id == candidate.id,
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if already is None:
            cv = CandidateVacancy(
                tenant_id=tenant_id,
                candidate_id=candidate.id,
                vacancy_id=vacancy_id,
                stage_id=stage_id,
                status="new",
                status_history=[],
                attached_by=user_id,
            )
            db.add(cv)
            await db.flush()
        else:
            cv = already

        summary = {
            "file_id": str(item.file_id),
            "candidate_id": str(candidate.id),
            "candidate_vacancy_id": str(cv.id),
            "full_name": candidate.full_name,
        }
        if was_linked:
            linked.append(summary)
        else:
            created.append(summary)

    await db.commit()

    return {"created": created, "linked": linked, "skipped": skipped}


async def list_vacancy_candidates_enriched(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Enriched candidate list for the vacancy table (FR-09).

    Default sort puts terminal stages at the bottom (``stage_type !=
    'active'``) and orders the rest by ``manager_score DESC`` (NULLs
    last, then ``added_at DESC`` as a tiebreaker). NULLs end up below
    real scores so unscored applications don't pin themselves to the
    top of the funnel.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    count_query = select(func.count(CandidateVacancy.id)).where(
        CandidateVacancy.vacancy_id == vacancy_id,
        CandidateVacancy.tenant_id == tenant_id,
    )
    total = (await db.execute(count_query)).scalar() or 0

    # HRP-181 REDO Sweep A3: sort INSIDE the SQL query so OFFSET/LIMIT
    # paginates the spec-required order ("terminal stages at bottom,
    # manager_score DESC, added_at DESC") instead of paging through an
    # undefined natural order and re-sorting the page in Python.
    from sqlalchemy import case as sa_case
    from sqlalchemy import nulls_last
    from sqlalchemy.orm import aliased

    StageAlias = aliased(VacancyStage)
    is_terminal_expr = sa_case(
        (
            or_(
                StageAlias.id.is_(None),
                StageAlias.stage_type == "active",
            ),
            0,
        ),
        else_=1,
    )

    rows_q = (
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate),
            selectinload(CandidateVacancy.stage),
        )
        .outerjoin(StageAlias, CandidateVacancy.stage_id == StageAlias.id)
        .where(
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
        .order_by(
            is_terminal_expr.asc(),
            nulls_last(CandidateVacancy.manager_score.desc()),
            CandidateVacancy.added_at.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    cvs = (await db.execute(rows_q)).scalars().unique().all()
    items = [_candidate_vacancy_enriched_dict(cv) for cv in cvs]
    # HRP-663: mark the internal candidates on this page in one lookup.
    employee_person_ids = await _employee_person_ids(
        db, tenant_id, [cv.candidate.person_id if cv.candidate else None for cv in cvs]
    )
    for cv, item in zip(cvs, items, strict=True):
        item["is_employee"] = (
            cv.candidate is not None and cv.candidate.person_id in employee_person_ids
        )
    # Single Compact-matrix call powers the per-row % match aggregates
    # + Divergence column shown in the candidates table (HRP-267).
    await apply_matrix_aggregates(db, tenant_id, vacancy_id, items)
    await apply_manager_score_rounds(db, tenant_id, items)
    # HRP-493: AI DATA / AI VERDICT read the inputs the model can see
    # and whether a run is in flight — both derived, never a stale
    # mirror column.
    from app.modules.recruitment.resume_analysis_service import (
        apply_ai_analysis_state,
    )

    await apply_ai_analysis_state(db, tenant_id, items)
    return items, total


async def patch_candidate_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: CandidateVacancyPatch,
    *,
    if_match: str | None = None,
) -> dict:
    """Apply a stage / status / manager_score change with optimistic
    locking.

    ``If-Match`` is required when supplied — a mismatch returns 412 with
    the same shape vacancy PATCH uses (HRP-177). Terminal-stage moves
    are allowed; the UI confirms with the recruiter beforehand.
    """
    cv = (
        await db.execute(
            select(CandidateVacancy)
            .options(
                selectinload(CandidateVacancy.candidate),
                selectinload(CandidateVacancy.vacancy),
                selectinload(CandidateVacancy.stage),
            )
            .where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    current_etag = candidate_vacancy_etag(cv)
    if if_match is not None and if_match != current_etag:
        raise AppError(
            "candidate_vacancy_modified_concurrently",
            status.HTTP_412_PRECONDITION_FAILED,
        )

    updates = data.model_dump(exclude_unset=True)
    comment = updates.pop("comment", None)

    new_stage_id = updates.pop("stage_id", None)
    if new_stage_id is not None and new_stage_id != cv.stage_id:
        # Validate the target stage exists and belongs to the same tenant /
        # vacancy effective list.
        applicable = await _get_applicable_stages(db, tenant_id, cv.vacancy_id)
        target = next((s for s in applicable if s.id == new_stage_id), None)
        if target is None:
            raise AppError("stage_not_found_for_vacancy", status.HTTP_404_NOT_FOUND)

        old_stage_id = cv.stage_id
        history = list(cv.status_history or [])
        history.append(
            {
                "from_stage_id": str(old_stage_id) if old_stage_id else None,
                "to_stage_id": str(new_stage_id),
                "changed_at": datetime.now(timezone.utc).isoformat(),
                "comment": comment,
            }
        )
        cv.status_history = history
        cv.stage_id = new_stage_id
        cv.stage = target

    if "status" in updates and updates["status"] is not None:
        cv.status = updates["status"]
    if "manager_score" in updates:
        cv.manager_score = updates["manager_score"]
        cv.manager_score_updated_at = datetime.now(timezone.utc)

    cv.version = cv.version + 1
    await db.commit()
    await db.refresh(cv, ["candidate", "vacancy", "stage"])

    payload = _candidate_vacancy_enriched_dict(cv)
    # HRP-663: the table swaps the row in place from this body, so the
    # internal-candidate marker has to survive the PATCH.
    payload["is_employee"] = await _check_is_employee(
        db, tenant_id, cv.candidate.person_id if cv.candidate else None
    )
    # HRP-662: the aggregates have to be recomputed on every PATCH, not
    # only on ``manager_score``. The table swaps the row in place from
    # this body, and ``_candidate_vacancy_enriched_dict`` cannot derive
    # them — so skipping the call on a stage move answered with
    # ``score_divergence: false`` / ``divergence_count: 0`` and silently
    # erased the divergence highlight until the next reload.
    # ``only_cv_ids`` keeps the kanban path off the whole-vacancy grid
    # (the "unnecessary load on a hot kanban path" the HRP-267 wave-review
    # guard used to prevent): one row in, one row's matrix out.
    await apply_matrix_aggregates(
        db, tenant_id, cv.vacancy_id, [payload], only_cv_ids=[cv.id]
    )
    await apply_manager_score_rounds(db, tenant_id, [payload])
    # HRP-493: keep the PATCH response's AI block consistent with the
    # list endpoint — the table swaps the row in place from this body.
    from app.modules.recruitment.resume_analysis_service import (
        apply_ai_analysis_state,
    )

    await apply_ai_analysis_state(db, tenant_id, [payload])
    payload["etag"] = candidate_vacancy_etag(cv)
    return payload


async def delete_candidate_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> None:
    """HRP-181 REDO: remove the candidate from this vacancy's funnel.

    The canonical Candidate row stays so other vacancies can keep
    referring to it. Only the ``candidate_vacancies`` link is dropped.
    """
    cv = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(cv)
    await db.commit()


async def get_candidate_full_card(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    scope_filter: ColumnElement[bool] | None = None,
) -> dict:
    """Return the canonical candidate card payload.

    Includes the canonical fields, every ``CandidateVacancy`` the
    candidate is attached to (with vacancy title + stage), and the list
    of files (resumes + interview media) so the card has everything in
    one round-trip.
    """
    candidate = await _load_canonical_candidate(db, tenant_id, candidate_id)

    cv_query = (
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.vacancy),
            selectinload(CandidateVacancy.stage),
        )
        .where(
            CandidateVacancy.candidate_id == candidate_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    # HRP-629: same reason as list_candidate_vacancies — applications to
    # other divisions' vacancies stay hidden.
    if scope_filter is not None:
        cv_query = cv_query.join(
            Vacancy, Vacancy.id == CandidateVacancy.vacancy_id
        ).where(scope_filter)
    cv_rows = (
        (await db.execute(cv_query.order_by(CandidateVacancy.added_at.desc())))
        .scalars()
        .unique()
        .all()
    )

    from app.modules.recruitment.manager_assessment_service import (
        resolve_score_rounds,
        round_ref,
    )

    score_rounds = await resolve_score_rounds(
        db, tenant_id, [cv.id for cv in cv_rows if cv.manager_score is not None]
    )
    applications: list[dict] = []
    for cv in cv_rows:
        applications.append(
            {
                "cv_id": cv.id,
                "vacancy_id": cv.vacancy_id,
                "vacancy_title": cv.vacancy.title if cv.vacancy else None,
                "stage_id": cv.stage_id,
                "stage_name": cv.stage.name if cv.stage else None,
                "stage_type": cv.stage.stage_type if cv.stage else None,
                "status": cv.status,
                "manager_score": cv.manager_score,
                # HRP-727: which round that score came from.
                "manager_score_round": round_ref(score_rounds.get(cv.id)),
                "ai_score": cv.ai_score,
                "ai_verdict": cv.ai_verdict,
                "ai_verdict_summary": cv.ai_verdict_summary,
                # HRP-204: mode of the active analysis run so the
                # candidate-card chips render the sub-badge.
                "ai_analysis_mode": cv.ai_analysis_mode,
                "ai_data_completeness": cv.ai_data_completeness,
                "added_at": cv.added_at,
            }
        )

    files_summary = [
        {
            "id": cf.id,
            "file_type": cf.file_type,
            "original_filename": cf.original_filename,
            "mime_type": cf.mime_type,
            "file_size": cf.file_size,
            "parse_status": cf.parse_status,
            "created_at": cf.created_at,
        }
        for cf in (candidate.files or [])
    ]

    # HRP-663: the card is where a recruiter decides — it has to say the
    # person in front of them already works here.
    payload = _candidate_canonical_to_read(
        candidate,
        is_employee=await _check_is_employee(db, tenant_id, candidate.person_id),
    )
    payload["vacancy_applications"] = applications
    payload["candidate_files"] = files_summary
    payload["etag"] = candidate_etag(candidate)
    return payload


async def patch_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    data: CandidateCanonicalPatch,
    *,
    if_match: str | None = None,
) -> dict:
    """Inline-edit canonical Candidate fields with optimistic locking.

    Only canonical denormalised fields and ``parsed_resume_jsonb`` are
    writable here; the AI block on the related CandidateVacancy rows
    stays internal (parser/verdict generator only).
    """
    # HRP-181 REDO Sweep S3: acquire a row-level lock so two concurrent
    # PATCHes on the same Candidate serialise — without the lock both
    # requests load the same ``updated_at``, both pass the If-Match
    # precondition, both commit, and the second silently clobbers the
    # first instead of returning 412.
    candidate = await _load_canonical_candidate(
        db, tenant_id, candidate_id, for_update=True
    )
    if candidate.archived_at is not None:
        raise AppError(
            "candidate_archived_read_only",
            status.HTTP_409_CONFLICT,
        )

    current_etag = candidate_etag(candidate)
    if if_match is not None and if_match != current_etag:
        raise AppError(
            "candidate_modified_concurrently",
            status.HTTP_412_PRECONDITION_FAILED,
        )

    updates = data.model_dump(exclude_unset=True)
    if "full_name" in updates:
        if updates["full_name"] is None:
            raise AppError(
                "candidate_full_name_required",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        updates["full_name"] = updates["full_name"].strip()
        if not updates["full_name"]:
            raise AppError(
                "candidate_full_name_required",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    for field, value in updates.items():
        setattr(candidate, field, value)

    # HRP-181 REDO Sweep S6: re-derive denormalised columns whenever the
    # recruiter edits ``parsed_resume_jsonb``. Without this the table
    # 'Last position' / 'Years exp.' / location / linkedin columns keep
    # the finalize-time values forever, even after the resume is fixed.
    if "parsed_resume_jsonb" in updates:
        derived = _denorm_from_parsed(updates["parsed_resume_jsonb"])
        for field, value in derived.items():
            # Don't trample an explicit override sent in the same PATCH.
            if field not in updates:
                setattr(candidate, field, value)

    await db.commit()
    # ``updated_at`` carries an ``onupdate=now()`` server default, so it
    # gets expired after commit and needs an explicit reload before the
    # ETag stamp reads off it.
    await db.refresh(candidate, ["files", "updated_at"])

    # HRP-663: the card merges this body into the state it already shows,
    # so an omitted flag reads as "not an employee" and drops the badge.
    payload = _candidate_canonical_to_read(
        candidate,
        is_employee=await _check_is_employee(db, tenant_id, candidate.person_id),
    )
    payload["etag"] = candidate_etag(candidate)
    return payload


async def archive_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> None:
    """Soft-delete by stamping ``archived_at`` (FR-04 "delete row").

    CandidateVacancy rows are intentionally not cascaded — the funnel
    still needs to render the history. The partial unique index on
    ``(tenant_id, lower(email))`` ignores archived rows so the same
    address can be re-imported.
    """
    candidate = await _load_canonical_candidate(db, tenant_id, candidate_id)
    if candidate.archived_at is not None:
        return  # idempotent
    candidate.archived_at = datetime.now(timezone.utc)
    await db.commit()


# ---------------------------------------------------------------------------
# HRP-181 REDO Stage 3 — bulk resume upload + batch LLM parsing
# ---------------------------------------------------------------------------


# Bulk upload caps — product spec (UI / Upload): up to 50
# files per batch, 10 MB each, 100 MB total. The Celery parser runs one
# LLM call per file (~30 s end-to-end); 50 keeps a recruiter's queue
# under ~25 min wall-clock while still matching the spec. The total
# cap guards against a single batch saturating the worker queue.
MAX_BULK_RESUME_FILES = 50

MAX_RESUME_BYTES = settings.recruitment_max_resume_mb * 1024 * 1024

MAX_BULK_TOTAL_BYTES = settings.recruitment_max_bulk_total_mb * 1024 * 1024

ALLOWED_RESUME_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Magic byte prefixes — the modal forwards the browser's Content-Type which
# can lie (.txt renamed to .pdf). Sniffing the leading bytes blocks the
# parser from chewing garbage and surfacing a confusing failure.
_PDF_MAGIC = b"%PDF-"

_DOCX_MAGIC = b"PK\x03\x04"

# Window the detached-files poll considers "recent" — anything older is
# treated as belonging to an abandoned batch (cleanup beat job will delete
# it in 7 days, but we hide it from the modal immediately).
_DETACHED_FILES_RECENT_HOURS = 24


def _sniff_resume_bytes(mime_type: str, payload: bytes) -> bool:
    if mime_type == "application/pdf":
        return payload[: len(_PDF_MAGIC)] == _PDF_MAGIC
    if (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return payload[: len(_DOCX_MAGIC)] == _DOCX_MAGIC
    return False


def _candidate_file_to_upload_ack(cf: CandidateFile) -> dict:
    return {
        "file_id": cf.id,
        "original_filename": cf.original_filename,
        "mime_type": cf.mime_type,
        "file_size": cf.file_size,
        "parse_status": cf.parse_status,
    }


async def bulk_upload_resumes(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    files: list[UploadFile],
) -> list[dict]:
    """Store up to ``MAX_BULK_RESUME_FILES`` resumes detached from any
    candidate and queue the Celery parser for each.

    Returns one ack dict per accepted file; raises on the first failed
    validation so the modal can show the precise reason. ``finalize_
    candidates_from_parsed`` later flips each ``CandidateFile.candidate_id``
    to the real (created or linked) row when the user clicks "Import".
    """
    from app.core.s3 import upload_file
    from app.modules.recruitment.tasks import parse_resume_task

    await _get_vacancy(db, tenant_id, vacancy_id)

    if not files:
        raise AppError("resume_file_required", status.HTTP_400_BAD_REQUEST)
    if len(files) > MAX_BULK_RESUME_FILES:
        raise AppError(
            "resume_bulk_limit_exceeded",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            max_files=MAX_BULK_RESUME_FILES,
        )

    prepared: list[tuple[UploadFile, bytes, str, str]] = []
    total_bytes = 0
    for upload in files:
        content_type = upload.content_type or "application/octet-stream"
        if content_type not in ALLOWED_RESUME_MIMES:
            raise AppError(
                "unsupported_resume_type",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                content_type=content_type,
            )
        data = await upload.read()
        if len(data) > MAX_RESUME_BYTES:
            raise AppError(
                "resume_too_large",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                max_mb=MAX_RESUME_BYTES // (1024 * 1024),
            )
        total_bytes += len(data)
        if total_bytes > MAX_BULK_TOTAL_BYTES:
            raise AppError(
                "resume_batch_too_large",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                max_mb=MAX_BULK_TOTAL_BYTES // (1024 * 1024),
            )
        if not _sniff_resume_bytes(content_type, data):
            raise AppError(
                "resume_mime_mismatch",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        original_filename = upload.filename or "resume"
        prepared.append((upload, data, content_type, original_filename))

    created: list[CandidateFile] = []
    for _upload, data, content_type, original_filename in prepared:
        ext = ""
        if "." in original_filename:
            ext = original_filename.rsplit(".", 1)[-1].lower()
        file_uuid = uuid.uuid4()
        s3_path = (
            f"{tenant_id}/resumes/{file_uuid}.{ext}"
            if ext
            else f"{tenant_id}/resumes/{file_uuid}"
        )
        # Best-effort S3 upload — ``upload_file`` logs and returns None on
        # any storage error instead of raising; the parse task then fails
        # this file with an explicit storage error (HRP-691 — a silent
        # failure here used to surface as an unexplained "no files
        # recognized" in the bulk-import modal).
        upload_file(data, s3_path, content_type)

        file_record = File(
            tenant_id=tenant_id,
            name=f"{file_uuid}.{ext}" if ext else str(file_uuid),
            original_name=original_filename,
            path=s3_path,
            size=len(data),
            mime_type=content_type,
            uploaded_by=user_id,
            entity_type="resume",
            entity_id=None,
        )
        db.add(file_record)
        await db.flush()

        cf = CandidateFile(
            tenant_id=tenant_id,
            candidate_id=None,
            file_id=file_record.id,
            file_type="resume",
            original_filename=original_filename,
            mime_type=content_type,
            file_size=len(data),
            parse_status="pending",
        )
        db.add(cf)
        await db.flush()
        created.append(cf)

    await db.commit()
    # ``.delay`` is sync — fine to call straight from an async path since
    # Celery just enqueues over Redis without blocking. Guard each enqueue
    # so a transient broker outage on file N doesn't strand files N+1.. in
    # ``parse_status='pending'`` with no queued job: log + continue, the
    # parsing-status poll will surface ``pending`` and the operator can
    # retrigger via the cleanup task.
    for cf in created:
        try:
            parse_resume_task.delay(str(cf.id), str(tenant_id))
        except Exception:  # noqa: BLE001 — broker hiccup is recoverable
            logger.exception(
                "Failed to enqueue parse_resume_task for file %s (tenant %s)",
                cf.id,
                tenant_id,
            )
    return [_candidate_file_to_upload_ack(cf) for cf in created]


async def get_resumes_parsing_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    file_ids: list[uuid.UUID] | None,
) -> dict:
    """Aggregate parsing status for the bulk-upload modal poll.

    When ``file_ids`` is empty/None, returns the user's own detached
    resume rows (``candidate_id IS NULL``) from the last 24 h. Scoping by
    ``File.uploaded_by`` prevents another recruiter's in-flight batch on
    a *different* vacancy from leaking into this vacancy's poll response.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    query = select(CandidateFile).where(
        CandidateFile.tenant_id == tenant_id,
        CandidateFile.file_type == "resume",
    )
    if file_ids:
        query = query.where(CandidateFile.id.in_(file_ids))
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=_DETACHED_FILES_RECENT_HOURS
        )
        query = query.join(File, File.id == CandidateFile.file_id).where(
            CandidateFile.candidate_id.is_(None),
            CandidateFile.created_at >= cutoff,
            File.uploaded_by == user_id,
        )

    rows = (await db.execute(query)).scalars().all()
    counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
    items: list[dict] = []
    for cf in rows:
        counts[cf.parse_status] = counts.get(cf.parse_status, 0) + 1
        parsed = cf.parsed_data if isinstance(cf.parsed_data, dict) else {}
        first_name = parsed.get("first_name") or ""
        last_name = parsed.get("last_name") or ""
        full_name = (f"{first_name} {last_name}".strip()) or None
        contacts = parsed.get("contacts") if isinstance(parsed, dict) else None
        email = contacts.get("email") if isinstance(contacts, dict) else None
        error = parsed.get("error") if cf.parse_status == "failed" else None
        items.append(
            {
                "file_id": cf.id,
                "parse_status": cf.parse_status,
                "original_filename": cf.original_filename,
                "full_name": full_name,
                "email": email,
                "last_position": _last_position_from_parsed(parsed),
                "error": error,
            }
        )
    return {"counts": counts, "files": items}


async def get_resumes_dedup_preview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    file_ids: list[uuid.UUID],
) -> list[dict]:
    """Per-file duplicate-detect verdict for the import-summary chip.

    Looks the parsed email up against the tenant's active candidates only
    (archived twins are intentionally ignored, mirroring the partial
    unique index ``ux_candidates_tenant_email_active``).

    HRP-181 REDO Sweep S1: emails are dedup-checked with a single batched
    SELECT ... IN instead of one round-trip per file.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    if not file_ids:
        return []

    rows = (
        (
            await db.execute(
                select(CandidateFile).where(
                    CandidateFile.id.in_(file_ids),
                    CandidateFile.tenant_id == tenant_id,
                    CandidateFile.file_type == "resume",
                )
            )
        )
        .scalars()
        .all()
    )

    file_emails: list[tuple[CandidateFile, str | None]] = []
    lowered_emails: set[str] = set()
    for cf in rows:
        parsed = cf.parsed_data if isinstance(cf.parsed_data, dict) else {}
        contacts = parsed.get("contacts") if isinstance(parsed, dict) else None
        email = contacts.get("email") if isinstance(contacts, dict) else None
        file_emails.append((cf, email))
        if email:
            lowered_emails.add(email.lower())

    matches_by_email: dict[str, Candidate] = {}
    if lowered_emails:
        match_rows = (
            (
                await db.execute(
                    select(Candidate).where(
                        Candidate.tenant_id == tenant_id,
                        func.lower(Candidate.email).in_(lowered_emails),
                        Candidate.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for cand in match_rows:
            if cand.email:
                matches_by_email[cand.email.lower()] = cand

    out: list[dict] = []
    for cf, email in file_emails:
        match = matches_by_email.get(email.lower()) if email else None
        out.append(
            {
                "file_id": cf.id,
                "parsed_email": email,
                "existing_candidate_id": match.id if match else None,
                "existing_candidate_full_name": (match.full_name if match else None),
            }
        )
    return out
