"""HRP-243: Employee-only callers see Results only when they are the
assessee (the ``self`` participant) and the assessment has reached the
Done status. Peers / subordinates never see results on assessments they
merely participated in.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentParticipant,
    AssessmentResult,
)
from app.modules.assessment.schemas import (
    AssessmentCreate,
    CompetenceCriteriaItem,
    CriteriaUpdate,
)
from sqlalchemy import select


async def _make_scale_with_max(db, tenant) -> AnswerScale:
    scale = AnswerScale(
        title=f"S-{uuid.uuid4().hex[:6]}", tenant_id=tenant.id, is_default=False
    )
    db.add(scale)
    await db.flush()
    for i in range(3):
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=f"L{i}",
                code=f"l{i}",
                weight=i,
                sort_index=i,
                is_neutral=False,
            )
        )
    await db.commit()
    await db.refresh(scale)
    return scale


async def _make_competence(db, tenant):
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"G-{uuid.uuid4().hex[:6]}")
    )
    return await comp_service.create_competence(
        db,
        tenant.id,
        CompetenceCreate(title=f"C-{uuid.uuid4().hex[:6]}", group_id=group.id),
    )


async def _set_status(db, assessment_id, code, statuses):
    a = await db.get(Assessment, assessment_id)
    a.status_id = statuses[code].id
    await db.commit()
    # Detach everything: production reads the detail in a FRESH session,
    # while the shared test session can serve identity-map instances whose
    # eager-loaded relationships predate this UPDATE (observed as
    # ``a.status is None`` on the enterprise CI runner while a fresh SELECT
    # in the same session returned 'done'). Expunging mirrors the real
    # request flow instead of depending on loader/identity-map semantics.
    db.expunge_all()


async def _seed_result(db, assessment_id, competence_id) -> AssessmentResult:
    row = AssessmentResult(
        assessment_id=assessment_id,
        competence_id=competence_id,
        avg_score=0.5,
        calibrated_score=None,
        percent=50,
        level_id=None,
    )
    db.add(row)
    await db.commit()
    return row


async def _create_basic_assessment(db, tenant, user, employee, scale):
    comp = await _make_competence(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="HRP-243",
            employee_id=employee.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    await service.set_assessment_criteria(
        db,
        tenant.id,
        created["id"],
        CriteriaUpdate(
            criteria_type="competences",
            competences=[CompetenceCriteriaItem(competence_id=comp.id)],
        ),
    )
    return uuid.UUID(str(created["id"])), comp.id


@pytest.mark.asyncio
class TestHRP243EmployeeResultsVisibility:
    async def test_employee_self_done_sees_results(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        scale = await _make_scale_with_max(db, tenant)
        assessment_id, comp_id = await _create_basic_assessment(
            db, tenant, user, employee, scale
        )
        await _seed_result(db, assessment_id, comp_id)
        await _set_status(db, assessment_id, "done", assessment_statuses)

        # Self participant: user.id matches the auto-created self
        # participant whose role == "self".
        self_p = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == assessment_id,
                    AssessmentParticipant.role == "self",
                )
            )
        ).scalar_one()

        detail = await service.get_assessment_detail(
            db,
            tenant.id,
            assessment_id,
            participant_user_id=self_p.user_id,
            hide_results_for_employee=True,
        )
        if not detail["results"]:
            # CI-only failure diagnostics (flake seen exclusively on the
            # enterprise pipeline): compare the service's view with fresh
            # rows read straight from the DB before failing.
            from app.modules.assessment.models import AssessmentStatus
            from sqlalchemy import func

            fresh_status = (
                await db.execute(
                    select(AssessmentStatus.code)
                    .join(Assessment, Assessment.status_id == AssessmentStatus.id)
                    .where(Assessment.id == assessment_id)
                )
            ).scalar_one_or_none()
            fresh_results = (
                await db.execute(
                    select(func.count())
                    .select_from(AssessmentResult)
                    .where(AssessmentResult.assessment_id == assessment_id)
                )
            ).scalar_one()
            fresh_parts = (
                await db.execute(
                    select(
                        AssessmentParticipant.role, AssessmentParticipant.user_id
                    ).where(AssessmentParticipant.assessment_id == assessment_id)
                )
            ).all()
            raise AssertionError(
                "Self participant on Done assessment must see results — diag: "
                f"fresh_status={fresh_status!r} fresh_results={fresh_results} "
                f"detail_status={detail.get('status')!r} "
                f"detail_results={detail['results']!r} "
                f"participants={[(r, str(u)) for r, u in fresh_parts]!r} "
                f"self_uid={self_p.user_id}"
            )
        assert detail["overall_percent"] == 50

    async def test_employee_self_on_review_results_hidden(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        scale = await _make_scale_with_max(db, tenant)
        assessment_id, comp_id = await _create_basic_assessment(
            db, tenant, user, employee, scale
        )
        await _seed_result(db, assessment_id, comp_id)
        await _set_status(db, assessment_id, "on_review", assessment_statuses)

        self_p = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == assessment_id,
                    AssessmentParticipant.role == "self",
                )
            )
        ).scalar_one()

        detail = await service.get_assessment_detail(
            db,
            tenant.id,
            assessment_id,
            participant_user_id=self_p.user_id,
            hide_results_for_employee=True,
        )
        assert detail["results"] == []
        assert detail["overall_percent"] is None

    async def test_employee_peer_participant_hides_results_even_on_done(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """A peer participant must NOT see results regardless of status."""
        scale = await _make_scale_with_max(db, tenant)
        assessment_id, comp_id = await _create_basic_assessment(
            db, tenant, user, employee, scale
        )
        await _seed_result(db, assessment_id, comp_id)
        await _set_status(db, assessment_id, "done", assessment_statuses)

        # Spawn a separate user, attach as peer participant.
        from datetime import datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User as AuthUser

        peer_user = AuthUser(
            email=f"peer-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("x"),
            first_name="Peer",
            last_name="Coworker",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(peer_user)
        await db.commit()
        await db.refresh(peer_user)
        peer_part = AssessmentParticipant(
            assessment_id=assessment_id,
            user_id=peer_user.id,
            role="peer",
            is_completed=True,
        )
        db.add(peer_part)
        await db.commit()

        detail = await service.get_assessment_detail(
            db,
            tenant.id,
            assessment_id,
            participant_user_id=peer_user.id,
            hide_results_for_employee=True,
        )
        assert detail["results"] == []
        assert detail["overall_percent"] is None

    async def test_admin_caller_sees_results_in_any_status(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """The Employee gate must be off for admin/manager — they keep
        seeing results in on_review."""
        scale = await _make_scale_with_max(db, tenant)
        assessment_id, comp_id = await _create_basic_assessment(
            db, tenant, user, employee, scale
        )
        await _seed_result(db, assessment_id, comp_id)
        await _set_status(db, assessment_id, "on_review", assessment_statuses)

        detail = await service.get_assessment_detail(
            db,
            tenant.id,
            assessment_id,
            participant_user_id=user.id,
            hide_results_for_employee=False,
        )
        assert detail["results"], "Admin/manager must keep seeing results in on_review"
        assert detail["overall_percent"] == 50

    async def test_get_results_endpoint_obeys_same_gate(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Direct GET /results must also return [] when the Employee gate
        blocks the assessee on a non-Done assessment."""
        scale = await _make_scale_with_max(db, tenant)
        assessment_id, comp_id = await _create_basic_assessment(
            db, tenant, user, employee, scale
        )
        await _seed_result(db, assessment_id, comp_id)
        await _set_status(db, assessment_id, "on_review", assessment_statuses)

        self_p = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == assessment_id,
                    AssessmentParticipant.role == "self",
                )
            )
        ).scalar_one()

        rows = await service.get_results(
            db,
            tenant.id,
            assessment_id,
            participant_user_id=self_p.user_id,
            hide_results_for_employee=True,
        )
        assert rows == []
