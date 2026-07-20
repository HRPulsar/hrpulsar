"""HRP-181 REDO post-review hardening.

Covers the regressions caught by the post-release code review:

* A1: ``list_candidates`` keeps person_id=None rows visible.
* A4: ``_check_is_employee`` short-circuits on ``person_id=None`` (would
  otherwise misclassify external candidates as employees).
* A6: ``add_candidate_to_vacancy_manual`` refuses to re-link an archived
  candidate.
* A8: ``replace_vacancy_stages_override`` rejects all-terminal / empty
  funnels and duplicate codes.
* A2: ``_first_non_terminal_stage_id`` picks from the per-vacancy
  override only (FR-08 all-or-nothing).
* B3+B5: resume endpoints filter ``file_type='resume'`` so interview
  media never leaks through them.
* C4: ``get_resumes_parsing_status`` scopes empty-file_ids polls by
  ``File.uploaded_by``.
* C6: ``finalize_candidates_from_parsed`` skips files whose parse hasn't
  reached ``completed``.
* S5: within-batch duplicate emails are skipped, not committed twice.
* E1: ``gdpr_erase`` blanks the canonical Candidate denorm columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.recruitment import gdpr_service, service
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
)
from app.modules.recruitment.schemas import (
    BatchFinalizeFile,
    BatchFinalizeRequest,
    CandidateManualCreate,
    VacancyCreate,
    VacancyStageReplaceItem,
    VacancyStagesReplace,
)
from app.modules.storage.models import File
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _make_vacancy(db: AsyncSession, tenant_id, user_id) -> dict:
    await service.seed_default_recruitment_stages(db, tenant_id)
    await db.commit()
    vacancy = await service.create_vacancy(
        db,
        tenant_id,
        user_id,
        VacancyCreate(title=f"V-{uuid.uuid4().hex[:6]}"),
    )
    return vacancy


# ---------------------------------------------------------------------------
# A1 — list_candidates uses LEFT OUTER JOIN
# ---------------------------------------------------------------------------


class TestListCandidatesShowsExternal:
    async def test_external_candidate_appears(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="External Candidate",
                email="external@example.com",
            ),
        )
        items, total = await service.list_candidates(db, tenant.id)
        names = [row["full_name"] for row in items]
        assert "External Candidate" in names
        assert total >= 1
        # ``person`` must be null on the external row and the response
        # must still expose the canonical email/full_name fallbacks.
        ext = next(row for row in items if row["full_name"] == "External Candidate")
        assert ext["person"] is None
        assert ext["email"] == "external@example.com"


# ---------------------------------------------------------------------------
# A4 — _check_is_employee guards person_id=None
# ---------------------------------------------------------------------------


class TestCheckIsEmployeeNone:
    async def test_none_short_circuits(self, db: AsyncSession, tenant):
        result = await service._check_is_employee(db, tenant.id, None)
        assert result is False


# ---------------------------------------------------------------------------
# A6 — archived candidate cannot be re-linked
# ---------------------------------------------------------------------------


class TestArchivedCandidateLink:
    async def test_link_archived_raises_409(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        first = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Soft Deleted",
                email="soft@example.com",
            ),
        )
        await service.archive_candidate(db, tenant.id, first["id"])

        other_vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title="V-Other"),
        )
        with pytest.raises(HTTPException) as exc:
            await service.add_candidate_to_vacancy_manual(
                db,
                tenant.id,
                user.id,
                other_vacancy["id"],
                CandidateManualCreate(
                    full_name="Soft Deleted",
                    email="soft@example.com",
                    link_candidate_id=first["id"],
                ),
            )
        assert exc.value.status_code == 409
        assert isinstance(exc.value.detail, dict)
        assert exc.value.detail["code"] == "candidate_archived"


# ---------------------------------------------------------------------------
# A8 — replace_vacancy_stages_override payload validation
# ---------------------------------------------------------------------------


class TestVacancyStagesReplaceValidation:
    async def test_empty_payload_rejected(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(HTTPException) as exc:
            await service.replace_vacancy_stages_override(
                db,
                tenant.id,
                vacancy["id"],
                VacancyStagesReplace(stages=[]),
            )
        assert exc.value.status_code == 422

    async def test_all_terminal_payload_rejected(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(HTTPException) as exc:
            await service.replace_vacancy_stages_override(
                db,
                tenant.id,
                vacancy["id"],
                VacancyStagesReplace(
                    stages=[
                        VacancyStageReplaceItem(
                            name="Hired",
                            code="hired",
                            sort_order=10,
                            stage_type="terminal_positive",
                        ),
                        VacancyStageReplaceItem(
                            name="Rejected",
                            code="rejected",
                            sort_order=20,
                            stage_type="terminal_negative",
                        ),
                    ]
                ),
            )
        assert exc.value.status_code == 422
        assert "active" in exc.value.detail.lower()

    async def test_duplicate_codes_rejected(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(HTTPException) as exc:
            await service.replace_vacancy_stages_override(
                db,
                tenant.id,
                vacancy["id"],
                VacancyStagesReplace(
                    stages=[
                        VacancyStageReplaceItem(
                            name="A",
                            code="dup",
                            sort_order=10,
                            stage_type="active",
                        ),
                        VacancyStageReplaceItem(
                            name="B",
                            code="dup",
                            sort_order=20,
                            stage_type="terminal_positive",
                        ),
                    ]
                ),
            )
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# A2 — override is all-or-nothing
# ---------------------------------------------------------------------------


class TestStageOverrideIsolation:
    async def test_first_non_terminal_picks_from_override_only(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        # Replace funnel with an override that lands new candidates on a
        # different sort_order than the tenant default.
        override = await service.replace_vacancy_stages_override(
            db,
            tenant.id,
            vacancy["id"],
            VacancyStagesReplace(
                stages=[
                    VacancyStageReplaceItem(
                        name="Intake",
                        code="intake",
                        sort_order=15,
                        stage_type="active",
                    ),
                    VacancyStageReplaceItem(
                        name="Done",
                        code="done",
                        sort_order=99,
                        stage_type="terminal_positive",
                    ),
                ]
            ),
        )
        landing = await service._first_non_terminal_stage_id(
            db, tenant.id, vacancy["id"]
        )
        override_ids = {item["id"] for item in override}
        assert landing in override_ids


# ---------------------------------------------------------------------------
# B3+B5 — resume endpoints filter file_type='resume'
# ---------------------------------------------------------------------------


class TestResumeEndpointsFileTypeGuard:
    async def test_interview_file_not_listed_as_resume(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        created = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Mike Mic",
                email="mike@example.com",
            ),
        )
        candidate_id = created["id"]
        # Drop a non-resume CandidateFile (e.g. an interview audio row).
        interview_file = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=candidate_id,
            file_id=None,
            file_type="interview_audio",
            original_filename="interview.mp3",
            mime_type="audio/mpeg",
            file_size=1234,
            parse_status="completed",
        )
        db.add(interview_file)
        await db.flush()

        listed = await service.list_candidate_resumes(
            db, tenant.id, candidate_id
        )
        assert all(item["file_type"] == "resume" for item in listed)

        with pytest.raises(HTTPException) as exc:
            await service.update_resume_parsed_data(
                db, tenant.id, interview_file.id, {"any": "thing"}
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# C4 — parsing-status scopes empty-file_ids polls by uploaded_by
# ---------------------------------------------------------------------------


class TestParsingStatusScopedByUser:
    async def test_other_users_files_excluded(
        self, db: AsyncSession, tenant, user
    ):
        # Spin up a second user in the same tenant so we can assert their
        # detached files don't leak into the first user's poll.
        other = User(
            email=f"other-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Other",
            last_name="User",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(other)
        await db.flush()

        vacancy = await _make_vacancy(db, tenant.id, user.id)
        # File owned by ``user``.
        mine = File(
            tenant_id=tenant.id,
            name="mine",
            original_name="mine.pdf",
            path="t/r/mine.pdf",
            size=1,
            mime_type="application/pdf",
            uploaded_by=user.id,
        )
        # File owned by another recruiter on a different batch.
        theirs = File(
            tenant_id=tenant.id,
            name="theirs",
            original_name="theirs.pdf",
            path="t/r/theirs.pdf",
            size=1,
            mime_type="application/pdf",
            uploaded_by=other.id,
        )
        db.add_all([mine, theirs])
        await db.flush()

        for f in (mine, theirs):
            db.add(
                CandidateFile(
                    tenant_id=tenant.id,
                    candidate_id=None,
                    file_id=f.id,
                    file_type="resume",
                    original_filename=f.original_name,
                    mime_type="application/pdf",
                    file_size=1,
                    parse_status="pending",
                )
            )
        await db.flush()

        status = await service.get_resumes_parsing_status(
            db, tenant.id, user.id, vacancy["id"], None
        )
        filenames = {row["original_filename"] for row in status["files"]}
        assert "mine.pdf" in filenames
        assert "theirs.pdf" not in filenames


# ---------------------------------------------------------------------------
# C6 + S5 — finalize skips pending parses and intra-batch duplicates
# ---------------------------------------------------------------------------


class TestFinalizeSkipsNonCompleted:
    async def test_pending_file_skipped(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        cf = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=None,
            file_id=None,
            file_type="resume",
            original_filename="pending.pdf",
            mime_type="application/pdf",
            file_size=1,
            parse_status="pending",
        )
        db.add(cf)
        await db.flush()

        result = await service.finalize_candidates_from_parsed(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            BatchFinalizeRequest(
                files=[BatchFinalizeFile(file_id=cf.id, link_candidate_id=None)]
            ),
        )
        assert result["created"] == []
        assert result["linked"] == []
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "parse_not_completed"

    async def test_intra_batch_duplicate_email_skipped(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        cfs = []
        for i in range(2):
            cf = CandidateFile(
                tenant_id=tenant.id,
                candidate_id=None,
                file_id=None,
                file_type="resume",
                original_filename=f"r{i}.pdf",
                mime_type="application/pdf",
                file_size=1,
                parse_status="completed",
                parsed_data={
                    "first_name": "Dup",
                    "last_name": f"Twin{i}",
                    "contacts": {"email": "dup@example.com"},
                },
            )
            db.add(cf)
            cfs.append(cf)
        await db.flush()

        result = await service.finalize_candidates_from_parsed(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            BatchFinalizeRequest(
                files=[
                    BatchFinalizeFile(file_id=cfs[0].id, link_candidate_id=None),
                    BatchFinalizeFile(file_id=cfs[1].id, link_candidate_id=None),
                ]
            ),
        )
        assert len(result["created"]) == 1
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "duplicate_email"


# ---------------------------------------------------------------------------
# E1 — gdpr_erase blanks canonical Candidate columns
# ---------------------------------------------------------------------------


class TestGdprEraseCanonical:
    async def test_canonical_pii_redacted(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        created = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Erase Me",
                email="erase@example.com",
                phone="+1-555",
                linkedin_url="https://linkedin.com/in/erase",
                location="Berlin",
                current_position="Engineer",
                years_of_experience=5,
            ),
        )
        # Stamp some resume payload so the erase path also clears it.
        candidate = await db.get(Candidate, created["id"])
        candidate.parsed_resume_jsonb = {"summary": "secret"}
        await db.commit()

        await gdpr_service.gdpr_erase(
            db, tenant.id, user.id, created["id"]
        )

        await db.refresh(candidate)
        assert candidate.full_name == "redacted"
        assert candidate.email and candidate.email.startswith("redacted-")
        assert candidate.phone is None
        assert candidate.linkedin_url is None
        assert candidate.location is None
        assert candidate.current_position is None
        assert candidate.years_of_experience is None
        assert candidate.parsed_resume_jsonb == {"redacted": True}
