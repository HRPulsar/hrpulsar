"""AI Insights staleness + AI-state derivation (HRP-489, HRP-492, HRP-493).

Three groups:

* ``evaluate_analysis_staleness`` — the four signals the AI Insights
  banners key on (resume changed, competency profile re-edited, run
  older than the window, a transcript newer than a full analysis).
* ``evaluate_topup_eligibility`` — an edited resume must also close the
  cheap +20-cr upgrade, not just raise a banner (HRP-489 case 3: the
  "Upgrade to full for 20 credits" path must no longer be offered).
* ``apply_ai_analysis_state`` — AI DATA follows the inputs the model can
  see, and AI VERDICT knows when a run is in flight.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.modules.recruitment import resume_analysis_service, service
from app.modules.recruitment.models import (
    AIAnalysisRun,
    CandidateFile,
    CandidateVacancy,
    Interview,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


PARSED_RESUME = {"experience": [{"company": "Acme", "position": "Senior"}]}


@pytest_asyncio.fixture
async def pair(db: AsyncSession, tenant, user):
    """A candidate-vacancy link with a parsed resume and a profile."""
    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"Staleness {uuid.uuid4().hex[:4]}"),
    )
    profile = VacancyProfile(
        tenant_id=tenant.id,
        vacancy_id=vacancy["id"],
        profile_data={"competences": [{"id": "python", "name": "Python"}]},
        version=2,
        language="en",
    )
    db.add(profile)

    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Nina",
            last_name="Orlova",
            email=f"nina-{uuid.uuid4().hex[:6]}@x.test",
        ),
    )
    resume = CandidateFile(
        tenant_id=tenant.id,
        candidate_id=candidate["id"],
        file_type="resume",
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size=1024,
        parsed_data=PARSED_RESUME,
        raw_text="text",
        parse_status="completed",
    )
    db.add(resume)
    await db.commit()

    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=candidate["id"], vacancy_id=vacancy["id"]
        ),
    )
    await db.refresh(profile)
    await db.refresh(resume)
    return {
        "cv_id": cv["id"],
        "candidate_id": candidate["id"],
        "vacancy_id": vacancy["id"],
        "profile": profile,
        "resume": resume,
    }


async def _add_run(
    db: AsyncSession,
    tenant,
    pair,
    *,
    mode: str = "resume_only",
    age_days: int = 1,
    interview_id: uuid.UUID | None = None,
    stamp_resume: bool = True,
) -> AIAnalysisRun:
    run = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=pair["cv_id"],
        mode=mode,
        status="completed",
        data_completeness="partial",
        vacancy_profile_id=pair["profile"].id,
        vacancy_profile_version=pair["profile"].version,
        interview_id=interview_id,
        verdict="needs_check",
        ai_score=0.5,
        analysis_data={"mode": mode},
        resume_snapshot_hash=(
            resume_analysis_service._compute_resume_snapshot_hash(PARSED_RESUME)
            if stamp_resume
            else None
        ),
    )
    db.add(run)
    await db.flush()
    run.created_at = datetime.now(UTC) - timedelta(days=age_days)
    await db.commit()
    await db.refresh(run)
    return run


async def _add_transcribed_interview(
    db: AsyncSession, tenant, user, pair
) -> Interview:
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=pair["cv_id"],
        interviewer_id=user.id,
        transcription_status="completed",
        analysis_status="not_started",
        transcript="hello",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview


# ---------------------------------------------------------------------------
# Staleness signals
# ---------------------------------------------------------------------------


class TestAnalysisStaleness:
    async def test_fresh_run_has_no_stale_signal(
        self, db: AsyncSession, tenant, user, pair
    ):
        run = await _add_run(db, tenant, pair)
        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert out == {
            "active_run_mode": "resume_only",
            "resume_outdated": False,
            "profile_outdated": False,
            "analysis_expired": False,
            "transcript_outdated": False,
            "newer_transcribed_interview_id": None,
        }

    async def test_no_active_run_reports_nothing_stale(
        self, db: AsyncSession, tenant, pair
    ):
        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, None, None
        )
        assert out["active_run_mode"] is None
        assert not any(
            out[k]
            for k in (
                "resume_outdated",
                "profile_outdated",
                "analysis_expired",
                "transcript_outdated",
            )
        )

    async def test_reparsed_resume_flags_resume_outdated(
        self, db: AsyncSession, tenant, user, pair
    ):
        run = await _add_run(db, tenant, pair)
        pair["resume"].parsed_data = {"experience": [{"company": "New Corp"}]}
        await db.commit()

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert out["resume_outdated"] is True
        assert out["profile_outdated"] is False

    async def test_run_without_stamped_hash_never_claims_resume_outdated(
        self, db: AsyncSession, tenant, user, pair
    ):
        """Legacy rows carry no snapshot — we do not guess."""
        run = await _add_run(db, tenant, pair, stamp_resume=False)
        pair["resume"].parsed_data = {"experience": [{"company": "New Corp"}]}
        await db.commit()

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert out["resume_outdated"] is False

    async def test_profile_version_bump_flags_profile_outdated(
        self, db: AsyncSession, tenant, user, pair
    ):
        run = await _add_run(db, tenant, pair)
        pair["profile"].version = pair["profile"].version + 1
        await db.commit()

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert out["profile_outdated"] is True
        assert out["resume_outdated"] is False

    async def test_run_older_than_window_flags_expired(
        self, db: AsyncSession, tenant, user, pair
    ):
        run = await _add_run(
            db,
            tenant,
            pair,
            age_days=resume_analysis_service.TOPUP_WINDOW_DAYS + 1,
        )
        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert out["analysis_expired"] is True

    async def test_full_run_flags_a_transcript_it_never_saw(
        self, db: AsyncSession, tenant, user, pair
    ):
        """HRP-492 case 2 — a second interview landed after the analysis."""
        analysed = await _add_transcribed_interview(db, tenant, user, pair)
        run = await _add_run(
            db, tenant, pair, mode="full", interview_id=analysed.id
        )
        newer = await _add_transcribed_interview(db, tenant, user, pair)

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, newer
        )
        assert out["transcript_outdated"] is True
        # The banner's button re-runs against the freshest transcript.
        assert out["newer_transcribed_interview_id"] == str(newer.id)

    async def test_full_run_on_the_latest_transcript_is_not_stale(
        self, db: AsyncSession, tenant, user, pair
    ):
        analysed = await _add_transcribed_interview(db, tenant, user, pair)
        # The run completes after the transcript it consumed landed.
        run = await _add_run(
            db, tenant, pair, mode="full", interview_id=analysed.id, age_days=0
        )

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, analysed
        )
        assert out["transcript_outdated"] is False
        assert out["newer_transcribed_interview_id"] is None

    async def _complete_full_run(
        self, db: AsyncSession, tenant, user, pair
    ) -> tuple[AIAnalysisRun, Interview]:
        """A full run the way the worker leaves it (HRP-492 REDO 3).

        The row is stamped ``pending`` at the click (``created_at``) and
        the verdict is written onto the interview in the same transaction
        that completes the run — so the interview row is always touched
        *after* the run was created.
        """
        analysed = await _add_transcribed_interview(db, tenant, user, pair)
        run = await _add_run(
            db, tenant, pair, mode="full", interview_id=analysed.id, age_days=0
        )
        run.created_at = datetime.now(UTC) - timedelta(minutes=10)
        await db.commit()
        analysed.analysis_status = "completed"
        run.verdict_summary = "Fresh verdict."
        await db.commit()
        await db.refresh(run)
        await db.refresh(analysed)
        return run, analysed

    async def test_fresh_full_run_is_not_stale(
        self, db: AsyncSession, tenant, user, pair
    ):
        """QA (15.09): the banner showed after *every* fresh analysis."""
        run, analysed = await self._complete_full_run(db, tenant, user, pair)

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, analysed
        )
        assert out["transcript_outdated"] is False
        assert out["newer_transcribed_interview_id"] is None

    async def _hashed_full_run(
        self, db: AsyncSession, tenant, user, pair
    ) -> tuple[AIAnalysisRun, Interview]:
        """A full run that recorded the transcript it analysed (HRP-492)."""
        analysed = await _add_transcribed_interview(db, tenant, user, pair)
        run = await _add_run(
            db, tenant, pair, mode="full", interview_id=analysed.id, age_days=0
        )
        run.analysis_data = {
            "mode": "full",
            "transcript_hash": resume_analysis_service.transcript_hash(
                analysed.transcript
            ),
        }
        await db.commit()
        return run, analysed

    async def test_editing_the_interview_card_is_not_a_new_transcript(
        self, db: AsyncSession, tenant, user, pair
    ):
        """Review: a rename or a note moves ``updated_at`` too — the banner
        must key on the transcript, not on the row."""
        run, analysed = await self._hashed_full_run(db, tenant, user, pair)
        analysed.title = "Renamed after the analysis"
        analysed.notes = "Good conversation"
        await db.commit()
        await db.refresh(analysed)

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, analysed
        )
        assert out["transcript_outdated"] is False

    async def test_a_changed_transcript_is_stale_even_if_older_than_the_run(
        self, db: AsyncSession, tenant, user, pair
    ):
        run, analysed = await self._hashed_full_run(db, tenant, user, pair)
        analysed.transcript = "a different conversation"
        await db.commit()
        await db.refresh(analysed)
        # Timestamps say nothing here: the hash is what decides.
        run.updated_at = datetime.now(UTC) + timedelta(hours=1)
        await db.commit()

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, analysed
        )
        assert out["transcript_outdated"] is True
        assert out["newer_transcribed_interview_id"] == str(analysed.id)

    async def test_transcript_reuploaded_after_the_analysis_is_stale(
        self, db: AsyncSession, tenant, user, pair
    ):
        """A new transcript on the same interview card, after the run."""
        run, analysed = await self._complete_full_run(db, tenant, user, pair)
        analysed.transcript = "a different conversation"
        await db.commit()
        await db.refresh(analysed)

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, analysed
        )
        assert out["transcript_outdated"] is True
        assert out["newer_transcribed_interview_id"] == str(analysed.id)

    async def test_resume_only_run_ignores_transcripts(
        self, db: AsyncSession, tenant, user, pair
    ):
        """A transcript is an *upgrade* offer for resume-only, not a
        staleness signal — HRP-489 keeps it in the top-up callout."""
        run = await _add_run(db, tenant, pair, mode="resume_only")
        interview = await _add_transcribed_interview(db, tenant, user, pair)

        cv = await db.get(CandidateVacancy, pair["cv_id"])
        out = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, interview
        )
        assert out["transcript_outdated"] is False


class TestEligibilityCarriesStaleness:
    async def test_edited_resume_closes_the_topup_upgrade(
        self, db: AsyncSession, tenant, user, pair
    ):
        """HRP-489 case 3 — a stale baseline must not be topped up at
        the discounted price."""
        await _add_run(db, tenant, pair)
        await _add_transcribed_interview(db, tenant, user, pair)
        pair["resume"].parsed_data = {"experience": [{"company": "Other"}]}
        await db.commit()

        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "resume_changed"
        assert result["resume_outdated"] is True

    async def test_staleness_block_present_on_every_branch(
        self, db: AsyncSession, tenant, user, pair
    ):
        """No run at all is the earliest early-return — the UI still
        needs the keys to exist."""
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, pair["cv_id"]
        )
        assert result["reason"] == "no_active_resume_only_run"
        for key in (
            "active_run_mode",
            "resume_outdated",
            "profile_outdated",
            "analysis_expired",
            "transcript_outdated",
            "newer_transcribed_interview_id",
        ):
            assert key in result

    async def test_eligible_branch_carries_staleness_too(
        self, db: AsyncSession, tenant, user, pair
    ):
        await _add_run(db, tenant, pair, age_days=2)
        await _add_transcribed_interview(db, tenant, user, pair)

        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, pair["cv_id"]
        )
        assert result["eligible"] is True
        assert result["active_run_mode"] == "resume_only"
        assert result["resume_outdated"] is False


# ---------------------------------------------------------------------------
# AI DATA / AI VERDICT derivation (HRP-493 task 2)
# ---------------------------------------------------------------------------


class TestApplyAiAnalysisState:
    async def _items(self, db: AsyncSession, pair) -> list[dict]:
        cv = await db.get(CandidateVacancy, pair["cv_id"])
        return [
            {
                "id": cv.id,
                "candidate_id": cv.candidate_id,
                "ai_readiness": cv.ai_readiness,
            }
        ]

    async def test_parsed_resume_alone_is_resume_only(
        self, db: AsyncSession, tenant, pair
    ):
        """Readiness follows the inputs, not the last analysis: a parsed
        resume flips AI DATA even when nothing has ever been analysed."""
        items = await self._items(db, pair)
        assert items[0]["ai_readiness"] == "none"

        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_readiness"] == "resume_only"
        assert items[0]["ai_analysis_in_progress"] is False

    async def test_transcribed_interview_promotes_to_resume_and_transcript(
        self, db: AsyncSession, tenant, user, pair
    ):
        await _add_transcribed_interview(db, tenant, user, pair)
        items = await self._items(db, pair)

        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_readiness"] == "resume_and_transcript"

    async def test_transcript_without_resume_is_transcript_only(
        self, db: AsyncSession, tenant, user, pair
    ):
        """HRP-681 — the transcript is an input on its own.

        The full analysis prompt takes the resume as an optional
        summary, so this candidate can be (and usually has been)
        analysed; reporting ``none`` claimed there was no data at all.
        """
        pair["resume"].parse_status = "failed"
        await _add_transcribed_interview(db, tenant, user, pair)
        items = await self._items(db, pair)

        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_readiness"] == "transcript_only"

    async def test_no_resume_stays_none(
        self, db: AsyncSession, tenant, user, pair
    ):
        pair["resume"].parse_status = "failed"
        await db.commit()
        items = await self._items(db, pair)

        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_readiness"] == "none"

    async def test_archived_interview_does_not_promote_readiness(
        self, db: AsyncSession, tenant, user, pair
    ):
        interview = await _add_transcribed_interview(db, tenant, user, pair)
        interview.archived_at = datetime.now(UTC)
        await db.commit()

        items = await self._items(db, pair)
        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_readiness"] == "resume_only"

    async def test_pending_run_marks_in_progress(
        self, db: AsyncSession, tenant, pair
    ):
        db.add(
            AIAnalysisRun(
                tenant_id=tenant.id,
                candidate_vacancy_id=pair["cv_id"],
                mode="resume_only",
                status="pending",
                analysis_data={},
            )
        )
        await db.commit()

        items = await self._items(db, pair)
        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_analysis_in_progress"] is True

    async def test_interview_mid_analysis_marks_in_progress(
        self, db: AsyncSession, tenant, user, pair
    ):
        """The interview-page entry point never creates a run row — the
        ``analysis_status`` flag is the only signal there."""
        interview = await _add_transcribed_interview(db, tenant, user, pair)
        interview.analysis_status = "processing"
        await db.commit()

        items = await self._items(db, pair)
        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_analysis_in_progress"] is True

    async def test_completed_run_is_not_in_progress(
        self, db: AsyncSession, tenant, pair
    ):
        await _add_run(db, tenant, pair)
        items = await self._items(db, pair)
        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items[0]["ai_analysis_in_progress"] is False

    async def test_empty_input_is_a_no_op(self, db: AsyncSession, tenant):
        items: list[dict] = []
        await resume_analysis_service.apply_ai_analysis_state(
            db, tenant.id, items
        )
        assert items == []


class TestFinalizerRecordsTheAnalysedTranscript:
    async def test_the_hash_of_what_the_model_read_is_stored(
        self, db: AsyncSession, tenant, user
    ):
        """Review: the hash is taken from the text sent to the model, not
        re-read at finalize — the task commits mid-run, and a transcript
        replaced meanwhile must still read as newer than the analysis."""
        from app.modules.recruitment.tasks.analysis import (
            _finalize_full_analysis_run,
        )
        from sqlalchemy.orm import Session

        from tests.unit.test_hrp274_normalized_ai_score import (
            _make_analysis,
            _seed_cv_with_interview,
            _sync_engine,
        )

        seeded = await _seed_cv_with_interview(db, tenant, user)
        read_by_model = resume_analysis_service.transcript_hash("what the model read")
        engine = _sync_engine()
        try:
            with Session(engine) as sync_db:
                cv = sync_db.get(CandidateVacancy, seeded["cv_id"])
                interview = sync_db.get(Interview, seeded["interview_id"])
                interview.transcript = "replaced while the model ran"
                _finalize_full_analysis_run(
                    sync_db,
                    tenant_id=tenant.id,
                    interview=interview,
                    cv=cv,
                    candidate_name="Hash Check",
                    analysis=_make_analysis(),
                    analysed_transcript_hash=read_by_model,
                )
                sync_db.commit()
                run = (
                    sync_db.query(AIAnalysisRun)
                    .filter(
                        AIAnalysisRun.candidate_vacancy_id == cv.id,
                        AIAnalysisRun.status == "completed",
                    )
                    .one()
                )
                assert run.analysis_data["transcript_hash"] == read_by_model
        finally:
            engine.dispose()
