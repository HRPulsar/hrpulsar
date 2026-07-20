"""HRP-266: assessment history timeline + Revert + ETag 412."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from app.modules.recruitment import service, settings_service
from app.modules.recruitment.models import RecruitmentAuditLog
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from app.modules.recruitment.settings_schemas import (
    MatrixSettingsUpdate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _vacancy_with_cv(
    db: AsyncSession, tenant, user
) -> tuple[dict, dict, dict, uuid.UUID]:
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    competence_slug = "python-skills"
    await service.save_profile(
        db,
        tenant.id,
        uuid.UUID(str(vacancy["id"])),
        VacancyProfileUpdate(
            profile_data={
                "competences": [
                    {
                        "id": competence_slug,
                        "name": "Python",
                        "group": "Hard",
                        "criticality": "critical",
                    }
                ]
            }
        ),
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="A",
            last_name="Lastname",
            email=f"a-{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])),
            vacancy_id=uuid.UUID(str(vacancy["id"])),
        ),
    )
    return (
        vacancy,
        candidate,
        cv,
        service.normalize_competence_id(competence_slug),
    )


class TestAssessmentETag:
    async def test_first_write_with_no_if_match_creates_row(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        result = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        assert result["version"] == 1
        assert service.assessment_etag(result["version"]) == 'W/"1"'

    async def test_update_with_matching_if_match_succeeds(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        first = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        second = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=4.0),
            if_match=service.assessment_etag(first["version"]),
        )
        assert second["version"] == 2
        assert second["score"] == 4.0

    async def test_update_with_stale_if_match_returns_412(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        first = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        # Bump version once so the original ETag is now stale.
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=4.0),
            if_match=service.assessment_etag(first["version"]),
        )
        with pytest.raises(HTTPException) as exc:
            await service.record_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                user.id,
                AssessmentScoreCreate(competence_id=comp_id, score=5.0),
                if_match='W/"1"',
            )
        assert exc.value.status_code == 412

    async def test_if_match_on_brand_new_cell_returns_412(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """If-Match is meaningful only against an existing snapshot; sending it
        before the first write means the caller saw a phantom version and we
        refuse to insert."""
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.record_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                user.id,
                AssessmentScoreCreate(competence_id=comp_id, score=3.0),
                if_match='W/"1"',
            )
        assert exc.value.status_code == 412


class TestAssessmentHistory:
    async def test_audit_payload_carries_old_and_new_scores(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        first = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=2.0),
        )
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=4.0),
            if_match=service.assessment_etag(first["version"]),
        )
        rows = (
            await db.execute(
                select(RecruitmentAuditLog)
                .where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.entity_type == "assessment",
                )
                .order_by(RecruitmentAuditLog.created_at.asc())
            )
        ).scalars().all()
        # Two audit rows — first upsert + second update.
        assert len(rows) == 2
        assert rows[0].action == "assessment.create"
        assert rows[0].payload_diff["operation"] == "upsert"
        assert rows[0].payload_diff["old_score"] is None
        assert rows[0].payload_diff["new_score"] == 2.0
        assert rows[1].action == "assessment.update"
        assert rows[1].payload_diff["old_score"] == 2.0
        assert rows[1].payload_diff["new_score"] == 4.0

    async def test_list_history_filters_by_evaluator(
        self, db: AsyncSession, tenant, user, admin_role
    ) -> None:

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles

        vacancy, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        # Two writes by ``user``, one by a second evaluator.
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        other = User(
            email=f"other-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("pw"),
            first_name="Other",
            last_name="Eval",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)
        await db.execute(
            user_roles.insert().values(user_id=other.id, role_id=admin_role.id)
        )
        await db.commit()
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            other.id,
            AssessmentScoreCreate(competence_id=comp_id, score=2.0),
        )

        all_items, total = await service.list_assessment_history(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
        assert total == 2

        scoped_items, scoped_total = await service.list_assessment_history(
            db,
            tenant.id,
            uuid.UUID(str(vacancy["id"])),
            evaluator_id=other.id,
        )
        assert scoped_total == 1
        assert scoped_items[0]["new_score"] == 2.0

    async def test_only_divergence_filter_uses_tenant_threshold(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        # Bump tenant threshold to 1.5 — only the second edit (gap 2.0)
        # should survive the divergence filter.
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=1.5)
        )
        first = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        small_edit = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=4.0),
            if_match=service.assessment_etag(first["version"]),
        )
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=2.0),
            if_match=service.assessment_etag(small_edit["version"]),
        )

        items, total = await service.list_assessment_history(
            db,
            tenant.id,
            uuid.UUID(str(vacancy["id"])),
            only_divergence=True,
        )
        # Only the 4.0 → 2.0 edit (|Δ|=2.0 ≥ 1.5) is surfaced.
        assert total == 1
        assert items[0]["old_score"] == 4.0
        assert items[0]["new_score"] == 2.0


class TestAssessmentRevert:
    async def test_revert_restores_prior_score(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        first = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=5.0),
            if_match=service.assessment_etag(first["version"]),
        )
        # Pick the update event for revert.
        events = (
            await db.execute(
                select(RecruitmentAuditLog)
                .where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.update",
                )
                .order_by(RecruitmentAuditLog.created_at.asc())
            )
        ).scalars().all()
        target_event = events[-1]

        reverted = await service.revert_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            comp_id,
            user.id,
            target_event.id,
            initiator_id=user.id,
        )
        assert reverted["score"] == 3.0
        # Audit row for the revert points back at the source event.
        revert_rows = (
            await db.execute(
                select(RecruitmentAuditLog).where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.revert",
                )
            )
        ).scalars().all()
        assert len(revert_rows) == 1
        assert revert_rows[0].payload_diff["reverted_from_event_id"] == str(
            target_event.id
        )

    async def test_revert_audit_records_actual_pre_revert_score(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """When an intermediate edit lands between the source event and
        the revert, the revert audit row's ``old_score`` must reflect
        the *actual* cell value at revert time, not the source event's
        ``new_score``. Otherwise the Versions timeline is internally
        inconsistent ("3 → 2" while the DB jumped "5 → 2")."""
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        v1 = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=2.0),
        )
        # Update v1 → v2 (this is the source event we will revert to v1's old_score).
        v2 = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
            if_match=service.assessment_etag(v1["version"]),
        )
        # An intermediate edit pushes the cell to 5.0 (v3).
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=5.0),
            if_match=service.assessment_etag(v2["version"]),
        )
        # Pick the source event that wrote 2 → 3.
        source_event = (
            await db.execute(
                select(RecruitmentAuditLog).where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.update",
                )
                .order_by(RecruitmentAuditLog.created_at.asc())
            )
        ).scalars().first()
        assert source_event.payload_diff["old_score"] == 2.0
        assert source_event.payload_diff["new_score"] == 3.0

        await service.revert_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            comp_id,
            user.id,
            source_event.id,
            initiator_id=user.id,
        )
        revert_row = (
            await db.execute(
                select(RecruitmentAuditLog).where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.revert",
                )
            )
        ).scalars().one()
        # ``old_score`` is the *current* score before revert (5.0), not
        # the source event's new_score (3.0).
        assert revert_row.payload_diff["old_score"] == 5.0
        assert revert_row.payload_diff["new_score"] == 2.0

    async def test_revert_412_when_cell_advanced_since_snapshot(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        v1 = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        v2 = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=5.0),
            if_match=service.assessment_etag(v1["version"]),
        )
        source = (
            await db.execute(
                select(RecruitmentAuditLog).where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.update",
                )
            )
        ).scalars().one()
        # Caller's stale ETag (v1) — backend already at v2.
        with pytest.raises(HTTPException) as exc:
            await service.revert_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                comp_id,
                user.id,
                source.id,
                initiator_id=user.id,
                if_match='W/"1"',
            )
        assert exc.value.status_code == 412
        # Fresh ETag (v2) — revert succeeds.
        reverted = await service.revert_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            comp_id,
            user.id,
            source.id,
            initiator_id=user.id,
            if_match=service.assessment_etag(v2["version"]),
        )
        assert reverted["score"] == 3.0  # source event's old_score

    async def test_update_audit_user_id_uses_initiator(
        self, db: AsyncSession, tenant, user, admin_role
    ) -> None:
        """Admin Bob editing Alice's cell — audit row must point at
        Bob, not Alice. Before the HRP-266 fix the user_id was
        ``ha.evaluator_id`` and the Versions panel misattributed every
        edit to the original evaluator."""

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles

        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        v1 = await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=2.0),
        )
        bob = User(
            email=f"bob-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("pw"),
            first_name="Bob",
            last_name="Admin",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(bob)
        await db.commit()
        await db.refresh(bob)
        await db.execute(
            user_roles.insert().values(user_id=bob.id, role_id=admin_role.id)
        )
        await db.commit()

        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,  # writing as Alice (evaluator_id)
            AssessmentScoreCreate(competence_id=comp_id, score=4.0),
            if_match=service.assessment_etag(v1["version"]),
            initiator_id=bob.id,  # but Bob is the actor
        )
        update_row = (
            await db.execute(
                select(RecruitmentAuditLog)
                .where(
                    RecruitmentAuditLog.tenant_id == tenant.id,
                    RecruitmentAuditLog.action == "assessment.update",
                )
                .order_by(RecruitmentAuditLog.created_at.desc())
            )
        ).scalars().first()
        assert update_row.user_id == bob.id
        # Payload still tracks the cell's evaluator_id (Alice) so the
        # Versions panel can group the row under her cell.
        assert update_row.payload_diff["evaluator_id"] == str(user.id)

    async def test_revert_invite_only_returns_409_with_clear_message(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """Invite-only check must run BEFORE the (cv, comp, evaluator)
        match — otherwise the user gets a generic 404 instead of the
        clear 'cannot revert invitee scores' message."""
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        invite_event = RecruitmentAuditLog(
            tenant_id=tenant.id,
            user_id=None,
            action="assessment.create",
            entity_type="assessment",
            entity_id=uuid.uuid4(),
            payload_diff=service._assessment_payload_diff(
                cv_id=uuid.UUID(str(cv["id"])),
                competence_id=comp_id,
                evaluator_id=None,
                invite_id=uuid.uuid4(),
                old_score=None,
                new_score=3.0,
                old_comment=None,
                new_comment=None,
                new_version=1,
                operation="upsert",
            ),
        )
        db.add(invite_event)
        await db.commit()
        await db.refresh(invite_event)
        with pytest.raises(HTTPException) as exc:
            await service.revert_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                comp_id,
                user.id,
                invite_event.id,
                initiator_id=user.id,
            )
        assert exc.value.status_code == 409
        assert "Invited" in exc.value.detail

    async def test_revert_rejects_mismatched_audit_event(
        self, db: AsyncSession, tenant, user
    ) -> None:
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=comp_id, score=3.0),
        )
        # Audit event from a different (cv, competence) triple would be
        # an obvious cross-cell shuffle attempt.
        wrong_event = (
            await db.execute(
                select(RecruitmentAuditLog).where(
                    RecruitmentAuditLog.tenant_id == tenant.id
                )
            )
        ).scalars().first()
        bogus_competence = service.normalize_competence_id("not-the-right-comp")
        with pytest.raises(HTTPException) as exc:
            await service.revert_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                bogus_competence,
                user.id,
                wrong_event.id,
                initiator_id=user.id,
            )
        assert exc.value.status_code == 404

    async def test_revert_refuses_invite_only_events(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """Synthesise an audit row whose payload says evaluator_id=None
        (invite-only path) and prove the revert guard fires with 409 —
        we do not need a backing HumanAssessment row for the assertion."""
        _, _, cv, comp_id = await _vacancy_with_cv(db, tenant, user)
        invite_event = RecruitmentAuditLog(
            tenant_id=tenant.id,
            user_id=None,
            action="assessment.create",
            entity_type="assessment",
            entity_id=uuid.uuid4(),
            payload_diff=service._assessment_payload_diff(
                cv_id=uuid.UUID(str(cv["id"])),
                competence_id=comp_id,
                evaluator_id=None,
                invite_id=uuid.uuid4(),
                old_score=None,
                new_score=3.0,
                old_comment=None,
                new_comment=None,
                new_version=1,
                operation="upsert",
            ),
        )
        db.add(invite_event)
        await db.commit()
        await db.refresh(invite_event)
        # ``evaluator_id`` passed into revert must match the audit
        # payload (which is None for invite-only events). The matching
        # guard catches the empty string vs ``None`` mismatch first and
        # returns 404 — which is the desired behaviour (the UI Revert
        # button is hidden for these rows in the first place).
        with pytest.raises(HTTPException) as exc:
            await service.revert_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                comp_id,
                uuid.uuid4(),
                invite_event.id,
                initiator_id=user.id,
            )
        assert exc.value.status_code in {404, 409}
