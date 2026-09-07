"""HRP-704: one predicate for "this candidate has a resume".

Two defects, one root: ``candidate_files`` is polymorphic and the question
loader filtered only ``parse_status``, so an audio row's ``parsed_data``
could be handed to the prompt; and "has a resume" was spelled out three
different ways, so a manually entered candidate (``parsed_resume_jsonb``
with no ``CandidateFile``) was offered Generate questions and then
answered 409 ``parsed_resume_required``.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import question_service
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    Vacancy,
    VacancyProfile,
)
from app.modules.recruitment.resume_presence import (
    candidate_ids_with_resume,
    load_parsed_resume,
)
from app.modules.recruitment.schemas import GenerateQuestionSetRequest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp205_question_sets import _gen_questions

pytestmark = pytest.mark.asyncio

RESUME_PARSED = {
    "experience": [{"role": "Engineer", "summary": "Led migration in 2022"}],
    "skills": ["Python"],
}
# What an ASR run leaves on the interview recording's row — the payload
# that used to reach the question prompt as if it were a CV.
MEDIA_PARSED = {"transcript": "Interviewer: tell me about yourself."}


async def _candidate(
    db: AsyncSession, tenant, *, mirror: dict | None = None, json_null: bool = False
) -> Candidate:
    """``json_null=True`` reproduces what the bulk-import finaliser writes
    for a candidate with nothing parsed: an explicit Python ``None``, which
    SQLAlchemy stores as JSON ``null`` rather than SQL NULL."""
    row = Candidate(
        tenant_id=tenant.id,
        full_name=f"Cand {uuid.uuid4().hex[:5]}",
        email=f"c-{uuid.uuid4().hex[:8]}@example.com",
    )
    if mirror is not None or json_null:
        row.parsed_resume_jsonb = mirror
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _file(
    db: AsyncSession,
    tenant,
    candidate: Candidate,
    file_type: str,
    parsed: dict | None,
    parse_status: str = "completed",
) -> CandidateFile:
    row = CandidateFile(
        tenant_id=tenant.id,
        candidate_id=candidate.id,
        file_type=file_type,
        original_filename=f"{file_type}.bin",
        mime_type="application/octet-stream",
        file_size=1024,
        parsed_data=parsed,
        parse_status=parse_status,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestPresencePredicate:
    async def test_manual_entry_counts_without_any_file(self, db: AsyncSession, tenant):
        """The reported desync: the table said resume_only, the POST 409'd."""
        cand = await _candidate(db, tenant, mirror=RESUME_PARSED)
        assert await candidate_ids_with_resume(db, tenant.id, [cand.id]) == {cand.id}

    async def test_a_completed_resume_file_counts_without_the_mirror(
        self, db: AsyncSession, tenant
    ):
        cand = await _candidate(db, tenant)
        await _file(db, tenant, cand, "resume", RESUME_PARSED)
        assert await candidate_ids_with_resume(db, tenant.id, [cand.id]) == {cand.id}

    async def test_an_empty_parse_is_still_a_parse(self, db: AsyncSession, tenant):
        """``is not None``, not truthiness — the report and the candidates
        table have always counted ``{}`` and must keep agreeing."""
        cand = await _candidate(db, tenant, mirror={})
        assert await candidate_ids_with_resume(db, tenant.id, [cand.id]) == {cand.id}

    async def test_media_and_unparsed_files_do_not_count(
        self, db: AsyncSession, tenant
    ):
        """A transcribed interview is not a CV, and neither is a pending parse."""
        media = await _candidate(db, tenant)
        await _file(db, tenant, media, "audio", MEDIA_PARSED)
        await _file(db, tenant, media, "video", MEDIA_PARSED)

        pending = await _candidate(db, tenant)
        await _file(db, tenant, pending, "resume", None, parse_status="pending")

        found = await candidate_ids_with_resume(db, tenant.id, [media.id, pending.id])
        assert found == set()

    async def test_a_json_null_mirror_is_not_a_resume(self, db: AsyncSession, tenant):
        """The bulk-import row with nothing parsed. It passes IS NOT NULL
        but reads back as ``None``, so SQL used to say "has a resume" while
        the API said the opposite."""
        cand = await _candidate(db, tenant, json_null=True)
        assert await candidate_ids_with_resume(db, tenant.id, [cand.id]) == set()
        assert await load_parsed_resume(db, tenant.id, cand.id) is None

    async def test_empty_input_asks_nothing(self, db: AsyncSession, tenant):
        assert await candidate_ids_with_resume(db, tenant.id, []) == set()

    async def test_another_tenant_is_not_counted(self, db: AsyncSession, tenant):
        cand = await _candidate(db, tenant, mirror=RESUME_PARSED)
        await _file(db, tenant, cand, "resume", RESUME_PARSED)
        assert await candidate_ids_with_resume(db, uuid.uuid4(), [cand.id]) == set()


class TestLoadParsedResume:
    async def test_media_parsed_data_never_reaches_the_prompt(
        self, db: AsyncSession, tenant
    ):
        """The missing ``file_type`` filter: the audio row is the most
        recent completed file, so it used to win the ORDER BY."""
        cand = await _candidate(db, tenant)
        await _file(db, tenant, cand, "audio", MEDIA_PARSED)
        await _file(db, tenant, cand, "video", MEDIA_PARSED)

        assert await load_parsed_resume(db, tenant.id, cand.id) is None

    async def test_media_loses_to_the_mirror(self, db: AsyncSession, tenant):
        """Same candidate, but manually entered: the CV is the mirror, and
        the newer audio row must not displace it."""
        cand = await _candidate(db, tenant, mirror=RESUME_PARSED)
        await _file(db, tenant, cand, "audio", MEDIA_PARSED)

        assert await load_parsed_resume(db, tenant.id, cand.id) == RESUME_PARSED

    async def test_the_resume_file_wins_over_the_mirror(self, db: AsyncSession, tenant):
        """An uploaded and parsed CV is fresher than the mirror behind it."""
        newer = {"skills": ["Rust"]}
        cand = await _candidate(db, tenant, mirror=RESUME_PARSED)
        await _file(db, tenant, cand, "resume", newer)

        assert await load_parsed_resume(db, tenant.id, cand.id) == newer

    async def test_nothing_on_file_is_none(self, db: AsyncSession, tenant):
        cand = await _candidate(db, tenant)
        assert await load_parsed_resume(db, tenant.id, cand.id) is None

    async def test_an_empty_parse_keeps_loader_and_predicate_in_step(
        self, db: AsyncSession, tenant
    ):
        """A completed resume file that parsed to {} and no mirror behind it.

        The predicate never looks at ``parsed_data``, so it says "has a
        resume". If the loader treated {} as falsy it would fall through to
        the absent mirror and return None — the UI would enable Generate and
        the POST would answer 409, which is the whole defect. Both sides must
        agree, so the loader returns the empty parse as it stands.
        """
        cand = await _candidate(db, tenant)
        await _file(db, tenant, cand, "resume", {})

        assert await candidate_ids_with_resume(db, tenant.id, [cand.id]) == {cand.id}
        assert await load_parsed_resume(db, tenant.id, cand.id) == {}


class TestGenerateQuestionsForAManuallyEnteredCandidate:
    """The end of the reported scenario: the button was enabled, the POST
    answered 409 ``parsed_resume_required``."""

    async def _cv(self, db: AsyncSession, tenant, user, cand: Candidate):
        vacancy = Vacancy(
            tenant_id=tenant.id,
            title=f"Backend {uuid.uuid4().hex[:4]}",
            owner_id=user.id,
        )
        db.add(vacancy)
        await db.commit()
        await db.refresh(vacancy)
        db.add(
            VacancyProfile(
                tenant_id=tenant.id,
                vacancy_id=vacancy.id,
                language="en",
                generated_by="manual",
                profile_data={
                    "competences": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Senior Python skills",
                            "criticality": "critical",
                        }
                    ]
                },
            )
        )
        cv = CandidateVacancy(
            tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vacancy.id
        )
        db.add(cv)
        await db.commit()
        await db.refresh(cv)
        return cv

    async def test_bulk_import_candidate_can_be_generated_for(
        self, db: AsyncSession, tenant, user
    ):
        cand = await _candidate(db, tenant, mirror=RESUME_PARSED)
        cv = await self._cv(db, tenant, user, cand)

        with patch(
            "app.modules.recruitment.question_service._call_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _gen_questions(10)
            out = await question_service.generate_question_set(
                db,
                tenant.id,
                cv.id,
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )

        assert out["status"] == "ready"
        # And the prompt was built from the CV, not from nothing.
        assert mock_llm.await_count == 1

    async def test_a_candidate_with_only_media_is_still_refused(
        self, db: AsyncSession, tenant, user
    ):
        """The other direction: unifying the predicate must not open the
        gate for a candidate who genuinely has no CV."""
        from fastapi import HTTPException

        cand = await _candidate(db, tenant)
        await _file(db, tenant, cand, "audio", MEDIA_PARSED)
        cv = await self._cv(db, tenant, user, cand)

        with pytest.raises(HTTPException) as exc:
            await question_service.generate_question_set(
                db,
                tenant.id,
                cv.id,
                GenerateQuestionSetRequest(mode="initial"),
                current_user_id=user.id,
            )
        assert exc.value.status_code == 409

    async def test_the_generation_task_accepts_an_empty_parse(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """The Celery twin of the 409: the predicate counts ``{}`` as a
        resume, so the task must not answer "No parsed resume found"."""
        from app.config import settings as app_settings
        from app.modules.recruitment.tasks import generate_questions_task

        from tests.conftest import TEST_DB_URL

        cand = await _candidate(db, tenant, mirror={})
        cv = await self._cv(db, tenant, user, cand)
        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)

        async def _no_questions(**kwargs):
            return []

        monkeypatch.setattr(
            "app.modules.recruitment.ai_service.generate_individual_questions",
            _no_questions,
        )

        # The task calls ``asyncio.run`` itself, so it cannot run on the
        # test's loop.
        out = await asyncio.to_thread(
            generate_questions_task.run,
            str(cand.id),
            str(cv.vacancy_id),
            str(tenant.id),
        )
        assert out["status"] == "completed"
