"""HRP-275 — a cache-hit analysis must fill the compact matrix.

QA on prod: on a demo tenant, Analyze toasted "AI analysis started" and
the matrix stayed `--` on every competence. The killswitch and the seed
were both keying `competence_id` correctly; the regression was in the
cache-hit writer, which validated cached ids against the tenant's
`competences` dictionary. `AIAssessment.competence_id` is not a
Competence FK — both the real path and the matrix derive it from the
vacancy profile slug (`uuid5(COMPETENCE_NS, slug)`), an id that can
never appear in that table. So every cached assessment was dropped while
the interview was still marked completed.

The gap that let it ship: no test ran seed-shaped cache rows through
`apply_cached_analysis` into `get_assessment_matrix` — the existing
cache tests hand-built payloads keyed on real Competence rows.
"""

from __future__ import annotations

import uuid

import pytest
from app.models import Person
from app.modules.company.models import Tenant
from app.modules.recruitment import assessment_service
from app.modules.recruitment.analysis_cache_service import apply_cached_analysis
from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.models import (
    AIAssessment,
    Candidate,
    CandidateVacancy,
    Interview,
    InterviewAnalysisCache,
    Vacancy,
    VacancyProfile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SLUGS = ("python-advanced", "distributed-systems", "postgres-advanced")


async def _setup(db: AsyncSession) -> tuple[Tenant, Vacancy, Interview]:
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Matrix {suffix}", slug=f"matrix-{suffix}", is_demo=True)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    vacancy = Vacancy(tenant_id=tenant.id, title="Senior Backend", language="en")
    db.add(vacancy)
    await db.commit()
    await db.refresh(vacancy)

    # Profile competences carry slugs, exactly as the demo seed writes them.
    db.add(
        VacancyProfile(
            tenant_id=tenant.id,
            vacancy_id=vacancy.id,
            profile_data={
                "competences": [
                    {"id": slug, "name": slug.replace("-", " ").title()}
                    for slug in _SLUGS
                ]
            },
            version=1,
        )
    )
    person = Person(
        email=f"matrix.{suffix}@example.com", first_name="Elena", last_name="Volkov"
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)

    candidate = Candidate(
        tenant_id=tenant.id,
        person_id=person.id,
        full_name="Elena Volkov",
        email=person.email,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    cv = CandidateVacancy(
        tenant_id=tenant.id, vacancy_id=vacancy.id, candidate_id=candidate.id
    )
    db.add(cv)
    await db.commit()
    await db.refresh(cv)

    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        transcript="Deterministic transcript.",
        transcription_status="completed",
        analysis_status="pending",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return tenant, vacancy, interview


def _cache_row(tenant_id: uuid.UUID) -> InterviewAnalysisCache:
    return InterviewAnalysisCache(
        tenant_id=tenant_id,
        cache_key=f"seeded-{uuid.uuid4().hex}"[:64],
        analysis_data={"verdict_summary": "Strong hire", "competence_assessments": []},
        assessments=[
            {
                "competence_id": str(normalize_competence_id(slug)),
                "score": 0.8,
                "status": "assessed",
                "citations": [{"quote": f"evidence for {slug}", "verdict": "strong"}],
                "reasoning": f"reasoning for {slug}",
            }
            for slug in _SLUGS
        ],
    )


@pytest.mark.asyncio
async def test_cached_profile_slug_assessments_are_written(db: AsyncSession) -> None:
    tenant, _vacancy, interview = await _setup(db)
    cached = _cache_row(tenant.id)
    db.add(cached)
    await db.commit()
    await db.refresh(cached)

    await apply_cached_analysis(db, tenant.id, interview, cached)
    await db.commit()

    rows = (
        (
            await db.execute(
                select(AIAssessment).where(AIAssessment.interview_id == interview.id)
            )
        )
        .scalars()
        .all()
    )
    assert {str(r.competence_id) for r in rows} == {
        str(normalize_competence_id(slug)) for slug in _SLUGS
    }
    # Citations survive the copy — the demo's headline feature (HRP-250).
    assert all(r.citations for r in rows)


@pytest.mark.asyncio
async def test_matrix_reads_the_cached_assessments_as_ready(
    db: AsyncSession,
) -> None:
    tenant, vacancy, interview = await _setup(db)
    cached = _cache_row(tenant.id)
    db.add(cached)
    await db.commit()
    await db.refresh(cached)

    await apply_cached_analysis(db, tenant.id, interview, cached)
    await db.commit()

    matrix = await assessment_service.get_assessment_matrix(db, tenant.id, vacancy.id)
    cells = matrix["candidates"][0]["cells"]
    assert {cell["ai_status"] for cell in cells} == {"ready"}
    assert all(cell["ai_score"] is not None for cell in cells)


@pytest.mark.asyncio
async def test_ids_outside_profile_and_dictionary_are_still_dropped(
    db: AsyncSession,
) -> None:
    """The HRP-276 / L4 cross-tenant guard must survive the widening."""
    tenant, _vacancy, interview = await _setup(db)
    cached = _cache_row(tenant.id)
    cached.assessments = cached.assessments + [
        {
            "competence_id": str(uuid.uuid4()),
            "score": 0.9,
            "status": "assessed",
            "citations": [],
            "reasoning": "stranger",
        }
    ]
    db.add(cached)
    await db.commit()
    await db.refresh(cached)

    await apply_cached_analysis(db, tenant.id, interview, cached)
    await db.commit()

    rows = (
        (
            await db.execute(
                select(AIAssessment).where(AIAssessment.interview_id == interview.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == len(_SLUGS)
