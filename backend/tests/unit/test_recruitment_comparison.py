"""Unit tests for R4a — candidate comparison endpoint."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.models import (
    AIAssessment,
    Interview,
)
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup_vacancy_with_candidates(
    db: AsyncSession, tenant, user, n_candidates: int = 3
) -> dict:
    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}"),
    )

    # Profile with two competences (slug ids).
    await service.save_profile(
        db,
        tenant.id,
        uuid.UUID(str(vacancy["id"])),
        VacancyProfileUpdate(
            profile_data={
                "competences": [
                    {
                        "id": "python-skills",
                        "name": "Python",
                        "group": "Hard",
                        "criticality": "critical",
                    },
                    {
                        "id": "communication",
                        "name": "Communication",
                        "group": "Soft",
                        "criticality": "important",
                    },
                ]
            }
        ),
    )

    candidates: list[dict] = []
    cv_links: list[dict] = []
    for i in range(n_candidates):
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
        candidates.append(cand)
        cv_links.append(cv)
    return {"vacancy": vacancy, "candidates": candidates, "cv_links": cv_links}


class TestCompareCandidatesBasic:
    async def test_returns_competence_matrix(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _setup_vacancy_with_candidates(db, tenant, user, 2)
        comp_id = normalize_competence_id("python-skills")
        # Score candidate 0 = 4.0, candidate 1 = 5.0 → divergence 1.0.
        for cv, score in zip(ctx["cv_links"], [4.0, 5.0], strict=True):
            await service.record_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                user.id,
                AssessmentScoreCreate(
                    competence_id=comp_id,
                    score=score,
                    comment="ok",
                ),
            )

        result = await service.compare_candidates(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            [uuid.UUID(str(c["id"])) for c in ctx["candidates"]],
        )
        assert len(result["candidates"]) == 2
        # Find the competence row for python-skills.
        python_row = next(
            row
            for row in result["competences"]
            if row["competence_id"] == str(comp_id)
        )
        assert python_row["divergence"] == 1.0
        score_by_cand = {
            cell["candidate_id"]: cell["score"] for cell in python_row["cells"]
        }
        cand_uuids = [uuid.UUID(str(c["id"])) for c in ctx["candidates"]]
        assert score_by_cand[cand_uuids[0]] == 4.0
        assert score_by_cand[cand_uuids[1]] == 5.0

    async def test_more_than_5_candidates_returns_400(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _setup_vacancy_with_candidates(db, tenant, user, 6)
        with pytest.raises(HTTPException) as exc:
            await service.compare_candidates(
                db,
                tenant.id,
                uuid.UUID(str(ctx["vacancy"]["id"])),
                [uuid.UUID(str(c["id"])) for c in ctx["candidates"]],
            )
        assert exc.value.status_code == 400
        assert "5" in str(exc.value.detail)

    async def test_empty_candidate_ids_returns_400(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="x")
        )
        with pytest.raises(HTTPException) as exc:
            await service.compare_candidates(
                db, tenant.id, uuid.UUID(str(vac["id"])), []
            )
        assert exc.value.status_code == 400

    async def test_unknown_vacancy_returns_404(
        self, db: AsyncSession, tenant
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await service.compare_candidates(
                db, tenant.id, uuid.uuid4(), [uuid.uuid4()]
            )
        assert exc.value.status_code == 404


class TestCompareDivergenceAndFallback:
    async def test_falls_back_to_ai_score_when_no_human_score(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _setup_vacancy_with_candidates(db, tenant, user, 2)
        comp_id = normalize_competence_id("python-skills")

        # Insert AI assessment by hand (no LLM call, no public service).
        cv = ctx["cv_links"][0]
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        ai_row = AIAssessment(
            tenant_id=tenant.id,
            interview_id=interview.id,
            competence_id=comp_id,
            score=3.5,
            status="assessed",
            citations=[],
            reasoning="auto",
        )
        db.add(ai_row)
        await db.commit()

        # Recruiter sees the AI fallback (role is one of _FULL_ROLES).
        result = await service.compare_candidates(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            [uuid.UUID(str(c["id"])) for c in ctx["candidates"]],
            role="recruiter",
        )
        python_row = next(
            row
            for row in result["competences"]
            if row["competence_id"] == str(comp_id)
        )
        cells = {
            cell["candidate_id"]: cell for cell in python_row["cells"]
        }
        first_cand_id = uuid.UUID(str(ctx["candidates"][0]["id"]))
        assert cells[first_cand_id]["score"] == 3.5
        assert cells[first_cand_id]["source"] == "ai"

    async def test_unknown_role_hides_ai_fallback(
        self, db: AsyncSession, tenant, user
    ) -> None:
        # Defence in depth: only the four full roles see AI scores.
        # role=None / unknown should mirror the hiring_manager posture
        # (matches `_role_filter_analysis`'s "None for unknown role").
        ctx = await _setup_vacancy_with_candidates(db, tenant, user, 1)
        comp_id = normalize_competence_id("python-skills")

        cv = ctx["cv_links"][0]
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
                competence_id=comp_id,
                score=4.5,
                status="assessed",
                citations=[],
                reasoning="auto",
            )
        )
        await db.commit()

        for caller_role in (None, "employee", "external"):
            result = await service.compare_candidates(
                db,
                tenant.id,
                uuid.UUID(str(ctx["vacancy"]["id"])),
                [uuid.UUID(str(ctx["candidates"][0]["id"]))],
                role=caller_role,
            )
            python_row = next(
                row
                for row in result["competences"]
                if row["competence_id"] == str(comp_id)
            )
            assert python_row["cells"][0]["score"] is None, caller_role
            assert python_row["cells"][0]["source"] == "missing"

    async def test_hiring_manager_role_hides_ai_only_scores(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _setup_vacancy_with_candidates(db, tenant, user, 1)
        comp_id = normalize_competence_id("python-skills")

        cv = ctx["cv_links"][0]
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
                competence_id=comp_id,
                score=4.5,
                status="assessed",
                citations=[],
                reasoning="auto",
            )
        )
        await db.commit()

        result = await service.compare_candidates(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            [uuid.UUID(str(ctx["candidates"][0]["id"]))],
            role="hiring_manager",
        )
        python_row = next(
            row
            for row in result["competences"]
            if row["competence_id"] == str(comp_id)
        )
        # AI fallback is suppressed for hiring_manager: cell stays missing.
        assert python_row["cells"][0]["score"] is None
        assert python_row["cells"][0]["source"] == "missing"
