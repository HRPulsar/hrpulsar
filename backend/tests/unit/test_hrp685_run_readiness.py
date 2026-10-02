"""HRP-685 (REDO) — a full run made without a resume is not "full".

The full analysis prompt takes the parsed resume as an *optional* input,
so a candidate interviewed without one still gets a real full run. Two
surfaces then called it "full" anyway: the chip on the candidate card's
AI Insights block (rendered off ``mode``) and the sub-badge in the
vacancy's candidates table (rendered off the ``ai_analysis_mode``
mirror), while the tooltip next to it — already derived — said
"transcript only". Every API consumer now receives the derived value:
each run carries ``readiness`` computed through ``_derive_readiness``,
the same seam the candidates table and the XLSX report use.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.modules.recruitment import resume_analysis_service, service
from app.modules.recruitment.models import AIAnalysisRun, Candidate, Interview
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _run(mode: str, *, stamp_resume: bool) -> AIAnalysisRun:
    """An in-memory run row — the serializer needs no database."""
    now = datetime.now(UTC)
    return AIAnalysisRun(
        id=uuid.uuid4(),
        candidate_vacancy_id=uuid.uuid4(),
        mode=mode,
        status="completed",
        interview_id=uuid.uuid4() if mode == "full" else None,
        analysis_data={},
        resume_snapshot_hash="abc" if stamp_resume else None,
        created_at=now,
        updated_at=now,
    )


class TestSerializedRunReadiness:
    def test_full_run_without_any_resume_is_transcript_only(self) -> None:
        read = resume_analysis_service.serialize_run_for_read(
            _run("full", stamp_resume=False), candidate_has_resume=False
        )
        assert read.mode == "full"
        assert read.readiness == "transcript_only"

    def test_full_run_that_stamped_a_resume_is_full(self) -> None:
        read = resume_analysis_service.serialize_run_for_read(
            _run("full", stamp_resume=True), candidate_has_resume=False
        )
        assert read.readiness == "resume_and_transcript"

    def test_legacy_full_run_trusts_the_resume_on_file(self) -> None:
        """Rows from before the snapshot stamp have no hash; the resume
        the candidate has today decides, exactly as it does in the table."""
        read = resume_analysis_service.serialize_run_for_read(
            _run("full", stamp_resume=False), candidate_has_resume=True
        )
        assert read.readiness == "resume_and_transcript"

    def test_a_run_that_recorded_no_resume_stays_transcript_only(self) -> None:
        """Review 01.10: a resume uploaded after the run must not rewrite
        the run's basis - the presence on file stands in only for rows
        from before the run recorded it."""
        run = _run("full", stamp_resume=False)
        run.analysis_data = {"had_resume": False}
        read = resume_analysis_service.serialize_run_for_read(
            run, candidate_has_resume=True
        )
        assert read.readiness == "transcript_only"

    def test_resume_only_run_is_resume_only(self) -> None:
        read = resume_analysis_service.serialize_run_for_read(
            _run("resume_only", stamp_resume=False), candidate_has_resume=False
        )
        assert read.readiness == "resume_only"


async def _seed_no_resume_full_run(db: AsyncSession, tenant, user) -> dict:
    """Candidate added by hand (no resume), interviewed, fully analysed."""
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"HRP-685 {uuid.uuid4().hex[:4]}")
    )
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="No",
            last_name="Resume",
            email=f"noresume-{uuid.uuid4().hex[:6]}@x.test",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=vacancy["id"]),
    )
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv["id"],
        interviewer_id=user.id,
        transcription_status="completed",
        analysis_status="completed",
        transcript="hello",
    )
    db.add(interview)
    await db.flush()
    db.add(
        AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv["id"],
            mode="full",
            status="completed",
            interview_id=interview.id,
            verdict="needs_check",
            analysis_data={"mode": "full"},
        )
    )
    await db.commit()
    return {"cv_id": cv["id"], "candidate_id": cand["id"]}


class TestCandidateCardPayload:
    async def test_card_and_table_agree_on_transcript_only(
        self, db: AsyncSession, tenant, user, auth_client
    ):
        """The reporter's case: no resume, transcript, full run."""
        seeded = await _seed_no_resume_full_run(db, tenant, user)

        res = await auth_client.get(
            f"/api/recruitment/candidate-vacancies/{seeded['cv_id']}/ai-analyses"
        )
        assert res.status_code == 200, res.text
        (run,) = res.json()
        assert run["mode"] == "full"
        assert run["readiness"] == "transcript_only"

        items = [
            {
                "id": seeded["cv_id"],
                "candidate_id": seeded["candidate_id"],
                "ai_readiness": "none",
            }
        ]
        await resume_analysis_service.apply_ai_analysis_state(db, tenant.id, items)
        assert items[0]["ai_readiness"] == run["readiness"]

    async def test_manually_entered_resume_counts(
        self, db: AsyncSession, tenant, user, auth_client
    ):
        """The HRP-704 union: a resume typed in leaves no file behind."""
        seeded = await _seed_no_resume_full_run(db, tenant, user)
        candidate = await db.get(Candidate, seeded["candidate_id"])
        candidate.parsed_resume_jsonb = {"summary": "typed in by the recruiter"}
        await db.commit()

        res = await auth_client.get(
            f"/api/recruitment/candidate-vacancies/{seeded['cv_id']}/ai-analyses"
        )
        assert res.status_code == 200, res.text
        assert res.json()[0]["readiness"] == "resume_and_transcript"

    async def test_foreign_pair_has_no_resume(self, db: AsyncSession, tenant):
        assert (
            await resume_analysis_service.candidate_has_resume_for_cv(
                db, tenant.id, uuid.uuid4()
            )
            is False
        )
