"""HRP-386 / 418 / 419: Schedule modal payload, list order, archive, email.

Complements ``test_hrp202_interview_upload.py`` (upload mechanics) — this
module covers what the Interviews block and the "Interview scheduled"
notification promise.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.recruitment import interview_service, service
from app.modules.recruitment.manager_assessment_schemas import RoundCreate
from app.modules.recruitment.models import AIAssessment, Interview
from app.modules.recruitment.notifications import _resolve_interview_scheduled
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    InterviewCreate,
    InterviewUpdate,
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
        VacancyCreate(title=f"Senior Backend {uuid.uuid4().hex[:6]}"),
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"Ada-{uuid.uuid4().hex[:4]}",
            last_name=f"Lovelace-{uuid.uuid4().hex[:4]}",
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


class TestScheduleModalPayload:
    """HRP-386 — Round, interviewers, list order."""

    @pytest.mark.asyncio
    async def test_round_is_persisted_and_returned(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        from app.modules.recruitment import manager_assessment_service as ma

        rnd = await ma.create_round(
            db, tenant.id, user.id, setup["cv"]["id"], RoundCreate(type="interview")
        )
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(title="Tech screening", round_id=rnd["id"]),
        )
        assert created["round_id"] == rnd["id"]

        fetched = await service.get_interview(db, tenant.id, created["id"])
        assert fetched["round_id"] == rnd["id"]

    @pytest.mark.asyncio
    async def test_round_from_another_cv_is_rejected(self, db, tenant, user):
        mine = await _setup_cv(db, tenant, user)
        other = await _setup_cv(db, tenant, user)
        from app.modules.recruitment import manager_assessment_service as ma

        foreign = await ma.create_round(
            db, tenant.id, user.id, other["cv"]["id"], RoundCreate(type="interview")
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_interview(
                db,
                tenant.id,
                user.id,
                mine["cv"]["id"],
                InterviewCreate(title="Wrong round", round_id=foreign["id"]),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_round_can_be_detached_on_update(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        from app.modules.recruitment import manager_assessment_service as ma

        rnd = await ma.create_round(
            db, tenant.id, user.id, setup["cv"]["id"], RoundCreate(type="interview")
        )
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(title="Tech screening", round_id=rnd["id"]),
        )
        updated = await service.update_interview(
            db, tenant.id, created["id"], InterviewUpdate(round_id=None)
        )
        assert updated["round_id"] is None

        # Not touching the field at all keeps the current value.
        relinked = await service.update_interview(
            db, tenant.id, created["id"], InterviewUpdate(round_id=rnd["id"])
        )
        untouched = await service.update_interview(
            db, tenant.id, created["id"], InterviewUpdate(title="Renamed")
        )
        assert relinked["round_id"] == rnd["id"]
        assert untouched["round_id"] == rnd["id"]

    @pytest.mark.asyncio
    async def test_explicit_null_clears_the_nullable_fields(self, db, tenant, user):
        """The Edit modal sends ``null`` to clear — it must not be a no-op.

        Under an ``is not None`` guard the Clear button returned 200 with
        the old value still in the row, which read as "the save silently
        failed". Every nullable column the modal owns now goes through
        ``model_fields_set``.
        """
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(
                title="Tech screening",
                interview_date=datetime.now(timezone.utc) + timedelta(days=2),
                duration_minutes=60,
                notes="Ask about the sharding project",
            ),
        )
        assert created["title"] == "Tech screening"

        cleared = await service.update_interview(
            db,
            tenant.id,
            created["id"],
            InterviewUpdate(
                title=None,
                interview_date=None,
                duration_minutes=None,
                notes=None,
            ),
        )
        assert cleared["title"] is None
        assert cleared["interview_date"] is None
        assert cleared["duration_minutes"] is None
        assert cleared["notes"] is None

    @pytest.mark.asyncio
    async def test_untouched_fields_keep_their_value(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(
                title="Tech screening", duration_minutes=45, notes="Bring the rubric"
            ),
        )
        updated = await service.update_interview(
            db, tenant.id, created["id"], InterviewUpdate(status="scheduled")
        )
        assert updated["title"] == "Tech screening"
        assert updated["duration_minutes"] == 45
        assert updated["notes"] == "Bring the rubric"

    @pytest.mark.asyncio
    async def test_interviewers_may_be_empty(self, db, tenant, user):
        """The creator is not silently promoted to interviewer (HRP-386)."""
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(title="Unassigned slot"),
        )
        assert created["interviewer_ids"] == []
        assert created["interviewer_id"] is None

    @pytest.mark.asyncio
    async def test_clearing_interviewers_clears_primary(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(title="Slot", interviewers=[user.id]),
        )
        assert created["interviewer_ids"] == [user.id]

        cleared = await service.update_interview(
            db, tenant.id, created["id"], InterviewUpdate(interviewers=[])
        )
        assert cleared["interviewer_ids"] == []
        assert cleared["interviewer_id"] is None

    @pytest.mark.asyncio
    async def test_new_interview_is_listed_first(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        first = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Older")
        )
        second = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Newer")
        )
        rows = await service.list_interviews(db, tenant.id, setup["cv"]["id"])
        assert [r["id"] for r in rows][:2] == [second["id"], first["id"]]

    @pytest.mark.asyncio
    async def test_read_exposes_created_at(self, db, tenant, user):
        """HRP-418 renders ``added yyyy-mm-dd`` from this field."""
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Slot")
        )
        assert created["created_at"] is not None

    @pytest.mark.asyncio
    async def test_interviewer_options_list_tenant_users(self, db, tenant, user):
        options = await service.list_interviewer_options(db, tenant.id)
        assert any(o["id"] == user.id for o in options)
        assert all({"id", "full_name", "email"} <= set(o) for o in options)


class TestArchiveSideEffects:
    """HRP-418 — round link + AI-score flag + retention purge."""

    @pytest.mark.asyncio
    async def test_archive_detaches_round_and_flags_ai_scores(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        from app.modules.recruitment import manager_assessment_service as ma

        rnd = await ma.create_round(
            db, tenant.id, user.id, setup["cv"]["id"], RoundCreate(type="interview")
        )
        created = await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(title="Tech screening", round_id=rnd["id"]),
        )
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=created["id"],
                competence_id=uuid.uuid4(),
                score=4.0,
                status="assessed",
            )
        )
        await db.commit()

        archived = await service.archive_interview(
            db, tenant.id, user.id, created["id"]
        )
        assert archived["archived_at"] is not None
        assert archived["round_id"] is None

        scores = (
            (
                await db.execute(
                    select(AIAssessment).where(
                        AIAssessment.interview_id == created["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        # Historical record kept, but flagged as coming from an archived
        # source.
        assert scores and all(s.source_archived for s in scores)

        restored = await service.restore_interview(
            db, tenant.id, user.id, created["id"]
        )
        assert restored["archived_at"] is None
        for row in scores:
            await db.refresh(row)
        assert not any(s.source_archived for s in scores)

    @pytest.mark.asyncio
    async def test_archived_rows_are_hidden_unless_requested(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Slot")
        )
        await service.archive_interview(db, tenant.id, user.id, created["id"])

        active = await service.list_interviews(db, tenant.id, setup["cv"]["id"])
        with_archived = await service.list_interviews(
            db, tenant.id, setup["cv"]["id"], include_archived=True
        )
        assert created["id"] not in [r["id"] for r in active]
        assert created["id"] in [r["id"] for r in with_archived]

    @pytest.mark.asyncio
    async def test_purge_drops_media_but_keeps_metadata(
        self, db, tenant, user, monkeypatch
    ):
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Slot")
        )
        row = (
            await db.execute(select(Interview).where(Interview.id == created["id"]))
        ).scalar_one()
        row.file_s3_key = f"{tenant.id}/interviews/{row.id}/upload"
        row.archived_at = datetime.now(timezone.utc) - timedelta(
            days=interview_service.ARCHIVE_RETENTION_DAYS + 1
        )
        row.status = "archived"
        await db.commit()

        deleted: list[str] = []
        monkeypatch.setattr(
            "app.core.s3.delete_file", lambda key: deleted.append(key) or True
        )

        # The sweeper is deliberately cross-tenant (celery beat, no actor),
        # so the assertions pin THIS row rather than a global count — the
        # shared test database may carry expired rows from other modules.
        purged = await interview_service.purge_expired_archived_interviews(db)
        assert purged >= 1
        assert f"{tenant.id}/interviews/{row.id}/upload" in deleted

        await db.refresh(row)
        assert row.file_s3_key is None
        purged_at = row.purged_at
        assert purged_at is not None
        # Metadata survives for audit.
        assert row.title == "Slot"
        assert row.archived_at is not None

        # Idempotent — a second sweep leaves the row (and S3) alone.
        deleted.clear()
        await interview_service.purge_expired_archived_interviews(db)
        await db.refresh(row)
        assert row.purged_at == purged_at
        assert deleted == []

    @pytest.mark.asyncio
    async def test_purge_removes_the_file_rows_too(self, db, tenant, user, monkeypatch):
        """The blob goes, so its ``files`` row must go with it.

        ``complete_interview_upload`` writes one row per uploaded media
        file; nulling only the interview's FK left them behind pointing at
        an object that no longer exists, and every storage listing kept
        counting them.
        """
        from app.modules.storage.models import File

        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Slot")
        )
        row = (
            await db.execute(select(Interview).where(Interview.id == created["id"]))
        ).scalar_one()
        key = f"{tenant.id}/interviews/{row.id}/upload"
        media = File(
            tenant_id=tenant.id,
            name="upload",
            original_name="interview.mp3",
            path=key,
            size=1024,
            mime_type="audio/mpeg",
            uploaded_by=user.id,
            entity_type="interview",
            entity_id=row.id,
        )
        db.add(media)
        await db.flush()
        media_id = media.id
        row.audio_file_id = media_id
        row.file_s3_key = key
        row.archived_at = datetime.now(timezone.utc) - timedelta(
            days=interview_service.ARCHIVE_RETENTION_DAYS + 1
        )
        row.status = "archived"
        await db.commit()

        monkeypatch.setattr("app.core.s3.delete_file", lambda _key: True)
        await interview_service.purge_expired_archived_interviews(db)

        await db.refresh(row)
        assert row.audio_file_id is None
        leftover = (
            await db.execute(select(File).where(File.id == media_id))
        ).scalar_one_or_none()
        assert leftover is None

    @pytest.mark.asyncio
    async def test_recently_archived_is_not_purged(self, db, tenant, user):
        setup = await _setup_cv(db, tenant, user)
        created = await service.create_interview(
            db, tenant.id, user.id, setup["cv"]["id"], InterviewCreate(title="Slot")
        )
        await service.archive_interview(db, tenant.id, user.id, created["id"])
        await interview_service.purge_expired_archived_interviews(db)
        row = (
            await db.execute(select(Interview).where(Interview.id == created["id"]))
        ).scalar_one()
        assert row.purged_at is None


class TestScheduledNotification:
    """HRP-419 — recipients, candidate name, vacancy, datetime format."""

    @pytest.mark.asyncio
    async def test_payload_carries_full_name_vacancy_and_local_time(
        self, db, tenant, user, monkeypatch
    ):
        setup = await _setup_cv(db, tenant, user)
        published: list[tuple[str, dict]] = []

        async def _capture(event, payload):
            published.append((event, payload))

        monkeypatch.setattr("app.modules.recruitment.common._publish_event", _capture)
        monkeypatch.setattr(
            "app.modules.recruitment.interview_service._publish_event", _capture
        )

        when = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
        await service.create_interview(
            db,
            tenant.id,
            user.id,
            setup["cv"]["id"],
            InterviewCreate(
                title="Tech screening",
                interview_date=when,
                timezone="Europe/Berlin",
                interviewers=[user.id],
            ),
        )

        assert published, "interview.scheduled was not published"
        event, payload = published[-1]
        assert event == "recruitment.interview.scheduled"
        assert payload["candidate_name"] == setup["candidate"]["full_name"]
        assert payload["candidate_name"] is not None
        assert payload["vacancy_title"] == setup["vacancy"]["title"]
        # Europe/Berlin is UTC+2 in May.
        assert payload["interview_date"] == "2026-05-28 14:00"
        assert payload["interviewer_ids"] == [str(user.id)]

    @pytest.mark.asyncio
    async def test_recipients_are_interviewers_only(self, db, tenant, user):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        recipients = await _resolve_interview_scheduled(
            db,
            tenant.id,
            {
                "interviewer_ids": [str(user.id)],
                "owner_id": str(uuid.uuid4()),
                "interview_date_iso": future.isoformat(),
            },
        )
        assert [r.id for r in recipients] == [user.id]

    @pytest.mark.asyncio
    async def test_no_recipients_without_interviewers(self, db, tenant, user):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        recipients = await _resolve_interview_scheduled(
            db,
            tenant.id,
            {
                "interviewer_ids": [],
                "owner_id": str(user.id),
                "interview_date_iso": future.isoformat(),
            },
        )
        assert recipients == []

    @pytest.mark.asyncio
    async def test_no_email_for_past_interviews(self, db, tenant, user):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        recipients = await _resolve_interview_scheduled(
            db,
            tenant.id,
            {
                "interviewer_ids": [str(user.id)],
                "interview_date_iso": past.isoformat(),
            },
        )
        assert recipients == []

    @pytest.mark.asyncio
    async def test_undated_interview_still_notifies(self, db, tenant, user):
        recipients = await _resolve_interview_scheduled(
            db,
            tenant.id,
            {"interviewer_ids": [str(user.id)], "interview_date_iso": None},
        )
        assert [r.id for r in recipients] == [user.id]
