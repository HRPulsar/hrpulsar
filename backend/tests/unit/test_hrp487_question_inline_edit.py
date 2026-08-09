"""Every question attribute is editable, not just the text (HRP-487).

The inline editor PATCHes the whole question in one request, so
``QuestionUpdate2`` has to accept each field the editor exposes —
including the resume anchor, which the schema did not carry before.
``source`` stays out: it records provenance, not a user choice.
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
    QuestionUpdate2,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _question(db: AsyncSession, tenant, user) -> dict:
    vac = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="BE")
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
            profile_data={"competences": [{"id": "python", "name": "Python"}]},
        )
    )
    await db.commit()

    generated = GeneratedQuestionSet(
        questions=[
            GeneratedQuestion(
                text=f"Original question {i}?",
                goal="clarify_experience",
                priority="nice_to_ask",
                competence_name="Python",
                expected_answer_indicators=["old"],
                follow_ups=["old follow-up"],
                rationale="old rationale",
                source="ai_generated",
            )
            for i in range(8)
        ],
        coverage_note="ok",
    )
    with patch(
        "app.modules.recruitment.question_service.generate_json",
        new=AsyncMock(return_value=generated),
    ):
        created = await question_service.generate_question_set(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            GenerateQuestionSetRequest(mode="initial"),
            current_user_id=user.id,
        )
    return created["questions"][0]


class TestInlineEditCoversEveryField:
    async def test_full_patch_updates_all_attributes(
        self, db: AsyncSession, tenant, user
    ):
        q = await _question(db, tenant, user)
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(q["id"])),
            QuestionUpdate2(
                text="Rewritten question?",
                goal="probe_risk",
                priority="must_ask",
                competence_id="python",
                expected_answer_indicators=["new one", "new two"],
                follow_ups=["new follow-up"],
                rationale="new rationale",
                resume_anchor_jsonb={"quote": "Led the migration", "section": None},
            ),
            current_user_id=user.id,
        )
        assert updated["text"] == "Rewritten question?"
        assert updated["goal"] == "probe_risk"
        assert updated["priority"] == "must_ask"
        assert updated["competence_id"] == normalize_competence_id("python")
        assert updated["expected_answer_indicators"] == ["new one", "new two"]
        assert updated["follow_ups"] == ["new follow-up"]
        assert updated["rationale"] == "new rationale"
        assert updated["resume_anchor_jsonb"]["quote"] == "Led the migration"

    async def test_source_is_not_editable(self, db: AsyncSession, tenant, user):
        # Provenance is not a user choice — the schema must not expose it.
        assert "source" not in QuestionUpdate2.model_fields

    async def test_partial_patch_leaves_other_fields_alone(
        self, db: AsyncSession, tenant, user
    ):
        q = await _question(db, tenant, user)
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(q["id"])),
            QuestionUpdate2(priority="must_ask"),
            current_user_id=user.id,
        )
        assert updated["priority"] == "must_ask"
        assert updated["text"] == q["text"]
        assert updated["goal"] == q["goal"]
        assert updated["rationale"] == q["rationale"]

    async def test_clearing_the_anchor_and_lists_is_possible(
        self, db: AsyncSession, tenant, user
    ):
        q = await _question(db, tenant, user)
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(q["id"])),
            QuestionUpdate2(
                expected_answer_indicators=[],
                follow_ups=[],
                resume_anchor_jsonb=None,
            ),
            current_user_id=user.id,
        )
        assert updated["expected_answer_indicators"] == []
        assert updated["follow_ups"] == []
        assert updated["resume_anchor_jsonb"] is None

    async def test_edit_bumps_the_version(self, db: AsyncSession, tenant, user):
        q = await _question(db, tenant, user)
        updated = await question_service.update_question_v2(
            db,
            tenant.id,
            uuid.UUID(str(q["id"])),
            QuestionUpdate2(text="Bumped?"),
            current_user_id=user.id,
        )
        assert updated["version"] == q["version"] + 1
