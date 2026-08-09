"""AI score aggregation with a baseline fallback (HRP-493, task 1).

Reported symptom: a candidate analysed in FULL mode showed no AI score
at all — the candidates table printed "—" in the AI column, while a
resume-only analysis of a different candidate showed 0.23.

Root cause: the aggregate is the mean of the competences the model
scored. When an interview covers none of the profile's competences
(``status='not_covered'`` → ``score=null`` for each — the production
example had a single-competence profile the interview never touched)
the list is empty and the finalizer wrote ``NULL`` over
``candidate_vacancies.ai_score``. On a top-up that also *erased* the
number the recruiter already had from the resume-only baseline.

``aggregate_ai_score_sync`` keeps the mean whenever there is one and
otherwise carries the last completed run's aggregate forward.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.modules.recruitment import service
from app.modules.recruitment.models import AIAnalysisRun
from app.modules.recruitment.resume_analysis_service import (
    aggregate_ai_score_sync,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sync_session():
    """Celery-style sync session against the same test database.

    ``aggregate_ai_score_sync`` runs inside the worker, so it is
    exercised through the API it actually gets.
    """
    from app.config import settings

    base = settings.database_url.rsplit("/", 1)[0]
    url = (base + "/hrpulsar_test").replace("+asyncpg", "+psycopg2")
    engine = create_engine(url)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest_asyncio.fixture
async def baseline(db: AsyncSession, tenant, user):
    """A candidate-vacancy whose only completed run scored 0.23."""
    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"Aggregate {uuid.uuid4().hex[:4]}"),
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Agrippina",
            last_name="Koptsova",
            email=f"agrippina-{uuid.uuid4().hex[:6]}@x.test",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=candidate["id"], vacancy_id=vacancy["id"]
        ),
    )
    run = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv["id"],
        mode="resume_only",
        status="completed",
        verdict="not_recommended",
        ai_score=0.23,
        analysis_data={"mode": "resume_only"},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"tenant_id": tenant.id, "cv_id": cv["id"], "run_id": run.id}


class TestAggregateAiScore:
    async def test_mean_of_scored_competences(self, sync_session: Session):
        assert aggregate_ai_score_sync(
            sync_session, uuid.uuid4(), uuid.uuid4(), [0.4, 0.6]
        ) == pytest.approx(0.5)

    async def test_mean_is_clamped_to_the_canonical_unit_scale(
        self, sync_session: Session
    ):
        """Belt-and-braces: a prompt regression emitting a 0..100 scale
        must not leak 60.0 into a column the UI renders as a fraction."""
        value = aggregate_ai_score_sync(
            sync_session, uuid.uuid4(), uuid.uuid4(), [40.0, 80.0]
        )
        assert value is not None
        assert 0.0 <= value <= 1.0

    async def test_no_scores_and_no_history_stays_none(
        self, sync_session: Session
    ):
        assert (
            aggregate_ai_score_sync(sync_session, uuid.uuid4(), uuid.uuid4(), [])
            is None
        )

    async def test_no_scores_inherits_the_prior_runs_aggregate(
        self, sync_session: Session, baseline
    ):
        """The bug: a FULL analysis that scored nothing must not blank a
        score the resume-only baseline already produced."""
        assert aggregate_ai_score_sync(
            sync_session, baseline["tenant_id"], baseline["cv_id"], []
        ) == pytest.approx(0.23)

    async def test_current_run_wins_over_history(
        self, sync_session: Session, baseline
    ):
        assert aggregate_ai_score_sync(
            sync_session, baseline["tenant_id"], baseline["cv_id"], [0.9]
        ) == pytest.approx(0.9)

    async def test_excluded_run_is_not_its_own_fallback(
        self, sync_session: Session, baseline
    ):
        """A re-run of the same row must not inherit from itself — that
        would pin the first score forever."""
        assert (
            aggregate_ai_score_sync(
                sync_session,
                baseline["tenant_id"],
                baseline["cv_id"],
                [],
                exclude_run_id=baseline["run_id"],
            )
            is None
        )

    async def test_history_is_tenant_scoped(
        self, sync_session: Session, baseline
    ):
        assert (
            aggregate_ai_score_sync(
                sync_session, uuid.uuid4(), baseline["cv_id"], []
            )
            is None
        )

    async def test_lookup_does_not_mutate_history(
        self, sync_session: Session, baseline
    ):
        aggregate_ai_score_sync(
            sync_session, baseline["tenant_id"], baseline["cv_id"], []
        )
        run = sync_session.get(AIAnalysisRun, baseline["run_id"])
        assert run is not None
        assert run.ai_score == pytest.approx(0.23)
        assert run.status == "completed"
