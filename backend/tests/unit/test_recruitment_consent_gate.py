"""HRP-979: no AI processing of a candidate's data without consent in force.

Every AI entry point refuses with ``consent_required`` until the candidate
has signed, and again once they withdraw through the public link. Demo
candidates are consented on creation.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from app.core.errors import AppError
from app.main import app
from app.modules.company.models import Tenant
from app.modules.recruitment import (
    candidate_service,
    consent_service,
    interview_service,
    onboarding_service,
    question_service,
    resume_analysis_service,
    service,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
    Candidate,
    CandidateVacancy,
    ConsentRequest,
    ConsentTemplate,
    Interview,
    RecruitmentAuditLog,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateManualCreate,
    GenerateQuestionSetRequest,
    InitUploadRequest,
    InterviewCreate,
    TextTranscriptRequest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp205_question_sets import (
    _add_profile,
    _add_resume,
    _attach,
    _make_vacancy,
)


async def _pair(db: AsyncSession, tenant, user, *, consented: bool) -> dict:
    """A candidate on a vacancy with a parsed resume, a profile and an
    interview that has a transcript — every AI path is open but consent."""
    vacancy = await _make_vacancy(db, tenant, user)
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Gate",
            last_name="Keeper",
            email=f"gate-{uuid.uuid4().hex[:8]}@example.com",
        ),
    )
    cv = await _attach(db, tenant, user, candidate["id"], vacancy["id"])
    await _add_resume(db, tenant, candidate["id"], parsed={"skills": ["Python"]})
    await _add_profile(db, tenant, user, vacancy["id"])
    token = None
    if consented:
        cand_obj = await db.get(Candidate, uuid.UUID(str(candidate["id"])))
        token = (
            await consent_service._record_signed_consent(db, tenant.id, cand_obj)
        ).token
        await db.commit()
    iv = await service.create_interview(
        db, tenant.id, user.id, cv["id"], InterviewCreate(title="Screen")
    )
    row = await db.get(Interview, uuid.UUID(str(iv["id"])))
    row.transcript = "[Interviewer] Hi\n[Candidate] Hello"
    row.transcription_status = "completed"
    await db.commit()
    return {
        "candidate_id": uuid.UUID(str(candidate["id"])),
        "vacancy_id": uuid.UUID(str(vacancy["id"])),
        "cv_id": uuid.UUID(str(cv["id"])),
        "interview_id": row.id,
        "token": token,
    }


async def _refused(call) -> None:
    with pytest.raises(AppError) as exc:
        await call
    assert exc.value.code == "consent_required"
    assert exc.value.status_code == 409


class TestEveryEntryNeedsConsent:
    async def test_without_consent_every_ai_entry_refuses(
        self, db: AsyncSession, tenant, user
    ) -> None:
        p = await _pair(db, tenant, user, consented=False)

        await _refused(
            interview_service.paste_text_transcript(
                db, tenant.id, p["interview_id"], TextTranscriptRequest(text="x")
            )
        )
        await _refused(
            interview_service.init_interview_upload(
                db,
                tenant.id,
                p["interview_id"],
                InitUploadRequest(
                    filename="a.txt",
                    mime_type="text/plain",
                    size_bytes=10,
                    kind="text_transcript",
                ),
            )
        )
        await _refused(
            interview_service.enqueue_analyze_or_cached(
                db, tenant.id, p["interview_id"]
            )
        )
        await _refused(
            interview_service.enqueue_analyze(db, tenant.id, p["interview_id"])
        )
        await _refused(
            resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, p["cv_id"], user.id
            )
        )
        with patch("app.modules.recruitment.question_service._call_llm") as llm:
            await _refused(
                question_service.generate_question_set(
                    db,
                    tenant.id,
                    p["cv_id"],
                    GenerateQuestionSetRequest(mode="initial"),
                    current_user_id=user.id,
                )
            )
        llm.assert_not_called()
        bulk = await resume_analysis_service.enqueue_bulk_resume_only(
            db, tenant.id, p["vacancy_id"], [p["cv_id"]], user.id
        )
        assert bulk["queued"] == []
        assert bulk["failed"][0]["status_code"] == 409

    async def test_legacy_generate_questions_route_refuses(
        self, db: AsyncSession, tenant, user, auth_client
    ) -> None:
        p = await _pair(db, tenant, user, consented=False)
        with patch(
            "app.modules.recruitment.tasks.generate_questions_task.delay"
        ) as delay:
            resp = await auth_client.post(
                f"/api/recruitment/candidates/{p['candidate_id']}"
                f"/vacancies/{p['vacancy_id']}/generate-questions"
            )
        assert resp.status_code == 409
        delay.assert_not_called()

    async def test_with_consent_the_transcript_goes_through(
        self, db: AsyncSession, tenant, user
    ) -> None:
        p = await _pair(db, tenant, user, consented=True)
        out = await interview_service.paste_text_transcript(
            db,
            tenant.id,
            p["interview_id"],
            TextTranscriptRequest(text="Interviewer: hi\nCandidate: hello"),
        )
        assert out["transcription_status"] == "completed"


class TestRevocation:
    async def test_withdrawn_consent_blocks_ai_and_the_upload_gate(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        p = await _pair(db, tenant, user, consented=True)
        iv = await db.get(Interview, p["interview_id"])
        assert iv.consent_signed_at is not None
        latest = await consent_service.get_latest_consent(
            db, tenant.id, p["candidate_id"]
        )
        assert latest["active"] is True

        resp = await client.post(f"/api/recruitment/consent/{p['token']}/revoke")
        assert resp.status_code == 200
        assert resp.json() == {"status": "revoked"}

        await _refused(
            interview_service.paste_text_transcript(
                db, tenant.id, p["interview_id"], TextTranscriptRequest(text="x")
            )
        )
        await _refused(
            resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, p["cv_id"], user.id
            )
        )
        iv = await db.get(Interview, p["interview_id"], populate_existing=True)
        assert iv.consent_signed_at is None
        latest = await consent_service.get_latest_consent(
            db, tenant.id, p["candidate_id"]
        )
        assert (latest["status"], latest["active"]) == ("revoked", False)
        view = await client.get(f"/api/recruitment/consent/{p['token']}")
        assert view.json()["status"] == "revoked"
        event = await db.scalar(
            select(RecruitmentAuditLog).where(
                RecruitmentAuditLog.tenant_id == tenant.id,
                RecruitmentAuditLog.action == "consent.revoke",
            )
        )
        assert event is not None and event.user_id is None
        # Withdrawing twice is harmless; signing the dead link again is not.
        again = await client.post(f"/api/recruitment/consent/{p['token']}/revoke")
        assert again.json() == {"status": "revoked"}
        resign = await client.post(f"/api/recruitment/consent/{p['token']}/sign")
        assert resign.status_code == 410

    async def test_every_signature_of_the_candidate_is_withdrawn(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        p = await _pair(db, tenant, user, consented=True)
        cand = await db.get(Candidate, p["candidate_id"])
        await consent_service._record_signed_consent(db, tenant.id, cand)
        await db.commit()

        await client.post(f"/api/recruitment/consent/{p['token']}/revoke")

        assert not await consent_service.has_active_consent(
            db, tenant.id, p["candidate_id"]
        )

    async def test_only_a_signed_consent_can_be_withdrawn(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        p = await _pair(db, tenant, user, consented=False)
        template = ConsentTemplate(tenant_id=tenant.id, name="T", body="B")
        db.add(template)
        await db.flush()
        pending = ConsentRequest(
            tenant_id=tenant.id,
            candidate_id=p["candidate_id"],
            template_id=template.id,
            token=uuid.uuid4().hex,
            email="c@example.com",
            expires_at=datetime.now(UTC) + timedelta(days=3),
        )
        db.add(pending)
        await db.commit()

        resp = await client.post(f"/api/recruitment/consent/{pending.token}/revoke")
        assert resp.status_code == 409
        missing = await client.post("/api/recruitment/consent/no-such-token/revoke")
        assert missing.status_code == 404


class TestDemoAutoConsent:
    async def _demo_tenant(self, db: AsyncSession) -> Tenant:
        t = Tenant(
            name=f"Demo {uuid.uuid4().hex[:6]}",
            slug=f"demo-{uuid.uuid4().hex[:8]}",
            is_demo=True,
        )
        db.add(t)
        await db.commit()
        return t

    async def test_new_demo_candidates_are_consented(
        self, db: AsyncSession, user
    ) -> None:
        demo = await self._demo_tenant(db)
        created = await service.create_candidate(
            db,
            demo.id,
            user.id,
            CandidateCreate(
                first_name="Demo",
                last_name="One",
                email=f"d1-{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        vacancy = await _make_vacancy(db, demo, user)
        manual = await service.add_candidate_to_vacancy_manual(
            db,
            demo.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Demo Two", email=f"d2-{uuid.uuid4().hex[:6]}@example.com"
            ),
        )
        for cid in (created["id"], manual["id"]):
            assert await consent_service.has_active_consent(
                db, demo.id, uuid.UUID(str(cid))
            )
        # No active template: the default is made on demand and kept
        # inactive, so real consent requests never go out with it.
        templates = (
            (
                await db.execute(
                    select(ConsentTemplate).where(ConsentTemplate.tenant_id == demo.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(templates) == 1 and not templates[0].is_active

        cv = await _attach(db, demo, user, created["id"], vacancy["id"])
        iv = await service.create_interview(
            db, demo.id, user.id, cv["id"], InterviewCreate()
        )
        out = await interview_service.paste_text_transcript(
            db,
            demo.id,
            uuid.UUID(str(iv["id"])),
            TextTranscriptRequest(text="Interviewer: hi\nCandidate: hello"),
        )
        assert out["transcription_status"] == "completed"

    async def test_a_bulk_import_looks_the_tenant_up_once(
        self, db: AsyncSession, user, monkeypatch
    ) -> None:
        from app.modules.recruitment.models import CandidateFile
        from app.modules.recruitment.schemas import (
            BatchFinalizeFile,
            BatchFinalizeRequest,
        )

        demo = await self._demo_tenant(db)
        vacancy = await _make_vacancy(db, demo, user)
        files = []
        for i in range(2):
            cf = CandidateFile(
                tenant_id=demo.id,
                file_type="resume",
                original_filename=f"cv{i}.pdf",
                mime_type="application/pdf",
                file_size=1,
                parse_status="completed",
                parsed_data={
                    "first_name": f"Bulk{i}",
                    "last_name": "Import",
                    "contacts": {"email": f"bulk{i}-{uuid.uuid4().hex[:6]}@x.test"},
                },
            )
            db.add(cf)
            files.append(cf)
        await db.commit()
        lookups = 0
        real = candidate_service.is_demo_tenant

        async def counting(*args, **kwargs):
            nonlocal lookups
            lookups += 1
            return await real(*args, **kwargs)

        monkeypatch.setattr(candidate_service, "is_demo_tenant", counting)

        result = await service.finalize_candidates_from_parsed(
            db,
            demo.id,
            user.id,
            vacancy["id"],
            BatchFinalizeRequest(
                files=[BatchFinalizeFile(file_id=f.id) for f in files]
            ),
        )

        assert len(result["created"]) == 2
        assert lookups == 1
        for row in result["created"]:
            assert await consent_service.has_active_consent(
                db, demo.id, uuid.UUID(row["candidate_id"])
            )

    async def test_onboarding_samples_are_consented(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """Maxim 04.10: the walkthrough's fictional candidates in a regular
        workspace get consent, so its AI actions open on them."""
        await onboarding_service.seed_demo(db, tenant.id, user.id)

        samples = (
            (
                await db.execute(
                    select(Candidate).where(
                        Candidate.tenant_id == tenant.id, Candidate.source == "demo"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(samples) == 3
        for cand in samples:
            assert await consent_service.has_active_consent(db, tenant.id, cand.id)
        # The regular workspace keeps no active template it never wrote.
        assert (
            await db.scalar(
                select(ConsentTemplate).where(
                    ConsentTemplate.tenant_id == tenant.id,
                    ConsentTemplate.is_active.is_(True),
                )
            )
        ) is None
        interview = await db.scalar(
            select(Interview)
            .join(
                CandidateVacancy, Interview.candidate_vacancy_id == CandidateVacancy.id
            )
            .where(Interview.tenant_id == tenant.id)
            .limit(1)
        )
        out = await interview_service.paste_text_transcript(
            db,
            tenant.id,
            interview.id,
            TextTranscriptRequest(text="Interviewer: hi\nCandidate: hello"),
        )
        assert out["transcription_status"] == "completed"

    async def test_onboarding_cleanup_takes_the_default_template_along(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """Re-review 04.10: the samples' auto-consent template goes with them,
        a template an admin wrote stays."""
        own = ConsentTemplate(
            tenant_id=tenant.id, name="Ours", body="Our text", is_active=False
        )
        db.add(own)
        await db.commit()
        await onboarding_service.seed_demo(db, tenant.id, user.id)
        names = await db.scalars(
            select(ConsentTemplate.name).where(ConsentTemplate.tenant_id == tenant.id)
        )
        assert sorted(names) == ["Candidate consent", "Ours"]

        await onboarding_service.cleanup_demo(db, tenant.id)

        names = await db.scalars(
            select(ConsentTemplate.name).where(ConsentTemplate.tenant_id == tenant.id)
        )
        assert list(names) == ["Ours"]

    async def test_regular_tenant_candidates_are_not(
        self, db: AsyncSession, tenant, user
    ) -> None:
        created = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="Real",
                last_name="One",
                email=f"r-{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        assert not await consent_service.has_active_consent(
            db, tenant.id, uuid.UUID(str(created["id"]))
        )


class TestAnalysisTaskGate:
    """A consent withdrawn while the job waits in the queue stops it."""

    async def test_interview_analysis_stops_before_the_ai_call(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        from app.modules.recruitment.tasks import analyze_interview_task

        p = await _pair(db, tenant, user, consented=True)
        run = AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=p["cv_id"],
            mode="full",
            status="pending",
            interview_id=p["interview_id"],
        )
        db.add(run)
        await db.commit()
        assert (
            consent_service.analysis_consent_gate(
                str(tenant.id), interview_id=str(p["interview_id"])
            )
            is None
        )
        await client.post(f"/api/recruitment/consent/{p['token']}/revoke")

        with patch("app.modules.ai.llm_client.generate_json") as llm:
            result = analyze_interview_task.run(str(p["interview_id"]), str(tenant.id))
        llm.assert_not_called()
        assert result == {"status": "failed", "error": "consent_required"}
        iv = await db.get(Interview, p["interview_id"], populate_existing=True)
        assert iv.analysis_status == "failed"
        run = await db.get(AIAnalysisRun, run.id, populate_existing=True)
        assert run.status == "failed"

    async def test_a_stopped_run_keeps_its_charge(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        """Review 04.10, decided behaviour: a withdrawal while the run waits
        in the queue stops it, and the credits taken at start stay taken
        (features.md says so). Cancel is the refunding path."""
        p = await _pair(db, tenant, user, consented=True)
        run = AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=p["cv_id"],
            mode="resume_only",
            status="pending",
            credits_charged=20.0,
        )
        db.add(run)
        await db.commit()
        await client.post(f"/api/recruitment/consent/{p['token']}/revoke")

        refused = consent_service.analysis_consent_gate(
            str(tenant.id), run_id=str(run.id)
        )

        assert refused == {"status": "failed", "error": "consent_required"}
        run = await db.get(AIAnalysisRun, run.id, populate_existing=True)
        assert (run.status, run.credits_charged) == ("failed", 20.0)

    async def test_resume_only_analysis_stops_too(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        from app.modules.recruitment.tasks import analyze_resume_only_task

        p = await _pair(db, tenant, user, consented=True)
        run = AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=p["cv_id"],
            mode="resume_only",
            status="pending",
        )
        db.add(run)
        await db.commit()
        await client.post(f"/api/recruitment/consent/{p['token']}/revoke")

        result = analyze_resume_only_task.run(str(run.id), str(tenant.id))

        assert result == {"status": "failed", "error": "consent_required"}
        run = await db.get(AIAnalysisRun, run.id, populate_existing=True)
        assert run.status == "failed"


def _revoke_sync(candidate_id: uuid.UUID) -> None:
    """Withdraw consent from inside a worker stage (sync engine)."""
    from sqlalchemy import create_engine, text

    from tests.conftest import TEST_DB_URL

    engine = create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE consent_requests SET status = 'revoked'"
                    " WHERE candidate_id = :c"
                ),
                {"c": candidate_id},
            )
    finally:
        engine.dispose()


class TestWorkerStagesNeedConsent:
    """Review 05.10 (E3/E4): every paid stage and every write re-checks the
    consent, not only the task's start."""

    @pytest.fixture(autouse=True)
    def _worker_db(self, monkeypatch):
        from app.config import settings as app_settings

        from tests.conftest import TEST_DB_URL

        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)
        monkeypatch.setattr(app_settings, "demo_ai_killswitch", False)

    async def _with_media(self, db: AsyncSession, tenant, user) -> dict:
        from app.modules.storage.models import File

        p = await _pair(db, tenant, user, consented=True)
        media = File(
            tenant_id=tenant.id,
            name="a.mp3",
            original_name="a.mp3",
            path=f"interviews/{uuid.uuid4().hex}.mp3",
            size=10,
            mime_type="audio/mpeg",
            uploaded_by=user.id,
        )
        db.add(media)
        await db.flush()
        row = await db.get(Interview, p["interview_id"])
        row.audio_file_id = media.id
        await db.commit()
        return p

    async def test_transcription_without_consent_never_calls_the_provider(
        self, db: AsyncSession, tenant, user, client, monkeypatch
    ) -> None:
        from app.modules.recruitment import transcription_service
        from app.modules.recruitment.tasks import transcribe_interview_task

        p = await self._with_media(db, tenant, user)
        await client.post(f"/api/recruitment/consent/{p['token']}/revoke")
        chain = []
        monkeypatch.setattr(
            transcription_service,
            "get_transcription_chain_sync",
            lambda *_a: chain.append(1) or ["x"],
        )

        result = transcribe_interview_task.run(str(p["interview_id"]), str(tenant.id))

        assert result == {"status": "failed", "error": "consent_required"}
        assert chain == []
        iv = await db.get(Interview, p["interview_id"], populate_existing=True)
        assert iv.transcription_status == "failed"

    async def test_consent_withdrawn_during_stt_drops_the_transcript(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        import asyncio

        from app.modules.recruitment import media_prep, speaker_roles
        from app.modules.recruitment import transcription_service as ts
        from app.modules.recruitment.tasks import transcribe_interview_task

        p = await self._with_media(db, tenant, user)
        monkeypatch.setattr(ts, "get_transcription_chain_sync", lambda *_a: ["x"])
        monkeypatch.setattr(
            "app.core.s3.get_presigned_url", lambda *_a, **_kw: "http://s3/x"
        )
        monkeypatch.setattr(media_prep, "fetch_to_file", lambda _url, path: path)
        monkeypatch.setattr(media_prep, "extract_audio", lambda *_a: None)

        async def stt(*_a, **_kw):
            _revoke_sync(p["candidate_id"])
            return (
                ts.TranscriptionResult(
                    full_text="secret words",
                    segments=[ts.TranscriptSegment("A", 0.0, 1.0, "secret words")],
                    provider="fake",
                ),
                None,
            )

        labelled = []
        monkeypatch.setattr(ts, "transcribe_with_chain", stt)
        monkeypatch.setattr(
            speaker_roles, "label_speakers_sync", lambda *a, **kw: labelled.append(1)
        )

        result = await asyncio.to_thread(
            transcribe_interview_task.run, str(p["interview_id"]), str(tenant.id)
        )

        assert result == {"status": "failed", "error": "consent_required"}
        assert labelled == []
        iv = await db.get(Interview, p["interview_id"], populate_existing=True)
        assert iv.transcription_status == "failed"
        assert "secret" not in (iv.transcript or "")

    async def test_consent_withdrawn_during_the_llm_discards_the_analysis(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        import asyncio

        from app.modules.recruitment.prompts_interview import (
            InterviewAnalysisResult,
        )
        from app.modules.recruitment.tasks import analyze_interview_task

        p = await _pair(db, tenant, user, consented=True)

        async def llm(*_a, **_kw):
            _revoke_sync(p["candidate_id"])
            return InterviewAnalysisResult(
                data_completeness="partial", verdict_summary="Secret verdict."
            )

        monkeypatch.setattr("app.modules.ai.llm_client.generate_json", llm)

        result = await asyncio.to_thread(
            analyze_interview_task.run, str(p["interview_id"]), str(tenant.id)
        )

        assert result == {"status": "failed", "error": "consent_required"}
        iv = await db.get(Interview, p["interview_id"], populate_existing=True)
        assert iv.analysis_status == "failed"
        assert "Secret verdict." not in str(iv.analysis_data)

    async def test_question_generation_without_consent_never_calls_the_llm(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from app.modules.recruitment.tasks import generate_questions_task

        p = await _pair(db, tenant, user, consented=False)
        with patch(
            "app.modules.recruitment.ai_service.generate_individual_questions"
        ) as llm:
            result = generate_questions_task.run(
                str(p["candidate_id"]), str(p["vacancy_id"]), str(tenant.id)
            )
        llm.assert_not_called()
        assert result == {"status": "failed", "error": "consent_required"}


_PUBLIC_PAGE = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "app"
    / "(invite)"
    / "recruitment"
    / "consent"
    / "[token]"
    / "page.tsx"
)


@pytest.mark.skipif(not _PUBLIC_PAGE.exists(), reason="frontend tree not present")
def test_the_withdraw_button_calls_a_url_the_app_serves() -> None:
    urls = re.findall(
        r"/recruitment/consent/\$\{token\}/\w+",
        _PUBLIC_PAGE.read_text(encoding="utf-8"),
    )
    referenced = {"/api" + u.replace("${token}", "{token}") for u in urls}
    mounted = {getattr(r, "path", "") for r in app.routes}
    assert "/api/recruitment/consent/{token}/revoke" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
