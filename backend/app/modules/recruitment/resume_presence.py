"""One definition of "this candidate has a resume" (HRP-704).

``candidate_files`` is polymorphic: resumes, audio and video interview
recordings all live in it, and they all reach ``parse_status="completed"``.
So every query about "the candidate's resume" has to say
``file_type == "resume"`` — a query that only filters ``parse_status``
picks up whatever media row happens to be the most recent, and the
question-generation prompt was being handed the ``parsed_data`` of an
audio file.

The second half is that a resume does not have to be a file at all.
Manual entry and the bulk-import finaliser write ``Candidate.
parsed_resume_jsonb`` and leave no ``CandidateFile`` behind, so presence
is the *union* of the two. Three places used to spell that out
separately — the report, the candidates table and the frontend gate —
and they disagreed: the table showed ``resume_only`` and enabled
Generate questions, then the POST answered 409
``parsed_resume_required``.

Both halves live here so a fourth caller cannot invent a fourth answer.
Sync twins exist for the Celery tasks, same shape as
``analysis_language``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.recruitment.models import Candidate, CandidateFile

__all__ = [
    "candidate_ids_with_resume",
    "candidate_ids_with_resume_sync",
    "load_parsed_resume",
    "load_parsed_resume_sync",
]


def _tenant_uuid(tenant_id: uuid.UUID | str) -> uuid.UUID:
    """The Celery tasks carry the tenant id as a string."""
    return tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))


def _presence_stmts(
    tenant_id: uuid.UUID | str, candidate_ids: list[uuid.UUID]
) -> tuple[Select[tuple[uuid.UUID | None]], Select[tuple[uuid.UUID]]]:
    """The two halves of the union, as statements.

    Kept separate rather than a SQL ``UNION`` so both the async and the
    sync twin stay a plain pair of bounded ``IN`` lookups.
    """
    tenant = _tenant_uuid(tenant_id)
    return (
        select(CandidateFile.candidate_id).where(
            CandidateFile.tenant_id == tenant,
            CandidateFile.candidate_id.in_(candidate_ids),
            CandidateFile.file_type == "resume",
            CandidateFile.parse_status == "completed",
        ),
        # ``is_not(None)``, not truthiness: an empty parse ({}) is still a
        # parse, and the report and the candidates table both count it.
        #
        # The ``jsonb_typeof`` clause is the other half. SQLAlchemy's JSON
        # types store a Python ``None`` as JSON ``null``, not SQL NULL, so
        # the bulk-import finaliser writing
        # ``parsed_resume_jsonb=parsed if isinstance(parsed, dict) else None``
        # (candidate_service) leaves a row that passes ``IS NOT NULL`` while
        # holding no resume at all. Reading it back yields Python ``None``,
        # so the API and the frontend called it "no resume" while every SQL
        # predicate called it "has one" — the same class of disagreement
        # this module exists to end.
        select(Candidate.id).where(
            Candidate.tenant_id == tenant,
            Candidate.id.in_(candidate_ids),
            Candidate.parsed_resume_jsonb.is_not(None),
            func.jsonb_typeof(Candidate.parsed_resume_jsonb) != "null",
        ),
    )


async def candidate_ids_with_resume(
    db: AsyncSession,
    tenant_id: uuid.UUID | str,
    candidate_ids: Iterable[uuid.UUID],
) -> set[uuid.UUID]:
    """Which of ``candidate_ids`` have a resume on file, by either route."""
    ids = [cid for cid in candidate_ids if cid is not None]
    if not ids:
        return set()
    files_stmt, mirror_stmt = _presence_stmts(tenant_id, ids)
    rows = list((await db.execute(files_stmt)).scalars().all())
    rows += list((await db.execute(mirror_stmt)).scalars().all())
    return {cid for cid in rows if cid is not None}


def candidate_ids_with_resume_sync(
    db: Session,
    tenant_id: uuid.UUID | str,
    candidate_ids: Iterable[uuid.UUID],
) -> set[uuid.UUID]:
    """Sync twin for the Celery tasks."""
    ids = [cid for cid in candidate_ids if cid is not None]
    if not ids:
        return set()
    files_stmt, mirror_stmt = _presence_stmts(tenant_id, ids)
    rows = list(db.execute(files_stmt).scalars().all())
    rows += list(db.execute(mirror_stmt).scalars().all())
    return {cid for cid in rows if cid is not None}


def _latest_resume_stmt(
    tenant_id: uuid.UUID | str, candidate_id: uuid.UUID
) -> Select[tuple[Any]]:
    # Secondary ``id DESC`` tiebreaker for the same reason as
    # ``resume_analysis_service._latest_parsed_resume``: two rows can land
    # with identical ``created_at`` (bulk import, seeded fixtures), and
    # without it Postgres returns whichever row it happens to reach first.
    return (
        select(CandidateFile.parsed_data)
        .where(
            CandidateFile.tenant_id == _tenant_uuid(tenant_id),
            CandidateFile.candidate_id == candidate_id,
            CandidateFile.file_type == "resume",
            CandidateFile.parse_status == "completed",
        )
        .order_by(CandidateFile.created_at.desc(), CandidateFile.id.desc())
        .limit(1)
    )


def _mirror_stmt(
    tenant_id: uuid.UUID | str, candidate_id: uuid.UUID
) -> Select[tuple[Any]]:
    return select(Candidate.parsed_resume_jsonb).where(
        Candidate.tenant_id == _tenant_uuid(tenant_id),
        Candidate.id == candidate_id,
    )


async def load_parsed_resume(
    db: AsyncSession,
    tenant_id: uuid.UUID | str,
    candidate_id: uuid.UUID,
) -> dict | None:
    """The candidate's parsed resume for an AI prompt, or None.

    Latest completed resume *file* first, then the canonical mirror — the
    same union the presence predicate uses, so a candidate the UI shows as
    having a resume can always be generated for.

    ``is not None``, not truthiness: an empty parse ({}) counts as a parse
    for the presence predicate, which never looks at ``parsed_data`` at
    all. Falling through to the mirror on {} would put the two back out of
    step — the UI would enable Generate and the POST would answer 409,
    which is the exact defect this module was written to end.
    """
    parsed = (
        await db.execute(_latest_resume_stmt(tenant_id, candidate_id))
    ).scalar_one_or_none()
    if parsed is not None:
        return parsed
    return (
        await db.execute(_mirror_stmt(tenant_id, candidate_id))
    ).scalar_one_or_none()


def load_parsed_resume_sync(
    db: Session,
    tenant_id: uuid.UUID | str,
    candidate_id: uuid.UUID,
) -> dict | None:
    """Sync twin for the Celery tasks."""
    parsed = db.execute(
        _latest_resume_stmt(tenant_id, candidate_id)
    ).scalar_one_or_none()
    if parsed is not None:
        return parsed
    return db.execute(_mirror_stmt(tenant_id, candidate_id)).scalar_one_or_none()
