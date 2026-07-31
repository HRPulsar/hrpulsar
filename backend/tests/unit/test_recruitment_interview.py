"""Service-level tests for interview + consent flow (R3a)."""

import uuid

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.schemas import (
    AbortUploadRequest,
    CandidateCreate,
    CandidateVacancyCreate,
    CompletePart,
    CompleteUploadRequest,
    ConsentSendRequest,
    ConsentTemplateCreate,
    ConsentTemplateUpdate,
    InitUploadRequest,
    InterviewCreate,
    InterviewSegmentUpdate,
    InterviewUpdate,
    PartUrlRequest,
    TranscriptUpdate,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup_cv(db: AsyncSession, tenant, user) -> dict:
    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"V {uuid.uuid4().hex[:6]}"),
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"First-{uuid.uuid4().hex[:4]}",
            last_name=f"Last-{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=candidate["id"],
            vacancy_id=vacancy["id"],
        ),
    )
    return {"vacancy": vacancy, "candidate": candidate, "cv": cv}


class TestInterviewService:
    async def test_create_interview(self, db: AsyncSession, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        result = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(notes="Initial slot"),
        )
        assert result["candidate_vacancy_id"] == ctx["cv"]["id"]
        # HRP-202: default lifecycle is now ``scheduled`` (was ``planned``).
        assert result["status"] == "scheduled"
        assert result["transcription_status"] == "pending"
        assert result["analysis_status"] == "pending"
        assert result["consent_signed_at"] is None

    async def test_create_interview_unknown_cv_returns_404(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_interview(
                db,
                tenant.id,
                user.id,
                uuid.uuid4(),
                InterviewCreate(notes="x"),
            )
        assert exc.value.status_code == 404

    async def test_init_upload_requires_consent(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.init_interview_upload(
                db,
                tenant.id,
                interview["id"],
                InitUploadRequest(
                    filename="rec.mp3",
                    mime_type="audio/mpeg",
                    size_bytes=1024,
                    kind="audio",
                ),
            )
        assert exc.value.status_code == 409
        assert "consent" in str(exc.value.detail).lower()

    async def test_complete_upload_requires_consent(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview["id"],
                CompleteUploadRequest(
                    upload_id="u-1",
                    parts=[CompletePart(part_number=1, etag="e1")],
                ),
            )
        assert exc.value.status_code == 409

    async def test_update_interview_partial(self, db: AsyncSession, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        updated = await service.update_interview(
            db,
            tenant.id,
            interview["id"],
            InterviewUpdate(notes="Reschedule pending", status="scheduled"),
        )
        assert updated["notes"] == "Reschedule pending"
        assert updated["status"] == "scheduled"

    async def test_update_transcript_redacts_pii(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        out = await service.update_transcript(
            db,
            tenant.id,
            interview["id"],
            TranscriptUpdate(transcript="Tax ID 7707083893 — our counterparty"),
        )
        assert "7707083893" not in out["transcript"]
        assert "[REDACTED:inn]" in out["transcript"]

    async def test_enqueue_transcribe_without_media_returns_409(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.enqueue_transcribe(db, tenant.id, interview["id"])
        assert exc.value.status_code == 409

    async def test_get_media_url_without_file_returns_404(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.get_interview_media_url(
                db, tenant.id, interview["id"]
            )
        assert exc.value.status_code == 404

    async def test_abort_upload_returns_aborted_marker(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        # abort_multipart_upload requires an S3 client; stub it out so the
        # service path itself is exercised without external state.
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "abort_multipart_upload", lambda *a, **k: True)
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        out = await service.abort_interview_upload(
            db,
            tenant.id,
            interview["id"],
            AbortUploadRequest(upload_id="u-1"),
        )
        assert out["status"] == "aborted"


class TestConsentFlow:
    async def test_send_consent_request_without_template_fails(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.send_consent_request(
                db,
                tenant.id,
                user.id,
                ctx["candidate"]["id"],
                ConsentSendRequest(email="c@example.com"),
            )
        assert exc.value.status_code == 409

    async def test_consent_send_request_rejects_invalid_email(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConsentSendRequest(email="not-an-email")

    async def test_create_consent_template_deactivates_previous(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import ConsentTemplateCreate

        first = await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="A", body="body A", is_active=True, language="fr"
            ),
        )
        second = await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="B", body="body B", is_active=True, language="fr"
            ),
        )
        templates = {
            t["id"]: t
            for t in await service.list_consent_templates(db, tenant.id)
        }
        # Only one active template per tenant — partial unique index +
        # bulk-update deactivation enforce this together.
        assert templates[first["id"]]["is_active"] is False
        assert templates[second["id"]]["is_active"] is True

    async def test_send_then_sign_consent_propagates_to_interviews(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="Default",
                body="By signing, you agree to recording.",
                language="fr",
                is_active=True,
            ),
        )
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        send_result = await service.send_consent_request(
            db,
            tenant.id,
            user.id,
            ctx["candidate"]["id"],
            ConsentSendRequest(email="c@example.com"),
        )
        assert send_result["status"] == "pending"

        # Resolve token via DB to mimic candidate clicking the link.
        from app.modules.recruitment.models import ConsentRequest
        from sqlalchemy import select

        token = (
            await db.execute(
                select(ConsentRequest.token).where(
                    ConsentRequest.id == send_result["id"]
                )
            )
        ).scalar_one()

        view = await service.get_consent_by_token(db, token)
        assert view["status"] == "pending"
        assert view["template_body"]

        signed = await service.sign_consent(
            db,
            token,
            signed_ip="127.0.0.1",
            signed_user_agent="pytest",
        )
        assert signed["status"] == "signed"

        # consent_signed_at should now be propagated to the interview row.
        refreshed = await service.get_interview(
            db, tenant.id, interview["id"], role="recruiter"
        )
        assert refreshed["consent_signed_at"] is not None

        # FR-28: signing the consent is a tenant-data mutation and must
        # leave an audit-log row even though the caller used a public
        # token (no tenant_id in args).
        from app.modules.recruitment import audit_service

        items, _ = await audit_service.list_events(
            db, tenant.id, action="consent.sign"
        )
        assert items, "consent.sign audit row not found"
        assert items[0]["entity_type"] == "consent"
        assert items[0]["entity_id"] == send_result["id"]
        # Anonymous signer — user_id stays None.
        assert items[0]["user_id"] is None
        assert items[0]["payload_diff"]["signed_ip"] == "127.0.0.1"

    async def test_template_create_deactivates_previous_active(
        self, db: AsyncSession, tenant, user
    ):
        first = await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="A", body="body A", language="fr", is_active=True
            ),
        )
        second = await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="B", body="body B", language="fr", is_active=True
            ),
        )
        templates = {t["id"]: t for t in await service.list_consent_templates(db, tenant.id)}
        assert templates[first["id"]]["is_active"] is False
        assert templates[second["id"]]["is_active"] is True

    async def test_template_update_bumps_version_when_body_changes(
        self, db: AsyncSession, tenant, user
    ):
        created = await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="N", body="old body", language="fr", is_active=True
            ),
        )
        assert created["version"] == 1
        updated = await service.update_consent_template(
            db,
            tenant.id,
            created["id"],
            ConsentTemplateUpdate(body="new body"),
        )
        assert updated["version"] == 2

    async def test_get_latest_consent_returns_none_when_never_sent(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        out = await service.get_latest_consent(
            db, tenant.id, ctx["candidate"]["id"]
        )
        assert out is None

    async def test_get_latest_consent_returns_most_recent(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="Default", body="t", language="fr", is_active=True
            ),
        )
        await service.send_consent_request(
            db,
            tenant.id,
            user.id,
            ctx["candidate"]["id"],
            ConsentSendRequest(email="a@example.com"),
        )
        second = await service.send_consent_request(
            db,
            tenant.id,
            user.id,
            ctx["candidate"]["id"],
            ConsentSendRequest(email="b@example.com"),
        )
        out = await service.get_latest_consent(
            db, tenant.id, ctx["candidate"]["id"]
        )
        assert out is not None
        # Latest = the second send; the first should be superseded.
        assert out["id"] == second["id"]
        assert out["email"] == "b@example.com"

    async def test_get_part_url_uses_deterministic_key(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        from app.core import s3 as s3_module

        captured: dict = {}

        def fake_part_url(path, upload_id, part_number, expires_in=3600):
            captured["path"] = path
            captured["upload_id"] = upload_id
            captured["part_number"] = part_number
            return "https://signed/example"

        monkeypatch.setattr(s3_module, "get_part_presigned_url", fake_part_url)

        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        out = await service.get_upload_part_url(
            db,
            tenant.id,
            interview["id"],
            PartUrlRequest(upload_id="u-1", part_number=2),
        )
        assert out["url"] == "https://signed/example"
        assert captured["path"].endswith(f"interviews/{interview['id']}/upload")
        assert captured["upload_id"] == "u-1"
        assert captured["part_number"] == 2


class TestSegmentService:
    async def test_update_segment_redacts_pii(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )

        # Insert a segment directly so we can test the update path.
        from app.modules.recruitment.models import InterviewSegment

        seg = InterviewSegment(
            tenant_id=tenant.id,
            interview_id=interview["id"],
            speaker="speaker_0",
            start_sec=0.0,
            end_sec=2.0,
            text="placeholder",
        )
        db.add(seg)
        await db.commit()
        await db.refresh(seg)

        out = await service.update_segment(
            db,
            tenant.id,
            interview["id"],
            seg.id,
            InterviewSegmentUpdate(
                text="Tax ID 7707083893",
                speaker="speaker_1",
            ),
        )
        assert out["speaker"] == "speaker_1"
        assert "[REDACTED:inn]" in out["text"]

    async def test_update_unknown_segment_returns_404(
        self, db: AsyncSession, tenant, user
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await service.create_interview(
            db,
            tenant.id,
            user.id,
            ctx["cv"]["id"],
            InterviewCreate(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_segment(
                db,
                tenant.id,
                interview["id"],
                uuid.uuid4(),
                InterviewSegmentUpdate(text="x"),
            )
        assert exc.value.status_code == 404


# TestTranscribePerMinutePricing was moved to tests/unit/ee/
# test_recruitment_transcribe_billing.py — it imports ee.billing and
# breaks public-repo CI (community build has no ee/ package).


class TestConsentEmailCandidateName:
    """HRP-384: the consent email greeted resume-sourced candidates as
    "(unnamed)".

    Both the email and the public consent view used to read the linked
    ``Person`` only. ``Candidate.person_id`` has been nullable since
    HRP-181 REDO — a candidate created from an uploaded resume has no
    ``Person`` row, and their name lives on the canonical
    ``Candidate.full_name``, so the person-only lookup fell through to
    the fallback.
    """

    async def _personless_candidate(self, db, tenant):
        from app.modules.recruitment.models import Candidate

        candidate = Candidate(
            tenant_id=tenant.id,
            person_id=None,
            full_name="Grace Hopper",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            source="resume",
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate, ["person", "files"])
        return candidate

    async def _send(self, db, tenant, user, candidate, monkeypatch):
        import app.core.email as email_mod

        sent: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            email_mod,
            "enqueue_email",
            lambda to, subject, html, **kw: sent.append((to, subject, html)),
        )
        await service.create_consent_template(
            db,
            tenant.id,
            ConsentTemplateCreate(
                name="Default",
                body="By signing, you agree to recording.",
                language="en",
                is_active=True,
            ),
        )
        result = await service.send_consent_request(
            db,
            tenant.id,
            user.id,
            candidate.id,
            ConsentSendRequest(email="candidate@example.com"),
        )
        return result, sent

    async def test_email_greets_candidate_without_person_row(
        self, db, tenant, user, monkeypatch
    ):
        candidate = await self._personless_candidate(db, tenant)
        _, sent = await self._send(db, tenant, user, candidate, monkeypatch)

        assert len(sent) == 1
        html = sent[0][2]
        assert "Hello, Grace Hopper" in html
        assert "(unnamed)" not in html

    async def test_public_consent_view_exposes_the_name(
        self, db, tenant, user, monkeypatch
    ):
        from app.modules.recruitment.models import ConsentRequest
        from sqlalchemy import select

        candidate = await self._personless_candidate(db, tenant)
        result, _ = await self._send(db, tenant, user, candidate, monkeypatch)

        token = (
            await db.execute(
                select(ConsentRequest.token).where(ConsentRequest.id == result["id"])
            )
        ).scalar_one()
        view = await service.get_consent_by_token(db, token)
        assert view["candidate_name"] == "Grace Hopper"

    async def test_person_backed_candidate_still_uses_person_name(
        self, db, tenant, user, monkeypatch
    ):
        """The Person path must keep working for internal referrals."""
        created = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="Ada",
                last_name="Lovelace",
                email=f"{uuid.uuid4().hex[:8]}@example.com",
            ),
        )
        from app.modules.recruitment.models import Candidate

        candidate = await db.get(Candidate, created["id"])
        _, sent = await self._send(db, tenant, user, candidate, monkeypatch)
        assert "Hello, Ada Lovelace" in sent[0][2]

    async def test_fallback_is_localized_when_there_is_no_name_at_all(
        self, db, tenant, user, monkeypatch
    ):
        """A genuinely nameless row still must not leak an untranslated
        string — the fallback comes from the email catalog."""
        from app.core.i18n import translate
        from app.modules.recruitment.models import Candidate

        candidate = Candidate(
            tenant_id=tenant.id,
            person_id=None,
            full_name="   ",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            source="resume",
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate, ["person", "files"])

        _, sent = await self._send(db, tenant, user, candidate, monkeypatch)
        assert translate("email.fallback.unnamed", "en") in sent[0][2]
