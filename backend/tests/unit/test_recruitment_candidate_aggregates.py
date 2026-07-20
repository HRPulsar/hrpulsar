"""HRP-267: %M / %AI / divergence_count on the enriched candidates list."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import service, settings_service
from app.modules.recruitment.models import AIAssessment, Interview
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from app.modules.recruitment.settings_schemas import (
    MatrixSettingsUpdate,
    ScaleConfigCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def matrix_scale(db: AsyncSession, tenant):
    return await settings_service.create_scale(
        db,
        tenant.id,
        ScaleConfigCreate(name="matrix-1-5", min_value=0, max_value=5),
    )


_COMPETENCE_SEED = [
    {"id": "python-skills", "name": "Python", "group": "Hard"},
    {"id": "communication", "name": "Communication", "group": "Soft"},
    {"id": "system-design", "name": "System Design", "group": "Hard"},
    {"id": "leadership", "name": "Leadership", "group": "Soft"},
]


async def _setup(db: AsyncSession, tenant, user, candidates: int = 1):
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    await service.save_profile(
        db,
        tenant.id,
        uuid.UUID(str(vacancy["id"])),
        VacancyProfileUpdate(profile_data={"competences": _COMPETENCE_SEED}),
    )
    cv_links: list[dict] = []
    for i in range(candidates):
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name=f"First{i}",
                last_name=f"Last{i}",
                email=f"c{i}-{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vacancy["id"])),
            ),
        )
        cv_links.append(cv)
    return vacancy, cv_links


class TestApplyMatrixAggregates:
    async def test_enriched_endpoint_carries_percent_and_divergence(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        vacancy, cvs = await _setup(db, tenant, user, candidates=1)
        cv = cvs[0]

        # Manager: 5/4 on first two competences (rest unscored).
        for slug, score in [("python-skills", 5.0), ("communication", 4.0)]:
            await service.record_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                user.id,
                AssessmentScoreCreate(
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                ),
            )
        # AI: 5 on python-skills (matches), 2 on communication
        # (|4-2|=2 >= tenant default 1.0 → divergent).
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)
        for slug, score in [("python-skills", 5.0), ("communication", 2.0)]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status="assessed",
                    citations=[],
                )
            )
        await db.commit()

        items, total = await service.list_vacancy_candidates_enriched(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
        assert total == 1
        row = items[0]
        # (5+4) / (5 * 4) * 100 = 45%
        assert row["manager_percent"] == 45.0
        # (5+2) / (5 * 4) * 100 = 35%
        assert row["ai_percent"] == 35.0
        assert row["divergence_count"] == 1
        assert len(row["divergence_top"]) == 1
        top = row["divergence_top"][0]
        assert top["competence_name"] == "Communication"
        assert top["manager_score"] == 4.0
        assert top["ai_score"] == 2.0

    async def test_tenant_threshold_drives_divergence_count(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        vacancy, cvs = await _setup(db, tenant, user, candidates=1)
        cv = cvs[0]
        # Manager 5 / AI 3 — gap of 2.0.
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(
                competence_id=service.normalize_competence_id("python-skills"),
                score=5.0,
            ),
        )
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=interview.id,
                competence_id=service.normalize_competence_id("python-skills"),
                score=3.0,
                status="assessed",
                citations=[],
            )
        )
        await db.commit()

        # Default threshold 1.0 → 1 divergent.
        items, _ = await service.list_vacancy_candidates_enriched(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
        assert items[0]["divergence_count"] == 1
        # Raise threshold to 2.5 → gap of 2.0 no longer counts.
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=2.5)
        )
        items2, _ = await service.list_vacancy_candidates_enriched(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
        assert items2[0]["divergence_count"] == 0
        assert items2[0]["divergence_top"] == []

    async def test_apply_aggregates_skips_unknown_payloads(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Defence-in-depth: a stale payload whose cv is not on this
        vacancy stays at its schema defaults instead of crashing."""
        vacancy, cvs = await _setup(db, tenant, user, candidates=1)
        ghost = {
            "id": uuid.uuid4(),
            "manager_percent": None,
            "ai_percent": None,
            "divergence_count": 0,
            "divergence_top": [],
        }
        await service.apply_matrix_aggregates(
            db,
            tenant.id,
            uuid.UUID(str(vacancy["id"])),
            [ghost],
        )
        assert ghost["manager_percent"] is None
        assert ghost["divergence_count"] == 0
