"""A question keeps its link to the vacancy-profile competence (HRP-503).

The link has to survive all three creation paths: AI generation, the
manual "Add custom question" form, and "Add from competency indicator".
AI-authored profiles identify competences by kebab-case slug while
curated ones use a UUID, so both forms must fold onto the same stable id
(``normalize_competence_id``) — otherwise the same competence would be
addressed by two different keys and auto-cover would silently miss.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import question_service, service
from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.models import CandidateFile, VacancyProfile
from app.modules.recruitment.prompts_interview import (
    GeneratedQuestion,
    GeneratedQuestionSet,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    GenerateQuestionSetRequest,
    QuestionCreate2,
    QuestionUpdate2,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

COMPETENCE_SLUG = "senior-python-skills"
COMPETENCE_NAME = "Senior Python skills"


async def _bootstrap(db: AsyncSession, tenant, user) -> dict:
    """Candidate-vacancy with a slug-keyed AI-style profile."""
    vac = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="Backend engineer")
    )
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Ada",
            last_name=f"L{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(cand["id"])),
            vacancy_id=uuid.UUID(str(vac["id"])),
        ),
    )
    db.add(
        CandidateFile(
            tenant_id=tenant.id,
            candidate_id=uuid.UUID(str(cand["id"])),
            file_type="resume",
            original_filename="cv.pdf",
            mime_type="application/pdf",
            file_size=10,
            parsed_data={"skills": ["Python"]},
            raw_text="raw",
            parse_status="completed",
        )
    )
    db.add(
        VacancyProfile(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(vac["id"])),
            language="en",
            generated_by="ai",
            profile_data={
                "competences": [
                    {
                        # AI profiles emit slugs, not UUIDs.
                        "id": COMPETENCE_SLUG,
                        "name": COMPETENCE_NAME,
                        "criticality": "critical",
                        "why_important": "Owns the service",
                        "indicators": ["Ships without regressions"],
                        "questions": [{"text": "Describe a migration."}],
                    }
                ]
            },
        )
    )
    await db.commit()
    return {"vacancy": vac, "candidate": cand, "cv": cv}


def _generated(n: int = 8) -> GeneratedQuestionSet:
    return GeneratedQuestionSet(
        questions=[
            GeneratedQuestion(
                text=f"Question {i} about the migration you led.",
                goal="verify_skill",
                priority="should_ask",
                competence_name=COMPETENCE_NAME,
                expected_answer_indicators=["Specifics"],
                follow_ups=["And then?"],
                rationale="Checks the claim.",
                source="ai_generated",
            )
            for i in range(n)
        ],
        coverage_note="ok",
    )


class TestGenerationLinksCompetence:
    async def test_generated_questions_carry_the_profile_competence(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service.generate_json",
            new=AsyncMock(return_value=_generated()),
        ):
            result = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        expected = normalize_competence_id(COMPETENCE_SLUG)
        assert result["questions"]
        for q in result["questions"]:
            assert q["competence_id"] == expected

    async def test_unknown_competence_name_leaves_the_link_empty(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        payload = _generated()
        for q in payload.questions:
            q.competence_name = "Something not in the profile"
        with patch(
            "app.modules.recruitment.question_service.generate_json",
            new=AsyncMock(return_value=payload),
        ):
            result = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        assert all(q["competence_id"] is None for q in result["questions"])


class TestManualAddLinksCompetence:
    async def _set_id(self, db, tenant, user, ctx) -> uuid.UUID:
        with patch(
            "app.modules.recruitment.question_service.generate_json",
            new=AsyncMock(return_value=_generated()),
        ):
            created = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        return uuid.UUID(str(created["id"]))

    async def test_slug_is_folded_onto_the_same_id_generation_uses(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        set_id = await self._set_id(db, tenant, user, ctx)
        added = await question_service.add_question_to_set(
            db,
            tenant.id,
            set_id,
            QuestionCreate2(
                text="Walk me through the rollout plan.",
                competence_id=COMPETENCE_SLUG,
                source="from_competency_indicator",
            ),
            current_user_id=user.id,
        )
        assert added["competence_id"] == normalize_competence_id(COMPETENCE_SLUG)

    async def test_uuid_competence_id_is_preserved(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        set_id = await self._set_id(db, tenant, user, ctx)
        explicit = uuid.uuid4()
        added = await question_service.add_question_to_set(
            db,
            tenant.id,
            set_id,
            QuestionCreate2(
                text="Walk me through the rollout plan.",
                competence_id=str(explicit),
                source="from_competency_indicator",
            ),
            current_user_id=user.id,
        )
        assert added["competence_id"] == explicit

    async def test_custom_question_may_stay_unlinked(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        set_id = await self._set_id(db, tenant, user, ctx)
        added = await question_service.add_question_to_set(
            db,
            tenant.id,
            set_id,
            QuestionCreate2(text="A free-form probe question.", source="manual"),
            current_user_id=user.id,
        )
        assert added["competence_id"] is None
        assert added["source"] == "manual"

    async def test_indicator_mapping_is_persisted(self, db: AsyncSession, tenant, user):
        # Mirrors what AddFromCompetencyDialog posts: first question text,
        # remaining questions as follow-ups, indicators and why_important.
        ctx = await _bootstrap(db, tenant, user)
        set_id = await self._set_id(db, tenant, user, ctx)
        added = await question_service.add_question_to_set(
            db,
            tenant.id,
            set_id,
            QuestionCreate2(
                text="Describe a migration.",
                priority="must_ask",
                goal="verify_skill",
                competence_id=COMPETENCE_SLUG,
                expected_answer_indicators=["Ships without regressions"],
                follow_ups=["What broke?"],
                rationale="Owns the service",
                source="from_competency_indicator",
            ),
            current_user_id=user.id,
        )
        assert added["priority"] == "must_ask"
        assert added["goal"] == "verify_skill"
        assert added["expected_answer_indicators"] == ["Ships without regressions"]
        assert added["follow_ups"] == ["What broke?"]
        assert added["rationale"] == "Owns the service"
        assert added["competence_id"] == normalize_competence_id(COMPETENCE_SLUG)


class TestEditKeepsTheLink:
    async def test_competence_can_be_relinked_by_slug(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _bootstrap(db, tenant, user)
        with patch(
            "app.modules.recruitment.question_service.generate_json",
            new=AsyncMock(return_value=_generated()),
        ):
            created = await question_service.generate_question_set(
                db,
                tenant.id,
                uuid.UUID(str(ctx["cv"]["id"])),
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        qid = uuid.UUID(str(created["questions"][0]["id"]))
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            qid,
            QuestionUpdate2(competence_id="another-competence"),
            current_user_id=user.id,
        )
        assert updated["competence_id"] == normalize_competence_id("another-competence")
