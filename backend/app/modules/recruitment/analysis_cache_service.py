"""HRP-252 (D4): cache for AI interview-analysis results.

The cache short-circuits a re-run of ``POST /recruitment/interviews/{id}/analyze``
when the transcript, the vacancy competence profile, and the vacancy
title / language have not changed since the previous analysis. A cache
hit skips both the LLM call and the credit deduction — see
``enqueue_analyze_or_cached`` in ``interview_service.py``.

Key shape: sha256(transcript || profile.id || profile.version ||
vacancy.title || vacancy.language || candidate_vacancy.id ||
latest_parsed_resume.id).

Cache is tenant-scoped by design; demo sessions are short-lived
single-tenant sandboxes and benefit primarily from the killswitch, not
cross-session cache hits.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.models import (
    AIAssessment,
    Interview,
    InterviewAnalysisCache,
    VacancyProfile,
)

logger = logging.getLogger(__name__)


async def _profile_competence_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview: Interview,
) -> set[uuid.UUID]:
    """Competence ids of the interview's vacancy profile, in AIAssessment space.

    ``AIAssessment.competence_id`` is not a Competence FK: both the real
    analysis path and the compact matrix derive it from the vacancy
    profile entry (``uuid5(COMPETENCE_NS, slug)``). This mirrors that
    derivation so cached rows land on the same keys the matrix looks up.
    """
    if interview.candidate_vacancy_id is None:
        return set()

    from app.modules.recruitment.models import CandidateVacancy

    cv = await db.get(CandidateVacancy, interview.candidate_vacancy_id)
    if cv is None:
        return set()

    profile_data = (
        await db.execute(
            select(VacancyProfile.profile_data).where(
                VacancyProfile.vacancy_id == cv.vacancy_id,
                VacancyProfile.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()

    ids: set[uuid.UUID] = set()
    for comp in (profile_data or {}).get("competences") or []:
        comp_uuid = normalize_competence_id(comp.get("id") or comp.get("name") or "")
        if comp_uuid is not None:
            ids.add(comp_uuid)
    return ids


def compute_cache_key(
    transcript: str,
    profile_id: uuid.UUID | None,
    profile_version: int | None,
    vacancy_title: str | None = None,
    vacancy_language: str | None = None,
    candidate_vacancy_id: uuid.UUID | None = None,
    resume_file_id: uuid.UUID | None = None,
) -> str:
    """Stable hex digest for (transcript, profile, vacancy, candidate) tuple.

    ``vacancy_title`` / ``vacancy_language`` are folded in because the
    analysis prompt embeds both — editing either changes the LLM output
    even when the profile row itself is untouched, so they must
    invalidate the cache.

    ``candidate_vacancy_id`` / ``resume_file_id`` are folded in for the
    same reason: the prompt embeds the candidate's name and the parsed
    summary of their latest resume. Without them two candidates on one
    vacancy with the same transcript text (a template transcript, the
    same person re-applying) collide on one key and one candidate is
    served the other's verdict — and a re-analyze after a new resume is
    parsed keeps returning the pre-resume analysis forever (review fix).
    """
    hasher = hashlib.sha256()
    hasher.update(transcript.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(str(profile_id or "").encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(str(profile_version or 0).encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update((vacancy_title or "").encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update((vacancy_language or "").encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(str(candidate_vacancy_id or "").encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(str(resume_file_id or "").encode("utf-8"))
    return hasher.hexdigest()


async def lookup_cached_analysis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cache_key: str,
) -> InterviewAnalysisCache | None:
    result = await db.execute(
        select(InterviewAnalysisCache).where(
            InterviewAnalysisCache.tenant_id == tenant_id,
            InterviewAnalysisCache.cache_key == cache_key,
        )
    )
    return result.scalar_one_or_none()


async def apply_cached_analysis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview: Interview,
    cached: InterviewAnalysisCache,
) -> None:
    """Copy a cached analysis onto the target Interview row.

    Mirrors the writes ``analyze_interview_task`` performs after a real
    LLM call: ``interview.analysis_data`` + a fresh set of AIAssessment
    rows (any prior rows for this interview are wiped first). Bumps
    ``interview.version`` so concurrent ETag readers see a fresh
    snapshot rather than a stale ``If-Match`` match.

    HRP-276 / L4: every ``competence_id`` in the cached payload is
    re-validated before insertion, so entries written under a different
    tenant (or against a competence that has since been deleted) are
    skipped silently rather than pointing assessments at another
    tenant's row.

    HRP-275: the accepted set is the vacancy profile's competence
    namespace — ``uuid5(COMPETENCE_NS, slug)`` — because that is what
    ``analyze_interview_task`` writes and what the compact matrix reads
    back. Tenant Competence row ids stay accepted for payloads keyed on
    the competence dictionary. Validating against the dictionary alone
    dropped *every* profile-derived assessment (the demo cache-hit flow
    wrote a completed analysis with an empty matrix).
    """
    interview.analysis_data = cached.analysis_data
    interview.analysis_status = "completed"
    interview.analysis_error = None
    interview.version = (interview.version or 0) + 1

    raw_competence_ids: set[uuid.UUID] = set()
    for row in cached.assessments or []:
        comp_id = row.get("competence_id")
        if not comp_id:
            continue
        try:
            raw_competence_ids.add(uuid.UUID(str(comp_id)))
        except (TypeError, ValueError):
            continue

    valid_competence_ids: set[uuid.UUID] = set()
    if raw_competence_ids:
        valid_competence_ids = await _profile_competence_ids(db, tenant_id, interview)

        from app.modules.competence.models import Competence

        valid_competence_ids |= set(
            (
                await db.execute(
                    select(Competence.id).where(
                        Competence.tenant_id == tenant_id,
                        Competence.id.in_(raw_competence_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        dropped = raw_competence_ids - valid_competence_ids
        if dropped:
            logger.warning(
                "cached analysis: %d of %d competence ids are outside the "
                "vacancy profile and the tenant dictionary (interview %s)",
                len(dropped),
                len(raw_competence_ids),
                interview.id,
            )

    await db.execute(
        delete(AIAssessment).where(
            AIAssessment.interview_id == interview.id,
            AIAssessment.tenant_id == tenant_id,
        )
    )
    for row in cached.assessments or []:
        comp_id = row.get("competence_id")
        if not comp_id:
            continue
        try:
            comp_uuid = uuid.UUID(str(comp_id))
        except (TypeError, ValueError):
            continue
        if comp_uuid not in valid_competence_ids:
            # Cached payload references a competence outside this
            # tenant — could be a stale cache or a cross-tenant blob.
            # Skip rather than risk an FK error or a wrong row.
            continue
        db.add(
            AIAssessment(
                tenant_id=tenant_id,
                interview_id=interview.id,
                competence_id=comp_uuid,
                score=row.get("score"),
                status=row.get("status") or "ok",
                citations=row.get("citations") or [],
                reasoning=row.get("reasoning"),
            )
        )


async def _load_vacancy_cache_inputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview: Interview,
) -> (
    tuple[uuid.UUID | None, int | None, str | None, str | None, uuid.UUID | None] | None
):
    """Async load: (profile_id, profile_version, vacancy_title, vacancy_language).

    Returns ``None`` when the interview has no candidate_vacancy link,
    no vacancy, or no vacancy profile — caller must treat this as a
    signal to skip caching entirely (two different vacancies without a
    profile would otherwise collide on transcript-only).
    """
    if interview.candidate_vacancy_id is None:
        return None
    from app.modules.recruitment.models import CandidateFile, CandidateVacancy, Vacancy

    cv = await db.get(CandidateVacancy, interview.candidate_vacancy_id)
    if cv is None:
        return None

    vacancy = await db.get(Vacancy, cv.vacancy_id)
    vacancy_title = getattr(vacancy, "title", None) if vacancy else None
    vacancy_language = getattr(vacancy, "language", None) if vacancy else None

    # Same "latest parsed resume" pick as the analysis task's prompt build.
    resume_file_id = (
        await db.execute(
            select(CandidateFile.id)
            .where(
                CandidateFile.candidate_id == cv.candidate_id,
                CandidateFile.parse_status == "completed",
            )
            .order_by(CandidateFile.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    result = await db.execute(
        select(VacancyProfile.id, VacancyProfile.version).where(
            VacancyProfile.vacancy_id == cv.vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )
    row = result.first()
    if row is None:
        return None
    profile_id, profile_version = row
    return profile_id, profile_version, vacancy_title, vacancy_language, resume_file_id


def _load_vacancy_cache_inputs_sync(
    db: Session,
    tenant_id: uuid.UUID,
    interview: Interview,
) -> (
    tuple[uuid.UUID | None, int | None, str | None, str | None, uuid.UUID | None] | None
):
    """Sync twin of ``_load_vacancy_cache_inputs`` for Celery."""
    if interview.candidate_vacancy_id is None:
        return None
    from app.modules.recruitment.models import CandidateFile, CandidateVacancy, Vacancy

    cv = db.get(CandidateVacancy, interview.candidate_vacancy_id)
    if cv is None:
        return None

    vacancy = db.get(Vacancy, cv.vacancy_id)
    vacancy_title = getattr(vacancy, "title", None) if vacancy else None
    vacancy_language = getattr(vacancy, "language", None) if vacancy else None

    # Same "latest parsed resume" pick as the analysis task's prompt build.
    resume_file_id = db.execute(
        select(CandidateFile.id)
        .where(
            CandidateFile.candidate_id == cv.candidate_id,
            CandidateFile.parse_status == "completed",
        )
        .order_by(CandidateFile.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    row = db.execute(
        select(VacancyProfile.id, VacancyProfile.version).where(
            VacancyProfile.vacancy_id == cv.vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    ).first()
    if row is None:
        return None
    profile_id, profile_version = row
    return profile_id, profile_version, vacancy_title, vacancy_language, resume_file_id


async def compute_cache_key_for_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview: Interview,
) -> str | None:
    """Build a cache key from the interview's transcript + matching profile.

    Returns None when:

    * the interview has no transcript yet, or
    * the vacancy has no ``VacancyProfile`` row (we refuse to key by
      ``profile_id=None``, which would collide across distinct vacancies
      and serve a stranger's cached analysis).
    """
    if not interview.transcript:
        return None
    inputs = await _load_vacancy_cache_inputs(db, tenant_id, interview)
    if inputs is None:
        return None
    profile_id, profile_version, vacancy_title, vacancy_language, resume_id = inputs
    return compute_cache_key(
        interview.transcript,
        profile_id,
        profile_version,
        vacancy_title=vacancy_title,
        vacancy_language=vacancy_language,
        candidate_vacancy_id=interview.candidate_vacancy_id,
        resume_file_id=resume_id,
    )


async def store_cached_analysis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cache_key: str,
    analysis_data: dict,
    assessments: list[dict[str, Any]],
) -> None:
    """Async twin of :func:`store_cached_analysis_sync`.

    Used from the demo seed (HRP-276 / L3) so the Elena interview
    lands a pre-populated cache row — a re-analyze on the same demo
    tenant becomes a cache hit and doesn't burn LLM credits.
    """
    stmt = pg_insert(InterviewAnalysisCache).values(
        tenant_id=tenant_id,
        cache_key=cache_key,
        analysis_data=analysis_data,
        assessments=assessments,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_interview_analysis_cache_key",
        set_={
            "analysis_data": stmt.excluded.analysis_data,
            "assessments": stmt.excluded.assessments,
        },
    )
    await db.execute(stmt)


def store_cached_analysis_sync(
    db: Session,
    tenant_id: uuid.UUID,
    cache_key: str,
    analysis_data: dict,
    assessments: list[dict[str, Any]],
) -> None:
    """Insert or refresh a cache row from inside a Celery task (sync ORM).

    Uses Postgres ``INSERT … ON CONFLICT (tenant_id, cache_key) DO UPDATE``
    so two concurrent identical-input analyses cannot race past a
    SELECT-then-add into an ``IntegrityError`` — which under the prior
    code would surface as ``analysis_status='failed'`` and trigger a
    Celery retry that double-bills credits.
    """
    stmt = pg_insert(InterviewAnalysisCache).values(
        tenant_id=tenant_id,
        cache_key=cache_key,
        analysis_data=analysis_data,
        assessments=assessments,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_interview_analysis_cache_key",
        set_={
            "analysis_data": stmt.excluded.analysis_data,
            "assessments": stmt.excluded.assessments,
        },
    )
    db.execute(stmt)


def compute_cache_key_for_interview_sync(
    db: Session,
    tenant_id: uuid.UUID,
    interview: Interview,
) -> str | None:
    """Sync twin of ``compute_cache_key_for_interview`` for the Celery task."""
    if not interview.transcript:
        return None
    inputs = _load_vacancy_cache_inputs_sync(db, tenant_id, interview)
    if inputs is None:
        return None
    profile_id, profile_version, vacancy_title, vacancy_language, resume_id = inputs
    return compute_cache_key(
        interview.transcript,
        profile_id,
        profile_version,
        vacancy_title=vacancy_title,
        vacancy_language=vacancy_language,
        candidate_vacancy_id=interview.candidate_vacancy_id,
        resume_file_id=resume_id,
    )
