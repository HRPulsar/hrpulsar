"""HRP-202: interview upload + lifecycle service tests.

Covers the new upload-session bookkeeping, TUS-style HEAD/PATCH
helpers, text-paste transcript, archive/restore, replace-file, signed
URL TTL and antivirus verdict handling.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.recruitment import interview_service, service
from app.modules.recruitment.models import (
    Interview,
    InterviewInterviewer,
    UploadSession,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    InitUploadRequest,
    InterviewArchiveRequest,
    InterviewCreate,
    InterviewUpdate,
    TextTranscriptRequest,
    UploadChunkAck,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
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


async def _scheduled_interview(db, tenant, user, cv) -> dict:
    return await service.create_interview(
        db,
        tenant.id,
        user.id,
        cv["id"],
        InterviewCreate(
            title="Tech screen",
            type="audio",
            timezone="Europe/Berlin",
            duration_minutes=45,
            interviewers=[user.id],
            notes="initial slot",
        ),
    )


async def _consent_interview(db, tenant, user, cv) -> Interview:
    """Schedule + flip consent so upload-init is allowed."""

    interview = await _scheduled_interview(db, tenant, user, cv)
    row = (
        await db.execute(select(Interview).where(Interview.id == interview["id"]))
    ).scalar_one()
    row.consent_signed_at = datetime.now(timezone.utc)
    await db.commit()
    return row


class TestScheduleInterview:
    async def test_schedule_persists_full_payload(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        result = await _scheduled_interview(db, tenant, user, ctx["cv"])
        assert result["status"] == "scheduled"
        assert result["title"] == "Tech screen"
        assert result["type"] == "audio"
        assert result["timezone"] == "Europe/Berlin"
        assert result["duration_minutes"] == 45
        assert result["created_by"] == user.id
        assert result["version"] == 1
        assert user.id in result["interviewer_ids"]

    async def test_update_with_stale_etag_returns_412(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        with pytest.raises(HTTPException) as exc:
            await service.update_interview(
                db,
                tenant.id,
                first["id"],
                InterviewUpdate(title="renamed"),
                if_match_version=first["version"] + 5,
            )
        assert exc.value.status_code == 412

    async def test_update_replaces_interviewers(self, db, tenant, user):
        from app.modules.auth.models import User

        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        other = User(
            email=f"second-{uuid.uuid4().hex[:6]}@test.com",
            password_hash="x",
            first_name="Other",
            last_name="Interviewer",
            tenant_id=tenant.id,
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        updated = await service.update_interview(
            db,
            tenant.id,
            first["id"],
            InterviewUpdate(interviewers=[user.id, other.id]),
        )
        assert sorted(updated["interviewer_ids"]) == sorted([user.id, other.id])

        rows = (
            (
                await db.execute(
                    select(InterviewInterviewer.user_id).where(
                        InterviewInterviewer.interview_id == first["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        # Both interviewers should be persisted as M2M rows.
        assert sorted(rows) == sorted([user.id, other.id])


class TestUploadSessions:
    async def test_init_persists_session_row(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-1")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        result = await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="rec.mp3",
                mime_type="audio/mpeg",
                size_bytes=1024 * 1024,
                kind="audio",
            ),
            user_id=user.id,
        )
        assert result["upload_id"] == "u-1"
        assert result["session_id"] is not None
        assert result["path"].startswith(str(tenant.id))

        session_row = (
            await db.execute(
                select(UploadSession).where(UploadSession.id == result["session_id"])
            )
        ).scalar_one()
        assert session_row.status == "active"
        assert session_row.s3_upload_id == "u-1"
        assert session_row.uploaded_bytes == 0
        assert session_row.expires_at > datetime.now(timezone.utc)

    async def test_init_rejects_unsupported_mime(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-1")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        with pytest.raises(HTTPException) as exc:
            await service.init_interview_upload(
                db,
                tenant.id,
                interview.id,
                InitUploadRequest(
                    filename="rec.exe",
                    mime_type="application/x-msdownload",
                    size_bytes=1024,
                    kind="audio",
                ),
                user_id=user.id,
            )
        assert exc.value.status_code in (415, 422)

    async def test_init_rejects_oversize_media(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-1")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        with pytest.raises(HTTPException) as exc:
            await service.init_interview_upload(
                db,
                tenant.id,
                interview.id,
                InitUploadRequest(
                    filename="big.mp4",
                    mime_type="video/mp4",
                    size_bytes=600 * 1024 * 1024,
                    kind="video",
                ),
                user_id=user.id,
            )
        assert exc.value.status_code == 413

    async def test_head_returns_offset_and_patch_persists_chunk(
        self, db, tenant, user, monkeypatch
    ):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-2")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        result = await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="rec.mp3",
                mime_type="audio/mpeg",
                size_bytes=10 * 1024 * 1024,
                kind="audio",
            ),
            user_id=user.id,
        )

        head_initial = await service.get_upload_session_head(
            db, tenant.id, interview.id, "u-2"
        )
        assert head_initial["upload_offset"] == 0
        assert head_initial["upload_length"] == 10 * 1024 * 1024

        # Two chunk acks: PATCH equivalent for TUS-style upload.
        await service.ack_uploaded_chunk(
            db,
            tenant.id,
            interview.id,
            "u-2",
            UploadChunkAck(part_number=1, etag="abc", size=8 * 1024 * 1024),
        )
        await service.ack_uploaded_chunk(
            db,
            tenant.id,
            interview.id,
            "u-2",
            UploadChunkAck(part_number=2, etag="def", size=2 * 1024 * 1024),
        )
        head_done = await service.get_upload_session_head(
            db, tenant.id, interview.id, "u-2"
        )
        assert (
            head_done["upload_offset"] == result["part_size"] + (2 * 1024 * 1024)
            or head_done["upload_offset"] == 10 * 1024 * 1024
        )
        assert len(head_done["parts"]) == 2

    async def test_abort_marks_session_aborted(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-3")
        monkeypatch.setattr(s3_module, "abort_multipart_upload", lambda *_a, **_k: True)
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        result = await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="rec.mp3",
                mime_type="audio/mpeg",
                size_bytes=1024,
                kind="audio",
            ),
            user_id=user.id,
        )
        from app.modules.recruitment.schemas import AbortUploadRequest

        await service.abort_interview_upload(
            db,
            tenant.id,
            interview.id,
            AbortUploadRequest(upload_id="u-3"),
        )
        row = (
            await db.execute(
                select(UploadSession).where(UploadSession.id == result["session_id"])
            )
        ).scalar_one()
        assert row.status == "aborted"

    async def test_cleanup_orphans_aborts_expired_sessions(
        self, db, tenant, user, monkeypatch
    ):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "abort_multipart_upload", lambda *_a, **_k: True)
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        expired = UploadSession(
            tenant_id=tenant.id,
            interview_id=interview.id,
            filename="rec.mp3",
            mime_type="audio/mpeg",
            kind="audio",
            total_size=1024,
            uploaded_bytes=0,
            part_size=8 * 1024 * 1024,
            s3_upload_id="orphan",
            s3_key=f"{tenant.id}/interviews/{interview.id}/upload",
            s3_parts=[],
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            created_by=user.id,
        )
        db.add(expired)
        await db.commit()

        aborted = await interview_service.cleanup_orphan_upload_sessions(db)
        assert aborted == 1

        row = (
            await db.execute(
                select(UploadSession).where(UploadSession.id == expired.id)
            )
        ).scalar_one()
        assert row.status == "expired"


class TestTextTranscript:
    async def test_paste_persists_segments_and_skips_av(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        result = await service.paste_text_transcript(
            db,
            tenant.id,
            first["id"],
            TextTranscriptRequest(
                text=(
                    "Interviewer: Hi, tell me about yourself.\n"
                    "Candidate: I have 5 years of backend experience.\n"
                    "Interviewer: What about scaling?\n"
                    "Candidate: I led a 10x growth at my last job."
                )
            ),
        )
        assert result["status"] == "uploaded"
        assert result["type"] == "text_transcript"
        assert result["av_status"] == "skipped"
        assert result["transcription_status"] == "completed"
        assert len(result["segments"]) == 4
        speakers = {s["speaker"] for s in result["segments"]}
        assert speakers == {"speaker_0", "speaker_1"}


class TestArchiveRestoreReplace:
    async def test_archive_then_restore(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        archived = await service.archive_interview(
            db,
            tenant.id,
            user.id,
            first["id"],
            InterviewArchiveRequest(reason="duplicate"),
        )
        assert archived["status"] == "archived"
        assert archived["archived_at"] is not None
        # The list view hides archived rows by default.
        visible = await service.list_interviews(db, tenant.id, ctx["cv"]["id"])
        assert all(i["id"] != first["id"] for i in visible)

        restored = await service.restore_interview(db, tenant.id, user.id, first["id"])
        assert restored["archived_at"] is None
        assert restored["status"] in {"scheduled", "uploaded"}

    async def test_restore_after_retention_returns_410(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        # Force the archived_at into the deep past so the retention
        # window check fires.
        row = (
            await db.execute(select(Interview).where(Interview.id == first["id"]))
        ).scalar_one()
        row.archived_at = datetime.now(timezone.utc) - timedelta(days=120)
        row.status = "archived"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.restore_interview(db, tenant.id, user.id, first["id"])
        assert exc.value.status_code == 410

    async def test_replace_file_drops_media_and_transcript(
        self, db, tenant, user, monkeypatch
    ):
        from app.core import s3 as s3_module
        from app.modules.storage.models import File

        monkeypatch.setattr(s3_module, "delete_file", lambda *_a, **_k: True)
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])

        file_row = File(
            tenant_id=tenant.id,
            name="upload",
            original_name="rec.mp3",
            path="tenant/interviews/x/upload",
            size=1024,
            mime_type="audio/mpeg",
            uploaded_by=user.id,
            entity_type="interview",
            entity_id=first["id"],
        )
        db.add(file_row)
        await db.commit()
        await db.refresh(file_row)

        row = (
            await db.execute(select(Interview).where(Interview.id == first["id"]))
        ).scalar_one()
        row.file_s3_key = "tenant/interviews/x/upload"
        row.file_size_bytes = 1024
        row.file_mime = "audio/mpeg"
        row.audio_file_id = file_row.id
        row.transcript = "redacted"
        row.av_status = "clean"
        await db.commit()

        result = await service.replace_interview_file(db, tenant.id, first["id"])
        assert result["file_s3_key"] is None
        assert result["transcript"] is None
        assert result["audio_file_id"] is None
        assert result["status"] == "scheduled"
        assert result["av_status"] == "pending"


class TestSignedUrl:
    async def test_signed_url_uses_short_ttl(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module
        from app.modules.storage.models import File

        captured: dict = {}

        def fake_presign(path, expires_in=3600):
            captured["path"] = path
            captured["expires_in"] = expires_in
            return f"https://signed/{path}?ttl={expires_in}"

        monkeypatch.setattr(s3_module, "get_presigned_url", fake_presign)

        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])

        file_row = File(
            tenant_id=tenant.id,
            name="upload",
            original_name="rec.mp3",
            path=f"{tenant.id}/interviews/{first['id']}/upload",
            size=1024,
            mime_type="audio/mpeg",
            uploaded_by=user.id,
            entity_type="interview",
            entity_id=first["id"],
        )
        db.add(file_row)
        await db.commit()
        await db.refresh(file_row)

        row = (
            await db.execute(select(Interview).where(Interview.id == first["id"]))
        ).scalar_one()
        row.audio_file_id = file_row.id
        await db.commit()

        result = await service.get_interview_media_url(db, tenant.id, first["id"])
        assert result["expires_in"] == 300
        assert captured["expires_in"] == 300

    async def test_evaluator_blocked_unless_tenant_opts_in(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        with pytest.raises(HTTPException) as exc:
            await service.get_interview_media_url(
                db,
                tenant.id,
                first["id"],
                role="invited_evaluator",
                allow_invited_evaluator_playback=False,
            )
        assert exc.value.status_code == 403


class TestCrossTenant:
    async def test_cross_tenant_get_returns_404(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        first = await _scheduled_interview(db, tenant, user, ctx["cv"])
        other_tenant_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.get_interview(db, other_tenant_id, first["id"])
        assert exc.value.status_code == 404


class TestConsentInheritance:
    """HRP-202 REDO: new interviews inherit the candidate's signed consent."""

    async def _sign_consent(self, db, tenant, user, candidate_id) -> None:
        from app.modules.recruitment.models import ConsentRequest, ConsentTemplate

        template = ConsentTemplate(
            tenant_id=tenant.id,
            name="Default",
            body="I consent to the recording.",
            is_active=True,
        )
        db.add(template)
        await db.flush()
        db.add(
            ConsentRequest(
                tenant_id=tenant.id,
                candidate_id=candidate_id,
                template_id=template.id,
                email="c@example.com",
                token=uuid.uuid4().hex,
                status="signed",
                signed_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=14),
                requested_by=user.id,
            )
        )
        await db.commit()

    async def test_new_interview_inherits_signed_consent(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        await self._sign_consent(db, tenant, user, ctx["candidate"]["id"])
        result = await _scheduled_interview(db, tenant, user, ctx["cv"])
        assert result["consent_signed_at"] is not None

    async def test_without_signed_consent_stays_null(self, db, tenant, user):
        ctx = await _setup_cv(db, tenant, user)
        result = await _scheduled_interview(db, tenant, user, ctx["cv"])
        assert result["consent_signed_at"] is None


class TestUploadValidationFormats:
    """HRP-202 REDO: AVI/MOV media types accepted."""

    def test_avi_and_mov_detected_as_video(self):
        assert interview_service._kind_for_mime("video/x-msvideo") == "video"
        assert interview_service._kind_for_mime("video/avi") == "video"
        assert interview_service._kind_for_mime("video/quicktime") == "video"

    def test_validate_accepts_avi_video(self):
        interview_service._validate_upload_payload("video/x-msvideo", 1024, "video")

    def test_validate_rejects_unknown_mime(self):
        with pytest.raises(HTTPException) as exc:
            interview_service._validate_upload_payload("application/zip", 1024, "video")
        assert exc.value.status_code == 415


class TestAutoProcess:
    """HRP-202 REDO: the auto flag is persisted on complete; the chain
    itself starts from the AV task (after a clean/skipped verdict), so
    complete_interview_upload must NOT dispatch transcription directly."""

    async def _complete(
        self, db, tenant, user, interview, *, auto_process: bool, mock_transcribe
    ):
        from unittest.mock import MagicMock, patch

        from app.modules.recruitment.schemas import CompleteUploadRequest

        with (
            patch(
                "app.core.s3.complete_multipart_upload",
                return_value="s3://loc",
            ),
            patch(
                "app.core.s3.head_object",
                return_value={"ContentLength": 2048},
            ),
            patch(
                "app.modules.recruitment.media_duration.probe_s3_audio_duration",
                return_value=90.0,
            ),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
            patch.object(
                interview_service,
                "enqueue_transcribe",
                new=mock_transcribe,
            ),
        ):
            scan_task.delay = MagicMock()
            return await interview_service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview.id,
                CompleteUploadRequest(
                    upload_id="up-1", parts=[], auto_process=auto_process
                ),
                filename="call.mp3",
                mime_type="audio/mpeg",
                kind="audio",
            )

    async def test_auto_process_persisted_without_direct_dispatch(
        self, db, tenant, user
    ):
        from unittest.mock import AsyncMock

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        mock_transcribe = AsyncMock()
        result = await self._complete(
            db,
            tenant,
            user,
            interview,
            auto_process=True,
            mock_transcribe=mock_transcribe,
        )
        assert result["auto_process"] is True
        assert result["status"] == "uploaded"
        # The AV task owns the chain start — completing the upload must
        # never hand unscanned media to the ASR provider.
        mock_transcribe.assert_not_awaited()

    async def test_manual_upload_keeps_flag_off(self, db, tenant, user):
        from unittest.mock import AsyncMock

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        mock_transcribe = AsyncMock()
        result = await self._complete(
            db,
            tenant,
            user,
            interview,
            auto_process=False,
            mock_transcribe=mock_transcribe,
        )
        assert result["auto_process"] is False
        mock_transcribe.assert_not_awaited()

    async def test_replace_file_clears_auto_process(self, db, tenant, user):
        from unittest.mock import AsyncMock

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        await self._complete(
            db,
            tenant,
            user,
            interview,
            auto_process=True,
            mock_transcribe=AsyncMock(),
        )
        result = await interview_service.replace_interview_file(
            db, tenant.id, interview.id
        )
        # Auto-processing was a per-upload decision; the replacement
        # upload makes its own.
        assert result["auto_process"] is False


class TestTranscriptUploadKind:
    """HRP-385 case 2: pdf/txt transcripts could never be uploaded.

    ``InitUploadRequest.kind`` allowed audio/video only, so both frontend
    surfaces sent ``kind="audio"`` for a transcript; the MIME/kind
    cross-check then rejected it with 422 and the interview was left
    sitting in ``scheduled``.
    """

    async def test_init_accepts_transcript_kind(self, db, tenant, user, monkeypatch):
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-t")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        result = await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="transcript.pdf",
                mime_type="application/pdf",
                size_bytes=4096,
                kind="text_transcript",
            ),
            user_id=user.id,
        )
        assert result["upload_id"] == "u-t"

        session_row = (
            await db.execute(
                select(UploadSession).where(UploadSession.id == result["session_id"])
            )
        ).scalar_one()
        assert session_row.kind == "text_transcript"

        await db.refresh(interview)
        assert interview.status == "uploading"

    async def test_init_rejects_transcript_kind_for_media_mime(
        self, db, tenant, user, monkeypatch
    ):
        """The new kind is cross-checked like audio and video are."""
        from app.core import s3 as s3_module

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-t")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        with pytest.raises(HTTPException) as exc:
            await service.init_interview_upload(
                db,
                tenant.id,
                interview.id,
                InitUploadRequest(
                    filename="rec.mp3",
                    mime_type="audio/mpeg",
                    size_bytes=4096,
                    kind="text_transcript",
                ),
                user_id=user.id,
            )
        assert exc.value.status_code == 422

    async def test_complete_attaches_transcript_and_sets_type(
        self, db, tenant, user
    ):
        from unittest.mock import MagicMock, patch

        from app.modules.recruitment.schemas import CompleteUploadRequest

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch("app.core.s3.head_object", return_value={"ContentLength": 512}),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            result = await interview_service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview.id,
                CompleteUploadRequest(upload_id="up-t", parts=[]),
                filename="transcript.pdf",
                mime_type="application/pdf",
                kind="text_transcript",
            )

        assert result["status"] == "uploaded"
        assert result["type"] == "text_transcript"
        assert result["transcript_file_id"] is not None
        assert result["audio_file_id"] is None
        assert result["video_file_id"] is None
        # Nothing to transcribe — the ASR chain must stay off.
        assert result["auto_process"] is False

    async def test_uploaded_transcript_text_is_extracted_and_analysable(
        self, db, tenant, user
    ):
        """HRP-385: attaching the file is not enough.

        Without extraction the interview lands with
        ``transcription_status="pending"`` and no transcript, so
        "Transcribe" refuses it (audio/video only) and "Analyze" refuses
        it (needs a finished transcription) — the upload would be a dead
        end one click later.
        """
        from unittest.mock import MagicMock, patch

        from app.modules.recruitment.schemas import CompleteUploadRequest

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        body = b"Interviewer: Tell me about yourself.\nCandidate: I ship backends.\n"

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch("app.core.s3.head_object", return_value={"ContentLength": len(body)}),
            patch("app.core.s3.download_bytes", return_value=body),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            result = await interview_service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview.id,
                CompleteUploadRequest(upload_id="up-txt", parts=[]),
                filename="transcript.txt",
                mime_type="text/plain",
                kind="text_transcript",
            )

        assert result["status"] == "uploaded"
        assert result["type"] == "text_transcript"
        assert result["transcript_file_id"] is not None
        assert result["transcription_status"] == "completed"
        # A real file was uploaded, so the AV scan still has to run —
        # unlike the paste path, which has nothing to scan.
        assert result["av_status"] == "pending"
        assert "I ship backends" in (result["transcript"] or "")
        # Speaker prefixes become segments, same as the paste path.
        assert len(result["segments"]) == 2

    async def test_unextractable_transcript_still_uploads(self, db, tenant, user):
        """A scanned/image-only PDF must not fail the finished upload."""
        from unittest.mock import MagicMock, patch

        from app.modules.recruitment.schemas import CompleteUploadRequest

        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch("app.core.s3.head_object", return_value={"ContentLength": 10}),
            patch(
                "app.core.s3.download_bytes",
                side_effect=RuntimeError("unreadable"),
            ),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            result = await interview_service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview.id,
                CompleteUploadRequest(upload_id="up-bad", parts=[]),
                filename="scan.pdf",
                mime_type="application/pdf",
                kind="text_transcript",
            )

        assert result["status"] == "uploaded"
        assert result["transcript_file_id"] is not None


class TestUploadSwitchesInterviewType:
    """HRP-405: the uploaded file's kind becomes ``interview.type``.

    The frontend asks for confirmation first (see
    ``requiresTypeSwitchConfirm``); these pin the server side of that
    contract for every case in the ticket.
    """

    async def _complete_with_kind(self, db, tenant, user, interview, kind, mime):
        from unittest.mock import MagicMock, patch

        from app.modules.recruitment.schemas import CompleteUploadRequest

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch("app.core.s3.head_object", return_value={"ContentLength": 512}),
            patch(
                "app.modules.recruitment.media_duration.probe_s3_audio_duration",
                return_value=12.0,
            ),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            return await interview_service.complete_interview_upload(
                db,
                tenant.id,
                user.id,
                interview.id,
                CompleteUploadRequest(upload_id="up-1", parts=[]),
                filename=f"file.{kind}",
                mime_type=mime,
                kind=kind,
            )

    @pytest.mark.parametrize(
        ("declared", "uploaded", "mime"),
        [
            # Case 1 — audio / transcript interview receiving video.
            ("audio", "video", "video/mp4"),
            ("text_transcript", "video", "video/webm"),
            # Case 2 — video / transcript interview receiving audio.
            ("video", "audio", "audio/mpeg"),
            ("text_transcript", "audio", "audio/wav"),
            # Case 3 — video / audio interview receiving a transcript.
            ("video", "text_transcript", "application/pdf"),
            ("audio", "text_transcript", "text/plain"),
            # Case 4 — "I'll decide later" adopts the uploaded kind.
            ("undecided", "video", "video/mp4"),
            ("undecided", "audio", "audio/mpeg"),
            ("undecided", "text_transcript", "application/pdf"),
        ],
    )
    async def test_type_follows_uploaded_file(
        self, db, tenant, user, declared, uploaded, mime
    ):
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])
        interview.type = declared
        await db.commit()

        result = await self._complete_with_kind(
            db, tenant, user, interview, uploaded, mime
        )
        assert result["type"] == uploaded
        assert result["status"] == "uploaded"

    async def test_complete_rejects_kind_the_session_was_not_opened_for(
        self, db, tenant, user, monkeypatch
    ):
        """HRP-385: init and complete each carry ``kind`` independently.

        Finalising an audio upload (500 MB ceiling) as a transcript would
        otherwise park an oversize blob in ``transcript_file_id``, past the
        10 MB transcript cap promised at init.
        """
        from unittest.mock import MagicMock, patch

        from app.core import s3 as s3_module
        from app.modules.recruitment.schemas import CompleteUploadRequest

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-x")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="rec.mp3",
                mime_type="audio/mpeg",
                size_bytes=1024,
                kind="audio",
            ),
            user_id=user.id,
        )

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch(
                "app.core.s3.head_object",
                return_value={"ContentLength": 400 * 1024 * 1024},
            ),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            with pytest.raises(HTTPException) as exc:
                await interview_service.complete_interview_upload(
                    db,
                    tenant.id,
                    user.id,
                    interview.id,
                    CompleteUploadRequest(upload_id="u-x", parts=[]),
                    filename="transcript.pdf",
                    mime_type="application/pdf",
                    kind="text_transcript",
                )
        assert exc.value.status_code == 409

    async def test_complete_rejects_object_above_the_kind_ceiling(
        self, db, tenant, user, monkeypatch
    ):
        """S3 does not enforce the ceiling promised at init — re-check it."""
        from unittest.mock import MagicMock, patch

        from app.core import s3 as s3_module
        from app.modules.recruitment.schemas import CompleteUploadRequest

        monkeypatch.setattr(s3_module, "init_multipart_upload", lambda *_a, **_k: "u-y")
        ctx = await _setup_cv(db, tenant, user)
        interview = await _consent_interview(db, tenant, user, ctx["cv"])

        await service.init_interview_upload(
            db,
            tenant.id,
            interview.id,
            InitUploadRequest(
                filename="transcript.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                kind="text_transcript",
            ),
            user_id=user.id,
        )

        with (
            patch("app.core.s3.complete_multipart_upload", return_value="s3://loc"),
            patch(
                "app.core.s3.head_object",
                return_value={"ContentLength": 40 * 1024 * 1024},
            ),
            patch(
                "app.modules.recruitment.tasks.scan_interview_media_task"
            ) as scan_task,
        ):
            scan_task.delay = MagicMock()
            with pytest.raises(HTTPException) as exc:
                await interview_service.complete_interview_upload(
                    db,
                    tenant.id,
                    user.id,
                    interview.id,
                    CompleteUploadRequest(upload_id="u-y", parts=[]),
                    filename="transcript.pdf",
                    mime_type="application/pdf",
                    kind="text_transcript",
                )
        assert exc.value.status_code == 413
