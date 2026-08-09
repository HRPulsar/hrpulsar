"""HRP-205: per-candidate question sets — unit tests.

Covers:

* generate(mode=initial)  — output shape + 8..15 question window
* generate(mode=regenerated) — preserves manual / from_competency_indicator
* generate(mode=dynamic_next) — does not repeat covered questions, turns
  blind spots into from_blind_spot
* anti-bias: prompt never contains human manager scores
* sample mode is free + does not persist
* cross-tenant fetch returns 404
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import question_service, service
from app.modules.recruitment.models import (
    AIAssessment,
    CandidateFile,
    HumanAssessment,
    Interview,
    Question,
    QuestionSet,
    VacancyProfile,
)
from app.modules.recruitment.prompts_interview import (
    GeneratedQuestion,
    GeneratedQuestionSet,
    ResumeAnchor,
    build_question_set_prompt,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    GenerateQuestionSetRequest,
    QuestionCreate2,
    QuestionUpdate2,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _gen_questions(n: int = 10) -> GeneratedQuestionSet:
    return GeneratedQuestionSet(
        questions=[
            GeneratedQuestion(
                text=f"Tell me about decision {i} from your CV.",
                goal="verify_skill",
                priority=(
                    "must_ask" if i < 3 else "should_ask" if i < 7 else "nice_to_ask"
                ),
                competence_name="Senior Python skills",
                resume_anchor=ResumeAnchor(
                    quote=f"Led migration in 202{i}",
                    section="experience",
                ),
                expected_answer_indicators=[
                    "Specific decision",
                    "Trade-offs articulated",
                ],
                follow_ups=["What would you do differently?"],
                rationale="Anchors the resume claim in a concrete moment.",
                source="ai_generated",
            )
            for i in range(n)
        ],
        coverage_note="All competences covered.",
    )


async def _make_vacancy(db: AsyncSession, tenant, user, title: str = "BE") -> dict:
    return await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=title)
    )


async def _make_candidate(db: AsyncSession, tenant, user) -> dict:
    return await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"F{uuid.uuid4().hex[:4]}",
            last_name=f"L{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )


async def _attach(db: AsyncSession, tenant, user, candidate_id, vacancy_id) -> dict:
    return await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate_id)),
            vacancy_id=uuid.UUID(str(vacancy_id)),
        ),
    )


async def _add_resume(db: AsyncSession, tenant, candidate_id, parsed: dict) -> None:
    db.add(
        CandidateFile(
            tenant_id=tenant.id,
            candidate_id=uuid.UUID(str(candidate_id)),
            file_type="resume",
            original_filename="cv.pdf",
            mime_type="application/pdf",
            file_size=1024,
            parsed_data=parsed,
            raw_text="raw",
            parse_status="completed",
        )
    )
    await db.commit()


async def _add_profile(db: AsyncSession, tenant, user, vacancy_id) -> None:
    db.add(
        VacancyProfile(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(vacancy_id)),
            language="en",
            generated_by="manual",
            profile_data={
                "competences": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Senior Python skills",
                        "criticality": "critical",
                    }
                ],
                "coverage_note": "fine",
            },
        )
    )
    await db.commit()


async def _add_interview(
    db: AsyncSession,
    tenant,
    cv_id,
    *,
    transcript: str = "Interviewer: tell me. Candidate: I led the migration.",
    transcription_status: str = "completed",
    archived_at=None,
    analysis_data: dict | None = None,
    title: str | None = "Interview 1",
) -> Interview:
    """A past round the next set can be built on (HRP-444)."""
    iv = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=uuid.UUID(str(cv_id)),
        title=title,
        status="uploaded",
        transcript=transcript,
        transcription_status=transcription_status,
        analysis_status="completed" if analysis_data else "not_started",
        analysis_data=analysis_data,
        archived_at=archived_at,
    )
    db.add(iv)
    await db.commit()
    await db.refresh(iv)
    return iv


async def _bootstrap(db: AsyncSession, tenant, user) -> dict[str, Any]:
    vac = await _make_vacancy(db, tenant, user)
    cand = await _make_candidate(db, tenant, user)
    cv = await _attach(db, tenant, user, cand["id"], vac["id"])
    await _add_resume(
        db,
        tenant,
        cand["id"],
        parsed={
            "experience": [
                {"role": "Engineer", "summary": "Led migration in 2022"},
            ],
            "skills": ["Python"],
        },
    )
    await _add_profile(db, tenant, user, vac["id"])
    return {"vacancy": vac, "candidate": cand, "cv": cv}


# ---------------------------------------------------------------------------


class TestGenerateInitial:
    async def test_creates_set_with_8_to_15_questions(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            out = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        assert out["generation_mode"] == "initial"
        assert out["status"] == "ready"
        assert 8 <= len(out["questions"]) <= 15
        q0 = out["questions"][0]
        # Every required field is populated
        for key in (
            "text",
            "goal",
            "priority",
            "rationale",
            "source",
            "expected_answer_indicators",
            "follow_ups",
        ):
            assert key in q0
        assert q0["source"] == "ai_generated"
        assert q0["resume_anchor_jsonb"]["quote"].startswith("Led migration")

    async def test_rejects_set_outside_window(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(3)
            with pytest.raises(HTTPException) as exc:
                await question_service.generate_question_set(
                    db,
                    tenant.id,
                    uuid.UUID(str(ctx["cv"]["id"])),
                    GenerateQuestionSetRequest(mode="initial"),
                    current_user_id=user.id,
                )
            assert exc.value.status_code == 502

    async def test_requires_parsed_resume(self, db: AsyncSession, tenant, user):
        vac = await _make_vacancy(db, tenant, user)
        cand = await _make_candidate(db, tenant, user)
        cv = await _attach(db, tenant, user, cand["id"], vac["id"])
        await _add_profile(db, tenant, user, vac["id"])

        with pytest.raises(HTTPException) as exc:
            await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        assert exc.value.status_code == 409


class TestRegenerate:
    async def test_preserves_manual_questions(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            first = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

        # Add a manual + a from_indicator question on top.
        manual = await question_service.add_question_to_set(
            db,
            tenant.id,
            uuid.UUID(str(first["id"])),
            QuestionCreate2(text="Manual probe", priority="must_ask", source="manual"),
            current_user_id=user.id,
        )
        indicator = await question_service.add_question_to_set(
            db,
            tenant.id,
            uuid.UUID(str(first["id"])),
            QuestionCreate2(
                text="Indicator probe",
                priority="should_ask",
                source="from_competency_indicator",
            ),
            current_user_id=user.id,
        )

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            regenerated = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(
                    mode="regenerated", target_set_id=uuid.UUID(str(first["id"]))
                ),
                current_user_id=user.id,
            )

        ids = {q["id"] for q in regenerated["questions"]}
        # Manual + indicator survived
        assert uuid.UUID(str(manual["id"])) in ids
        assert uuid.UUID(str(indicator["id"])) in ids
        # AI ones got replaced (different UUIDs)
        ai_questions = [
            q for q in regenerated["questions"] if q["source"] == "ai_generated"
        ]
        # The old AI questions are gone; new ones exist
        assert len(ai_questions) == 10
        assert regenerated["generation_mode"] == "regenerated"


class TestDynamicNext:
    async def test_does_not_repeat_covered_questions(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        # HRP-444: a next-round set is only generated off a real
        # transcript, so the round has to exist before we ask for one.
        iv = await _add_interview(db, tenant, ctx["cv"]["id"])

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            first = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

        covered_id = first["questions"][0]["id"]
        await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(covered_id)),
            QuestionUpdate2(covered=True),
            current_user_id=user.id,
        )

        captured: dict[str, Any] = {}

        async def fake_call_llm(**kw):
            captured.update(kw)
            return _gen_questions(10)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new=fake_call_llm,
        ):
            out = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(
                    mode="dynamic_next",
                    source_round_ids=[iv.id],
                    create_round=True,
                ),
                current_user_id=user.id,
            )

        # Prompt context for the LLM lists the prior question with covered=True
        prev = captured["previous_questions"]
        assert prev, "Dynamic mode must pass previous_questions to the LLM"
        flat = [q for s in prev for q in s["questions"]]
        covered = [q for q in flat if q["covered"]]
        assert covered, "Covered question must be flagged so AI avoids it"

        assert out["generation_mode"] == "dynamic_next"

    async def test_anti_bias_prompt_excludes_manager_scores(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        # Add a manager human-score row for this cv.
        db.add(
            HumanAssessment(
                tenant_id=tenant.id,
                candidate_vacancy_id=uuid.UUID(str(ctx["cv"]["id"])),
                competence_id=uuid.uuid4(),
                evaluator_id=user.id,
                evaluator_name="Boss",
                score=4.5,
                comment="strong leader",
            )
        )
        await db.commit()

        captured: dict[str, Any] = {}

        async def fake_call_llm(**kw):
            captured.update(kw)
            return _gen_questions(10)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new=fake_call_llm,
        ):
            await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

        # Build the actual prompt with the same payload and verify it
        # contains no human-score signal.
        prompt = build_question_set_prompt(
            vacancy_title=captured["vacancy"].title,
            language=captured["vacancy"].language or "en",
            profile_competences=captured["profile_competences"],
            resume_data=captured["resume_data"],
            previous_questions=captured["previous_questions"],
            transcripts=captured["transcripts"],
            blind_spots=captured["blind_spots"],
            generation_mode=captured["generation_mode"],
        )
        lower = prompt.lower()
        assert "manager score" not in lower
        assert "boss" not in lower
        assert "4.5" not in lower
        assert "strong leader" not in lower


class TestNewSetFlow:
    """HRP-444: New set is guarded, bound to a round, and context-rich."""

    async def _first_set(self, db, tenant, user, cv_id) -> dict:
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            return await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(cv_id)),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

    async def test_rejects_generation_without_a_transcribed_round(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            with pytest.raises(HTTPException) as exc:
                await question_service.generate_question_set(
                    db,
                    tenant.id,
                    uuid.UUID(str(ctx["cv"]["id"])),
                    GenerateQuestionSetRequest(mode="dynamic_next", create_round=True),
                    current_user_id=user.id,
                )
        assert exc.value.status_code == 409
        # The LLM must not be called at all — the precondition fails first.
        assert mock_llm.await_count == 0

    async def test_ignores_unfinished_and_archived_transcripts(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        processing = await _add_interview(
            db,
            tenant,
            ctx["cv"]["id"],
            transcription_status="processing",
            transcript="half a sentence",
        )
        archived = await _add_interview(
            db,
            tenant,
            ctx["cv"]["id"],
            archived_at=datetime.now(UTC),
        )
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            with pytest.raises(HTTPException) as exc:
                await question_service.generate_question_set(
                    db,
                    tenant.id,
                    uuid.UUID(str(ctx["cv"]["id"])),
                    GenerateQuestionSetRequest(
                        mode="dynamic_next",
                        source_round_ids=[processing.id, archived.id],
                        create_round=True,
                    ),
                    current_user_id=user.id,
                )
        assert exc.value.status_code == 409

    async def test_opens_the_next_round_and_binds_the_set_to_it(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment import manager_assessment_service

        ctx = await _bootstrap(db, tenant, user)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        await self._first_set(db, tenant, user, cv_id)
        iv = await _add_interview(db, tenant, cv_id)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(9)
            out = await question_service.generate_question_set(
                db,
                tenant.id,
                cv_id,
                GenerateQuestionSetRequest(
                    mode="dynamic_next",
                    source_round_ids=[iv.id],
                    create_round=True,
                    # Deliberately wrong on the wire — a transcript-based
                    # set is always a round set.
                    set_type="pre_interview",
                ),
                current_user_id=user.id,
            )

        assert out["set_type"] == "interview_round"
        assert out["assessment_round_id"] is not None
        rounds = await manager_assessment_service.list_rounds(db, tenant.id, cv_id)
        interview_rounds = [r for r in rounds if r["type"] == "interview"]
        assert len(interview_rounds) == 1
        assert interview_rounds[0]["round_number"] == 1
        assert str(interview_rounds[0]["id"]) == str(out["assessment_round_id"])

    async def test_one_set_per_round(self, db: AsyncSession, tenant, user):
        from app.modules.recruitment import manager_assessment_service
        from app.modules.recruitment.manager_assessment_schemas import RoundCreate

        ctx = await _bootstrap(db, tenant, user)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        iv = await _add_interview(db, tenant, cv_id)
        rd = await manager_assessment_service.create_round(
            db, tenant.id, user.id, cv_id, RoundCreate(type="interview")
        )

        req = GenerateQuestionSetRequest(
            mode="dynamic_next",
            source_round_ids=[iv.id],
            assessment_round_id=uuid.UUID(str(rd["id"])),
        )
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            first = await question_service.generate_question_set(
                db, tenant.id, cv_id, req, current_user_id=user.id
            )
            assert str(first["assessment_round_id"]) == str(rd["id"])

            with pytest.raises(HTTPException) as exc:
                await question_service.generate_question_set(
                    db, tenant.id, cv_id, req, current_user_id=user.id
                )
        assert exc.value.status_code == 409

    async def test_rejects_a_round_from_another_candidate_vacancy(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment import manager_assessment_service
        from app.modules.recruitment.manager_assessment_schemas import RoundCreate

        mine = await _bootstrap(db, tenant, user)
        other = await _bootstrap(db, tenant, user)
        iv = await _add_interview(db, tenant, mine["cv"]["id"])
        foreign = await manager_assessment_service.create_round(
            db,
            tenant.id,
            user.id,
            uuid.UUID(str(other["cv"]["id"])),
            RoundCreate(type="interview"),
        )

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            with pytest.raises(HTTPException) as exc:
                await question_service.generate_question_set(
                    db,
                    tenant.id,
                    uuid.UUID(str(mine["cv"]["id"])),
                    GenerateQuestionSetRequest(
                        mode="dynamic_next",
                        source_round_ids=[iv.id],
                        assessment_round_id=uuid.UUID(str(foreign["id"])),
                    ),
                    current_user_id=user.id,
                )
        assert exc.value.status_code == 404

    async def test_prompt_carries_prior_analysis_and_blind_spots(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        comp_id = str(uuid.uuid4())
        iv = await _add_interview(
            db,
            tenant,
            cv_id,
            analysis_data={
                "data_completeness": "partial",
                "competence_assessments": [
                    {
                        "competence_id": comp_id,
                        "status": "insufficient",
                        "confidence": "low",
                    }
                ],
                "blind_spots": [
                    {
                        "competence_id": comp_id,
                        "suggested_question": "How did you size the cache?",
                    }
                ],
                "red_flags": [
                    {
                        "flag_type": "inconsistency",
                        "severity": "medium",
                        "description": "Dates do not line up.",
                    }
                ],
            },
        )

        captured: dict[str, Any] = {}

        async def fake_call_llm(**kw):
            captured.update(kw)
            return _gen_questions(10)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new=fake_call_llm,
        ):
            await question_service.generate_question_set(
                db,
                tenant.id,
                cv_id,
                GenerateQuestionSetRequest(
                    mode="dynamic_next",
                    source_round_ids=[iv.id],
                    create_round=True,
                ),
                current_user_id=user.id,
            )

        assert captured["transcripts"], "transcript must reach the model"
        assert captured["blind_spots"][0]["suggested_question"]
        analyses = captured["prior_analyses"]
        assert analyses[0]["competence_assessments"][0]["status"] == "insufficient"
        assert analyses[0]["red_flags"][0]["flag_type"] == "inconsistency"

        prompt = build_question_set_prompt(
            vacancy_title=captured["vacancy"].title,
            language="en",
            profile_competences=captured["profile_competences"],
            resume_data=captured["resume_data"],
            previous_questions=captured["previous_questions"],
            transcripts=captured["transcripts"],
            blind_spots=captured["blind_spots"],
            prior_analyses=captured["prior_analyses"],
            manager_divergence=captured["manager_divergence"],
            generation_mode="dynamic_next",
        )
        # The next-round rules only appear in the mode that needs them.
        assert "NEXT-ROUND RULES" in prompt
        assert "How did you size the cache?" in prompt

    async def test_divergence_reaches_the_prompt_without_any_scores(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        comp_id = uuid.uuid4()
        iv = await _add_interview(db, tenant, cv_id)
        db.add(
            HumanAssessment(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                competence_id=comp_id,
                evaluator_id=user.id,
                evaluator_name="Boss",
                score=5.0,
                comment="outstanding leader",
            )
        )
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=iv.id,
                competence_id=comp_id,
                score=1.0,
                status="assessed",
                reasoning="thin evidence",
            )
        )
        await db.commit()

        captured: dict[str, Any] = {}

        async def fake_call_llm(**kw):
            captured.update(kw)
            return _gen_questions(10)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new=fake_call_llm,
        ):
            await question_service.generate_question_set(
                db,
                tenant.id,
                cv_id,
                GenerateQuestionSetRequest(
                    mode="dynamic_next",
                    source_round_ids=[iv.id],
                    create_round=True,
                ),
                current_user_id=user.id,
            )

        divergence = captured["manager_divergence"]
        assert divergence == [{"competence_id": str(comp_id), "disagreed": True}]

        prompt = build_question_set_prompt(
            vacancy_title=captured["vacancy"].title,
            language="en",
            profile_competences=captured["profile_competences"],
            resume_data=captured["resume_data"],
            previous_questions=captured["previous_questions"],
            transcripts=captured["transcripts"],
            blind_spots=captured["blind_spots"],
            prior_analyses=captured["prior_analyses"],
            manager_divergence=captured["manager_divergence"],
            generation_mode="dynamic_next",
        )
        lower = prompt.lower()
        # Anti-bias: the model learns THAT they disagreed, never the
        # scores, the direction, or who scored it.
        assert "boss" not in lower
        assert "outstanding leader" not in lower
        assert "5.0" not in lower
        assert "disagreed" in lower

    async def test_agreeing_scores_are_not_reported_as_divergence(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        comp_id = uuid.uuid4()
        iv = await _add_interview(db, tenant, cv_id)
        db.add(
            HumanAssessment(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                competence_id=comp_id,
                evaluator_id=user.id,
                score=4.0,
            )
        )
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=iv.id,
                competence_id=comp_id,
                score=4.0,
                status="assessed",
            )
        )
        await db.commit()

        captured: dict[str, Any] = {}

        async def fake_call_llm(**kw):
            captured.update(kw)
            return _gen_questions(10)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new=fake_call_llm,
        ):
            await question_service.generate_question_set(
                db,
                tenant.id,
                cv_id,
                GenerateQuestionSetRequest(
                    mode="dynamic_next",
                    source_round_ids=[iv.id],
                    create_round=True,
                ),
                current_user_id=user.id,
            )
        assert captured["manager_divergence"] == []


class TestSampleMode:
    async def test_sample_returns_static_set_without_persistence(
        self, db: AsyncSession, tenant, user
    ):
        sample = question_service.get_sample_question_set()
        assert sample["status"] == "sample"
        assert sample["id"] is None
        assert sample["questions"], "Sample set must contain ≥1 question"
        # No question_sets row was created
        from sqlalchemy import select

        rows = (
            (
                await db.execute(
                    select(QuestionSet).where(QuestionSet.tenant_id == tenant.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


class TestCrossTenant:
    async def test_other_tenant_cannot_read_question_set(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(8)
            first = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

        other_tenant = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await question_service.get_question_set(
                db, other_tenant, uuid.UUID(str(first["id"]))
            )
        assert exc.value.status_code == 404


class TestQuestionEditing:
    async def test_soft_delete_keeps_row(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(8)
            first = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        qid = first["questions"][0]["id"]
        await question_service.soft_delete_question(db, tenant.id, uuid.UUID(str(qid)))
        from sqlalchemy import select

        q = (
            await db.execute(select(Question).where(Question.id == uuid.UUID(str(qid))))
        ).scalar_one()
        assert q.status == "removed"

    async def test_mark_covered_stamps_timestamp(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(8)
            first = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        qid = first["questions"][0]["id"]
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(qid)),
            QuestionUpdate2(covered=True),
            current_user_id=user.id,
        )
        assert updated["covered_at"] is not None
        assert updated["covered_method"] == "manual"


class TestQuestionSetEvents:
    """HRP-205 REDO: ready/failed notification events."""

    async def test_ready_event_published_on_generate(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with (
            patch(
                "app.modules.recruitment.question_service._call_llm",
                new_callable=AsyncMock,
            ) as mock_llm,
            patch(
                "app.modules.recruitment.question_service._publish_event",
                new_callable=AsyncMock,
            ) as mock_pub,
        ):
            mock_llm.return_value = _gen_questions(9)
            out = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        events = [c.args[0] for c in mock_pub.await_args_list]
        assert "recruitment.question_set.ready" in events
        payload = mock_pub.await_args_list[-1].args[1]
        assert payload["question_set_id"] == str(out["id"])
        assert payload["requested_by"] == str(user.id)
        assert payload["link"].startswith("/recruitment/candidates/")

    async def test_failed_event_published_on_llm_error(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with (
            patch(
                "app.modules.recruitment.question_service._call_llm",
                new_callable=AsyncMock,
            ) as mock_llm,
            patch(
                "app.modules.recruitment.question_service._publish_event",
                new_callable=AsyncMock,
            ) as mock_pub,
        ):
            mock_llm.side_effect = HTTPException(502, "LLM unavailable")
            with pytest.raises(HTTPException):
                await question_service.generate_question_set(
                    db,
                    tenant.id,
                    uuid.UUID(str(ctx["cv"]["id"])),
                    GenerateQuestionSetRequest(mode="initial"),
                    current_user_id=user.id,
                )
        events = [c.args[0] for c in mock_pub.await_args_list]
        assert events == ["recruitment.question_set.failed"]


class TestAutoCoverFromAnalysis:
    """HRP-205 REDO: auto_from_transcript stamping after AI analysis."""

    async def _generated_set(self, db, tenant, user, ctx) -> dict:
        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(8)
            return await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

    async def test_marks_assessed_competences_covered(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        out = await self._generated_set(db, tenant, user, ctx)
        comp_id = uuid.UUID(str(out["questions"][0]["competence_id"]))
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))

        covered = await db.run_sync(
            lambda sync_db: question_service.auto_cover_questions_sync(
                sync_db, tenant.id, cv_id, {comp_id}
            )
        )
        assert covered == len(out["questions"])

        refreshed = await question_service.get_question_set(
            db, tenant.id, uuid.UUID(str(out["id"]))
        )
        for q in refreshed.questions:
            assert q.covered_at is not None
            assert q.covered_method == "auto_from_transcript"

    async def test_ignores_unassessed_competences(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)
        out = await self._generated_set(db, tenant, user, ctx)
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))

        covered = await db.run_sync(
            lambda sync_db: question_service.auto_cover_questions_sync(
                sync_db, tenant.id, cv_id, {uuid.uuid4()}
            )
        )
        assert covered == 0

        refreshed = await question_service.get_question_set(
            db, tenant.id, uuid.UUID(str(out["id"]))
        )
        assert all(q.covered_at is None for q in refreshed.questions)

    async def test_already_covered_not_restamped(self, db: AsyncSession, tenant, user):
        ctx = await _bootstrap(db, tenant, user)
        out = await self._generated_set(db, tenant, user, ctx)
        comp_id = uuid.UUID(str(out["questions"][0]["competence_id"]))
        cv_id = uuid.UUID(str(ctx["cv"]["id"]))
        qid = uuid.UUID(str(out["questions"][0]["id"]))
        await question_service.update_question_v2(
            db,
            tenant.id,
            qid,
            QuestionUpdate2(covered=True),
            current_user_id=user.id,
        )

        covered = await db.run_sync(
            lambda sync_db: question_service.auto_cover_questions_sync(
                sync_db, tenant.id, cv_id, {comp_id}
            )
        )
        # The manually covered question keeps its manual stamp.
        assert covered == len(out["questions"]) - 1
        refreshed = await question_service.get_question_set(
            db, tenant.id, uuid.UUID(str(out["id"]))
        )
        manual = next(q for q in refreshed.questions if q.id == qid)
        assert manual.covered_method == "manual"
