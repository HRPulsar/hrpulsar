"""HRP-265: tenant-scoped divergence threshold + Compact matrix aggregates."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import service, settings_service
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
from app.modules.recruitment.settings_schemas import (
    MatrixSettingsUpdate,
    ScaleConfigCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def matrix_scale(db: AsyncSession, tenant):
    """1..5 scale used by the assessment-matrix tests below."""
    return await settings_service.create_scale(
        db,
        tenant.id,
        ScaleConfigCreate(name="matrix-1-5", min_value=0, max_value=5),
    )


async def _vacancy_with_competences(
    db: AsyncSession,
    tenant,
    user,
    competences: list[dict],
    n_candidates: int = 0,
) -> dict:
    """Build a vacancy with a saved profile and N attached candidates."""
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    await service.save_profile(
        db,
        tenant.id,
        uuid.UUID(str(vacancy["id"])),
        VacancyProfileUpdate(profile_data={"competences": competences}),
    )
    cv_links: list[dict] = []
    candidates: list[dict] = []
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


# ─── Tenant matrix settings ─────────────────────────────────────────


class TestMatrixSettings:
    async def test_get_returns_default_threshold(
        self, db: AsyncSession, tenant
    ) -> None:
        payload = await settings_service.get_matrix_settings(db, tenant.id)
        assert payload == {"divergence_threshold": 1.0}

    async def test_update_persists_and_round_trips(
        self, db: AsyncSession, tenant
    ) -> None:
        result = await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=2.5)
        )
        assert result == {"divergence_threshold": 2.5}
        refetched = await settings_service.get_matrix_settings(db, tenant.id)
        assert refetched == {"divergence_threshold": 2.5}

    async def test_update_partial_keeps_existing(
        self, db: AsyncSession, tenant
    ) -> None:
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=0.5)
        )
        # Send an empty body — schema with all-Optional fields → no-op.
        result = await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate()
        )
        assert result == {"divergence_threshold": 0.5}

    async def test_get_divergence_threshold_helper(
        self, db: AsyncSession, tenant
    ) -> None:
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=1.7)
        )
        assert await settings_service.get_divergence_threshold(db, tenant.id) == 1.7
        # Unknown tenant short-circuits to the historical default.
        assert await settings_service.get_divergence_threshold(db, uuid.uuid4()) == 1.0

    async def test_invalid_range_rejected_by_schema(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=-0.5)
        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=99.0)
        # threshold == 0 marks every (M, AI) cell as divergent — explicitly
        # banned by ``gt=0`` after the HRP-265 code review.
        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=0.0)

    async def test_unknown_tenant_returns_404(self, db: AsyncSession) -> None:
        with pytest.raises(HTTPException) as exc:
            await settings_service.get_matrix_settings(db, uuid.uuid4())
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            await settings_service.update_matrix_settings(
                db, uuid.uuid4(), MatrixSettingsUpdate(divergence_threshold=1.0)
            )
        assert exc.value.status_code == 404


# ─── Assessment matrix aggregates ───────────────────────────────────


_COMPETENCE_SEED = [
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
    {
        "id": "system-design",
        "name": "System Design",
        "group": "Hard",
        "criticality": "important",
    },
    {
        "id": "leadership",
        "name": "Leadership",
        "group": "Soft",
        "criticality": "desirable",
    },
]


class TestAssessmentMatrixBasic:
    async def test_empty_vacancy_returns_empty_candidates(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=0
        )
        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert result["candidates"] == []
        assert result["divergence_threshold"] == 1.0
        assert result["max_score"] == 5.0
        # Competences are still surfaced so the UI can render the header row
        assert len(result["competences"]) == len(_COMPETENCE_SEED)

    async def test_per_candidate_aggregates(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        # Manager scores: 5 / 4 on the first two competences, nothing on the
        # remaining two. Denominator stays max_score * total_competences (=20).
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

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        # (5+4) / (5*4) * 100 = 45%
        assert cand["manager_percent"] == 45.0
        assert cand["ai_percent"] is None
        assert cand["divergence_count"] == 0
        assert cand["manager_scored_competences"] == 2
        assert cand["ai_scored_competences"] == 0

    async def test_ai_not_covered_drops_out_of_denominator(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        # AI scored 3/5 on the first two competences and explicitly skipped
        # the next one. Denominator must therefore be max_score * (4 - 1) = 15.
        # HRP-507: AIAssessment.score is stored on the canonical 0..1 scale
        # (HRP-274) and rebased onto the tenant scale on read, so 0.6 → 3.
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        for slug, score, status in [
            ("python-skills", 0.6, "ready"),
            ("communication", 0.6, "ready"),
            ("system-design", None, "not_covered"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        # (3+3) / (5 * 3) * 100 = 40%, not 30% (which would use denom=20).
        assert cand["ai_percent"] == 40.0
        assert cand["ai_not_covered_competences"] == 1
        assert cand["ai_scored_competences"] == 2

    async def test_divergence_uses_tenant_threshold(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]
        python_id = service.normalize_competence_id("python-skills")

        # Manager 5 / AI 3 — gap of 2.0.
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=python_id, score=5.0),
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
                competence_id=python_id,
                # 0.6 raw → 3 on the tenant 0..5 scale (HRP-507).
                score=0.6,
                status="ready",
                citations=[],
            )
        )
        await db.commit()

        # Default threshold = 1.0 → divergence True.
        first = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert first["divergence_threshold"] == 1.0
        assert first["candidates"][0]["divergence_count"] == 1

        # Bump threshold to 2.5 → the same 2.0 gap no longer counts.
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=2.5)
        )
        second = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert second["divergence_threshold"] == 2.5
        assert second["candidates"][0]["divergence_count"] == 0

    async def test_production_ai_status_vocabulary(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Regression: the real LLM pipeline writes ``assessed`` /
        ``not_covered`` / ``insufficient`` (per CompetenceAssessment in
        prompts_interview.py), not ``ready``. The matrix must treat
        ``assessed`` as a scored cell and ``insufficient`` as dropping
        out of the AI denominator (same posture as ``not_covered``)."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
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

        # Two ``assessed`` rows + one ``insufficient`` + one ``not_covered``.
        # Denominator must collapse to max_score * scored = 5 * 2 = 10.
        # Numerator = 4 + 4 = 8. ai_percent = 80%.
        for slug, score, ai_status in [
            # 0.8 raw → 4 on the tenant 0..5 scale (HRP-507).
            ("python-skills", 0.8, "assessed"),
            ("communication", 0.8, "assessed"),
            ("system-design", None, "insufficient"),
            ("leadership", None, "not_covered"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=ai_status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["ai_percent"] == 80.0
        assert cand["ai_scored_competences"] == 2
        # ``insufficient`` + ``not_covered`` both fall into the
        # not_covered bookkeeping bucket.
        assert cand["ai_not_covered_competences"] == 2

        # Cell-level ai_status normalisation: ``assessed`` → ``ready`` so
        # the frontend renders the score; ``insufficient`` → ``not_covered``.
        cells_by_comp = {str(c["competence_id"]): c for c in cand["cells"]}
        python_cell = cells_by_comp[
            str(service.normalize_competence_id("python-skills"))
        ]
        assert python_cell["ai_status"] == "ready"
        assert python_cell["ai_score"] == 4.0
        sysd_cell = cells_by_comp[str(service.normalize_competence_id("system-design"))]
        assert sysd_cell["ai_status"] == "not_covered"

    async def test_failed_ai_status_drops_out_of_denominator(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """``status='failed'`` (or any non-ready, non-not_covered) must not
        deflate the AI %-match — the cell is treated as if AI hadn't run."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
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

        # Three scored + one failed. Denominator before fix would have
        # been 5 * 4 = 20 with numerator 3+3+3 = 9 → 45%. The fix drops
        # ``failed`` out of the denominator: 5 * 3 = 15 → 60%.
        for slug, score, ai_status in [
            # 0.6 raw → 3 on the tenant 0..5 scale (HRP-507).
            ("python-skills", 0.6, "ready"),
            ("communication", 0.6, "ready"),
            ("system-design", 0.6, "ready"),
            ("leadership", None, "failed"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=ai_status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["ai_percent"] == 60.0
        # ``failed`` is folded into the not_covered bookkeeping bucket so the
        # exposed counters stay self-consistent for the UI.
        assert cand["ai_not_covered_competences"] == 1
        assert cand["ai_scored_competences"] == 3

    async def test_cell_detail_returns_evaluator_breakdown(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]
        python_id = service.normalize_competence_id("python-skills")

        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=python_id, score=4.0, comment="solid"),
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
                competence_id=python_id,
                # 0.6 raw → 3 on the tenant 0..5 scale (HRP-507). The
                # drill-down rebases exactly like the cell it explains.
                score=0.6,
                status="ready",
                citations=[{"text": "I built async services"}],
                reasoning="confident on async",
            )
        )
        await db.commit()

        detail = await service.get_assessment_matrix_cell_detail(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            uuid.UUID(str(cv["id"])),
            python_id,
        )
        assert detail["competence_id"] == python_id
        assert len(detail["manager_entries"]) == 1
        assert detail["manager_entries"][0]["score"] == 4.0
        assert detail["manager_entries"][0]["comment"] == "solid"
        assert detail["ai_latest"]["score"] == 3.0
        assert detail["ai_latest"]["status"] == "ready"
        assert detail["ai_history"] == []


# ─── HRP-361: candidate identity in the Compact matrix ─────────────


class TestMatrixCandidateIdentity:
    async def test_name_uses_denormalised_full_name(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Resume-sourced candidates have no Person row (person_id is
        optional since HRP-181 REDO) — the matrix must fall back to the
        denormalised ``Candidate.full_name`` instead of "Unknown"."""
        from app.modules.recruitment.models import Candidate

        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cand = await db.get(Candidate, uuid.UUID(str(ctx["candidates"][0]["id"])))
        assert cand is not None
        cand.person_id = None
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert result["candidates"][0]["name"] == "First0 Last0"

    async def test_stage_name_resolved(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        from app.modules.recruitment.models import CandidateVacancy, VacancyStage

        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        stage = VacancyStage(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(ctx["vacancy"]["id"])),
            name="Interview",
            code=f"interview-{uuid.uuid4().hex[:4]}",
            sort_order=1,
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)

        cv = await db.get(CandidateVacancy, uuid.UUID(str(ctx["cv_links"][0]["id"])))
        assert cv is not None
        cv.stage_id = stage.id
        await db.commit()
        # Refresh the relationship — the shared test session's identity map
        # keeps the instance whose ``stage`` was loaded as None before the
        # FK write (production requests use a fresh session).
        await db.refresh(cv, attribute_names=["stage"])

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["stage_name"] == "Interview"
        assert cand["stage_id"] == stage.id


# ─── HRP-510: interview-round scoping + canvas export ────────────────


class TestAssessmentMatrixRounds:
    async def _two_rounds(self, db: AsyncSession, tenant, user, matrix_scale):
        """One candidate with two interviews scoring the same competence
        3.0 (first round) then 5.0 (second).

        Stored raw on the canonical 0..1 scale (HRP-507) — 0.6 and 1.0 —
        and read back rebased onto the tenant's 0..5 scale.
        """
        from datetime import datetime, timedelta, timezone

        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv_id = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        python_id = service.normalize_competence_id("python-skills")
        base = datetime(2026, 5, 1, tzinfo=timezone.utc)

        for offset_days, score in ((0, 0.6), (7, 1.0)):
            interview = Interview(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                transcription_status="completed",
                analysis_status="completed",
                created_at=base + timedelta(days=offset_days),
            )
            db.add(interview)
            await db.commit()
            await db.refresh(interview)
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=python_id,
                    score=score,
                    status="ready",
                    citations=[],
                )
            )
        await db.commit()
        return ctx

    async def test_round_count_and_latest_default(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        # Interview recordings alone build no Round slot — slots come from
        # the Manager-assessments rounds (HRP-510 REDO).
        assert result["round_slots"] == []
        assert result["round"] == "latest"
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        # Newest interview wins by default.
        assert cell["ai_score"] == 5.0

    async def test_slot_that_no_candidate_has_falls_back_to_latest(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """HRP-510 REDO — the old numeric filter meant "the n-th interview
        recording". Slots are rounds now, so a key nobody owns is not a
        request for the first recording; it is not a slot at all."""
        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="interview_1",
        )
        assert result["round"] == "latest"
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        assert cell["ai_score"] == 5.0

    async def test_all_combined_averages_across_rounds(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="all",
        )
        assert result["round"] == "all"
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        # (3 + 5) / 2
        assert cell["ai_score"] == 4.0

    async def test_unparseable_round_falls_back_to_latest(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="not-a-round",
        )
        assert result["round"] == "latest"

    async def test_archived_interview_drops_out_of_the_round_selector(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """HRP-510 REDO — every other reader of these interviews
        (``_latest_transcribed_interview``, ``_load_transcripts``,
        ``apply_ai_analysis_state``) skips archived rows. The round list
        did not, so "Latest" could resolve to a recording the recruiter
        had already thrown away."""
        from datetime import datetime, timezone

        from sqlalchemy import select

        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        cv_id = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        rows = list(
            (
                await db.execute(
                    select(Interview)
                    .where(
                        Interview.tenant_id == tenant.id,
                        Interview.candidate_vacancy_id == cv_id,
                    )
                    .order_by(Interview.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        rows[-1].archived_at = datetime.now(timezone.utc)
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        # The surviving (older) round, not the archived 5.0.
        assert cell["ai_score"] == 3.0

    async def test_canvas_xlsx_export_renders_both_sources(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        import io

        from app.modules.recruitment.report_xlsx import render_canvas_xlsx
        from openpyxl import load_workbook

        ctx = await self._two_rounds(db, tenant, user, matrix_scale)
        payload = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        wb = load_workbook(
            io.BytesIO(render_canvas_xlsx(payload, vacancy_title="Senior Backend"))
        )
        ws = wb["Canvas"]
        assert "Assessment canvas — Senior Backend" in str(
            ws.cell(row=1, column=1).value
        )
        assert ws.cell(row=4, column=1).value == "Candidate"
        # Two rows per candidate: Manager then AI.
        assert ws.cell(row=5, column=2).value == "Manager"
        assert ws.cell(row=6, column=2).value == "AI"


# ─── HRP-510 REDO: Round slots + vacancy Assessment scale ────────────


class TestAssessmentMatrixRoundSlots:
    """The Round selector lists the vacancy's Manager-assessment slots.

    A round belongs to one candidate-vacancy pair, so the filter cannot be
    a round id: "Interview 2" has to resolve to a different row for every
    candidate, and to nothing at all for a candidate who never had it.
    """

    @staticmethod
    async def _round_with_scores(
        db: AsyncSession,
        tenant,
        user,
        cv_id: uuid.UUID,
        round_type: str,
        scores: dict[str, int],
    ) -> uuid.UUID:
        from app.modules.recruitment import manager_assessment_service
        from app.modules.recruitment.manager_assessment_schemas import (
            CompetenceScoreIn,
            RoundCreate,
        )

        rnd = await manager_assessment_service.create_round(
            db, tenant.id, user.id, cv_id, RoundCreate(type=round_type)
        )
        round_id = uuid.UUID(str(rnd["id"]))
        sheet = await manager_assessment_service.get_or_create_assessment(
            db, tenant.id, round_id, evaluator_user_id=user.id
        )
        for slug, value in scores.items():
            await manager_assessment_service.set_competence_score(
                db,
                tenant.id,
                user.id,
                sheet.id,
                service.normalize_competence_id(slug),
                CompetenceScoreIn(score_value=value),
            )
        return round_id

    @staticmethod
    async def _run(
        db,
        tenant,
        cv_id: uuid.UUID,
        mode: str,
        assessments: list[dict],
        *,
        interview_id: uuid.UUID | None = None,
    ):
        from datetime import datetime, timezone

        from app.modules.recruitment.models import AIAnalysisRun
        from sqlalchemy import select as _select

        # What every finalising task does first: only one active completed
        # run per pair is allowed, older ones are archived. The archived
        # resume-only run is still the only answer the Pre-interview slot
        # has once a full top-up supersedes it.
        prior = (
            (
                await db.execute(
                    _select(AIAnalysisRun).where(
                        AIAnalysisRun.candidate_vacancy_id == cv_id,
                        AIAnalysisRun.archived_at.is_(None),
                        AIAnalysisRun.status == "completed",
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in prior:
            row.archived_at = datetime.now(timezone.utc)
        await db.flush()

        run = AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_id,
            mode=mode,
            status="completed",
            interview_id=interview_id,
            analysis_data={"mode": mode, "competence_assessments": assessments},
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run

    async def test_slots_come_from_the_candidate_with_the_most_rounds(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=2
        )
        deep = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        shallow = uuid.UUID(str(ctx["cv_links"][1]["id"]))
        await self._round_with_scores(db, tenant, user, deep, "pre_interview", {})
        for _ in range(3):
            await self._round_with_scores(db, tenant, user, deep, "interview", {})
        await self._round_with_scores(db, tenant, user, shallow, "interview", {})

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert [slot["key"] for slot in result["round_slots"]] == [
            "pre_interview",
            "interview_1",
            "interview_2",
            "interview_3",
        ]
        # No candidate reached a Final round, so the slot is not offered.
        assert all(slot["type"] != "final" for slot in result["round_slots"])

    async def test_slot_scopes_manager_cells_to_that_round(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=2
        )
        scored = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        # Interview 1 says 2, Interview 2 says 4 — the slot decides which.
        await self._round_with_scores(
            db, tenant, user, scored, "interview", {"python-skills": 2}
        )
        await self._round_with_scores(
            db, tenant, user, scored, "interview", {"python-skills": 4}
        )
        # The second candidate never got past Interview 1.
        await self._round_with_scores(
            db,
            tenant,
            user,
            uuid.UUID(str(ctx["cv_links"][1]["id"])),
            "interview",
            {"python-skills": 3},
        )

        python_id = service.normalize_competence_id("python-skills")
        first = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="interview_1",
        )
        assert first["round"] == "interview_1"
        by_cv = {c["candidate_vacancy_id"]: c for c in first["candidates"]}
        cell = next(
            c for c in by_cv[scored]["cells"] if c["competence_id"] == python_id
        )
        assert cell["manager_score"] == 2.0

        second = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="interview_2",
        )
        by_cv = {c["candidate_vacancy_id"]: c for c in second["candidates"]}
        cell = next(
            c for c in by_cv[scored]["cells"] if c["competence_id"] == python_id
        )
        assert cell["manager_score"] == 4.0
        # A candidate who never had Interview 2 reads as dashes, not as
        # their Interview 1 scores borrowed forward.
        other = by_cv[uuid.UUID(str(ctx["cv_links"][1]["id"]))]
        assert all(c["manager_score"] is None for c in other["cells"])
        assert other["manager_percent"] is None

    async def test_pre_interview_slot_takes_the_last_resume_only_run(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv_id = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        await self._round_with_scores(db, tenant, user, cv_id, "pre_interview", {})
        await self._run(
            db,
            tenant,
            cv_id,
            "resume_only",
            [{"competence_id": "python-skills", "score": 0.25, "status": "assessed"}],
        )
        # Re-run of the same mode — the newer verdict wins.
        await self._run(
            db,
            tenant,
            cv_id,
            "resume_only",
            [{"competence_id": "python-skills", "score": 0.75, "status": "assessed"}],
        )
        # A full run must not answer for the Pre-interview slot.
        await self._run(
            db,
            tenant,
            cv_id,
            "full",
            [{"competence_id": "python-skills", "score": 1.0, "status": "assessed"}],
        )

        result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="pre_interview",
        )
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        # 0.75 across the vacancy's 1..4 range: 1 + 0.75 × 3.
        assert cell["ai_score"] == 3.25

    async def test_candidate_without_the_slot_round_reads_as_dashes(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """A slot exists because *some* candidate reached that round. For
        everyone else the whole row is dashes — including the AI half: a
        resume-only run is not the Pre-interview verdict of a candidate
        who has no Pre-interview round."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=2
        )
        with_round = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        without_round = uuid.UUID(str(ctx["cv_links"][1]["id"]))
        await self._round_with_scores(db, tenant, user, with_round, "pre_interview", {})
        for cv_id in (with_round, without_round):
            await self._run(
                db,
                tenant,
                cv_id,
                "resume_only",
                [
                    {
                        "competence_id": "python-skills",
                        "score": 1.0,
                        "status": "assessed",
                    }
                ],
            )

        result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="pre_interview",
        )
        by_cv = {c["candidate_vacancy_id"]: c for c in result["candidates"]}
        assert all(
            cell["ai_score"] is None for cell in by_cv[without_round]["cells"]
        )
        assert by_cv[without_round]["ai_percent"] is None
        # The candidate who does have the round still gets their verdict.
        assert any(cell["ai_score"] == 4.0 for cell in by_cv[with_round]["cells"])

    async def test_interview_slot_needs_the_interview_linked_to_that_round(
        self, db: AsyncSession, tenant, user
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv_id = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        round_id = await self._round_with_scores(
            db, tenant, user, cv_id, "interview", {}
        )
        unlinked = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_id,
            transcription_status="completed",
        )
        db.add(unlinked)
        await db.commit()
        await db.refresh(unlinked)
        await self._run(
            db,
            tenant,
            cv_id,
            "full",
            [{"competence_id": "python-skills", "score": 1.0, "status": "assessed"}],
            interview_id=unlinked.id,
        )
        python_id = service.normalize_competence_id("python-skills")

        # The transcript is not attached to the round, so the slot has no
        # AI opinion — a dash, not the candidate's newest analysis.
        unlinked_result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="interview_1",
        )
        cell = next(
            c
            for c in unlinked_result["candidates"][0]["cells"]
            if c["competence_id"] == python_id
        )
        assert cell["ai_score"] is None
        assert cell["ai_status"] == "missing"

        unlinked.round_id = round_id
        await db.commit()
        linked_result = await service.get_assessment_matrix(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            round_filter="interview_1",
        )
        cell = next(
            c
            for c in linked_result["candidates"][0]["cells"]
            if c["competence_id"] == python_id
        )
        assert cell["ai_score"] == 4.0

    async def test_bottom_and_top_marks_agree_across_both_halves(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Review finding — the AI was rebased as ``raw × max``, which puts
        it on 0..max while manager levels sit on min..max. On "Standard
        1-4" the AI's bottom mark printed 0.0 against the manager's 1: a
        full threshold apart, so two verdicts that agree the candidate is
        at the floor of the scale were counted as a divergence."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv_id = uuid.UUID(str(ctx["cv_links"][0]["id"]))
        # Bottom of the scale on one competence, top on another.
        await self._round_with_scores(
            db,
            tenant,
            user,
            cv_id,
            "interview",
            {"python-skills": 1, "communication": 4},
        )
        await self._run(
            db,
            tenant,
            cv_id,
            "resume_only",
            [
                {"competence_id": "python-skills", "score": 0.0, "status": "assessed"},
                {"competence_id": "communication", "score": 1.0, "status": "assessed"},
            ],
        )

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        candidate = result["candidates"][0]
        cells = {str(c["competence_id"]): c for c in candidate["cells"]}
        bottom = cells[str(service.normalize_competence_id("python-skills"))]
        assert bottom["manager_score"] == 1.0
        assert bottom["ai_score"] == 1.0
        assert bottom["divergence"] is False
        top = cells[str(service.normalize_competence_id("communication"))]
        assert top["manager_score"] == 4.0
        assert top["ai_score"] == 4.0
        assert top["divergence"] is False
        assert candidate["divergence_count"] == 0

    async def test_matrix_renders_the_vacancy_assessment_scale(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """HRP-510 REDO task 2 — the Scale selector names the vacancy's
        Assessment scale, and its top level is the matrix maximum. The
        tenant ScaleConfig (0..5 here) is not what the recruiter picked
        for the vacancy, and printing a top mark as 5 on a 1-4 vacancy is
        what the tester rejected."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        await self._round_with_scores(
            db,
            tenant,
            user,
            uuid.UUID(str(ctx["cv_links"][0]["id"])),
            "interview",
            {"python-skills": 4},
        )

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert result["max_score"] == 4.0
        assert result["scale_name"] == "Standard 1-4"
        cell = next(
            c
            for c in result["candidates"][0]["cells"]
            if c["competence_id"] == service.normalize_competence_id("python-skills")
        )
        assert cell["manager_score"] == 4.0
