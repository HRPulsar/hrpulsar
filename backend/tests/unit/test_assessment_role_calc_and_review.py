"""HRP-62 (role-mean calculation) + HRP-27 (on_review status).

The two changes are bundled because the new status triggers the new
calculation and the test harness for both shares the same scaffolding
(scale + competence + indicators + multi-role participants).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
    AssessmentResult,
)
from app.modules.assessment.schemas import (
    AnswerRecord,
    AssessmentCreate,
    ParticipantAdd,
)
from app.modules.auth.models import User as AuthUser
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import advance_to_in_progress

pytestmark = pytest.mark.asyncio


# --- helpers ---------------------------------------------------------------


async def _make_user_with_employee(
    db: AsyncSession, tenant, suffix: str
) -> tuple[AuthUser, Employee]:
    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.flush()

    u = AuthUser(
        email=f"role-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()

    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(u)
    await db.refresh(emp)
    return u, emp


async def _make_scale(
    db: AsyncSession, tenant, *, weights: list[int], with_levels: bool = True
) -> AnswerScale:
    scale = AnswerScale(tenant_id=tenant.id, title=f"Scale-{uuid.uuid4().hex[:6]}")
    db.add(scale)
    await db.flush()
    for i, w in enumerate(weights):
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=f"Opt{i}",
                code=f"opt{i}",
                weight=w,
                sort_index=i,
            )
        )
    db.add(
        AnswerOption(
            scale_id=scale.id,
            title="Don't know",
            code="dk",
            weight=None,
            sort_index=len(weights),
            is_neutral=True,
        )
    )
    if with_levels:
        db.add_all(
            [
                AnswerScaleLevel(
                    scale_id=scale.id,
                    percent_from=0,
                    percent_to=50,
                    system_title="Low",
                    sort_index=0,
                ),
                AnswerScaleLevel(
                    scale_id=scale.id,
                    percent_from=51,
                    percent_to=100,
                    system_title="High",
                    sort_index=1,
                ),
            ]
        )
    await db.commit()
    await db.refresh(scale)
    return scale


async def _make_competence_with_levels(
    db: AsyncSession, tenant, suffix: str, *, indicators_per_level: list[list[int]]
) -> tuple[uuid.UUID, list[Indicator]]:
    """Build a competence whose skill levels each carry indicators with
    the given ``weight`` integers. Returns ``(competence_id, indicators)``
    in the order they were inserted (level by level)."""
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"Grp-{suffix}")
    )
    comp = await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=f"Comp-{suffix}", group_id=group.id)
    )

    indicators: list[Indicator] = []
    for level_idx, weights in enumerate(indicators_per_level):
        sl = SkillLevel(
            title=f"Level-{suffix}-{level_idx}",
            sort_index=level_idx,
            tenant_id=tenant.id,
        )
        db.add(sl)
        await db.flush()
        for ind_idx, w in enumerate(weights):
            ind = Indicator(
                title=f"Ind-{suffix}-{level_idx}-{ind_idx}",
                weight=w,
                sort_index=ind_idx,
                skill_level_id=sl.id,
                competence_id=comp.id,
                tenant_id=tenant.id,
            )
            db.add(ind)
            indicators.append(ind)
    await db.commit()
    for ind in indicators:
        await db.refresh(ind)
    return comp.id, indicators


async def _create_360(
    db: AsyncSession,
    tenant,
    initiator: AuthUser,
    target: Employee,
    *,
    competence_id: uuid.UUID,
    scale: AnswerScale,
) -> dict:
    a = await service.create_assessment(
        db,
        tenant.id,
        initiator.id,
        AssessmentCreate(
            title=f"360-{uuid.uuid4().hex[:6]}",
            employee_id=target.id,
            type_code="360",
            scale_id=scale.id,
        ),
    )
    db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=competence_id))
    a_obj = await db.get(Assessment, a["id"])
    a_obj.criteria_type = "current_positions"
    await db.commit()
    return a


async def _add_participant_with_role(
    db: AsyncSession, tenant, assessment_id: uuid.UUID, suffix: str, role: str
) -> AssessmentParticipant:
    _user, emp = await _make_user_with_employee(db, tenant, suffix)
    return await _add_participant(db, tenant, assessment_id, emp.id, role)


async def _add_participant(
    db: AsyncSession,
    tenant,
    assessment_id: uuid.UUID,
    employee_id: uuid.UUID,
    role: str,
) -> AssessmentParticipant:
    created = await service.add_participant(
        db,
        tenant.id,
        assessment_id,
        ParticipantAdd(employee_id=employee_id, role=role),
    )
    p = await db.get(AssessmentParticipant, created["id"])
    return p


async def _record_raw_answer(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    participant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    *,
    option: AnswerOption | None = None,
    score: int | None = None,
) -> None:
    db.add(
        AssessmentAnswer(
            assessment_id=assessment_id,
            participant_id=participant_id,
            indicator_id=indicator_id,
            answer_option_id=option.id if option is not None else None,
            score=score if option is None else option.weight,
        )
    )


# --- HRP-62 calculation ----------------------------------------------------


class TestRoleMeanCalculation:
    async def test_360_role_mean_with_weighted_levels(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Spec example reduced: one competence with two skill levels.

        Level-1 has indicators (weight 1, weight 2); level-2 has one
        indicator (weight 1). Scale max weight is 4 (Outstanding).

        - self answers level-1 inds with weight 4, level-2 with weight 4
          → role percent = 100
        - manager answers level-1 inds with weight 2, level-2 with weight 4
          → level-1 weighted avg (2*1 + 2*2) / (1+2) = 2 → 50%; level-2 100%
            → manager role percent = 75
        - peer1 answers everything with weight 4 → 100; peer2 with 2 → 50
          → peer role percent = (peer1 + peer2 averaged per indicator) =
            actually we average per indicator across raters in the role:
            level-1 ind1 (4+2)/2=3 → 3*1; ind2 (4+2)/2=3 → 3*2; weighted
            level1 = (3 + 6) / 3 = 3 → 75%; level-2 (4+2)/2=3 → 75%; peer
            role percent = 75
        - subordinate answers level-1 with weight 4, level-2 with weight 2
          → 100% level1, 50% level2 → 75
        Final = (100 + 75 + 75 + 75) / 4 = 81.25 → 81%, avg_score 0.8125.
        """
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, indicators = await _make_competence_with_levels(
            db, tenant, "rolemean", indicators_per_level=[[1, 2], [1]]
        )
        l1_i1, l1_i2, l2_i1 = indicators

        a = await _create_360(
            db, tenant, user, employee, competence_id=comp_id, scale=scale
        )
        # service.create_assessment auto-adds the self participant for
        # the target employee.
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

        manager = await _add_participant_with_role(
            db, tenant, a["id"], "rmgr", "manager"
        )
        peer1 = await _add_participant_with_role(db, tenant, a["id"], "rp1", "peer")
        peer2 = await _add_participant_with_role(db, tenant, a["id"], "rp2", "peer")
        sub = await _add_participant_with_role(
            db, tenant, a["id"], "rsub", "subordinate"
        )

        # Resolve snapshotted scale options. change_status to sent
        # snapshots the scale, and answers reference snapshotted option
        # ids — so we transition first and look options up after.
        await service.change_status(db, tenant.id, a["id"], "sent")
        snap = await service._load_scale_full(
            db, (await db.get(Assessment, a["id"])).scale_id
        )
        opt_by_weight = {o.weight: o for o in snap.options if not o.is_neutral}
        w4, w2 = opt_by_weight[4], opt_by_weight[2]

        # self: all 4
        await _record_raw_answer(
            db, a["id"], self_part_id, l1_i1.id, option=w4
        )
        await _record_raw_answer(
            db, a["id"], self_part_id, l1_i2.id, option=w4
        )
        await _record_raw_answer(
            db, a["id"], self_part_id, l2_i1.id, option=w4
        )
        # manager: level1 = 2,2; level2 = 4
        await _record_raw_answer(db, a["id"], manager.id, l1_i1.id, option=w2)
        await _record_raw_answer(db, a["id"], manager.id, l1_i2.id, option=w2)
        await _record_raw_answer(db, a["id"], manager.id, l2_i1.id, option=w4)
        # peer1: 4,4,4
        await _record_raw_answer(db, a["id"], peer1.id, l1_i1.id, option=w4)
        await _record_raw_answer(db, a["id"], peer1.id, l1_i2.id, option=w4)
        await _record_raw_answer(db, a["id"], peer1.id, l2_i1.id, option=w4)
        # peer2: 2,2,2
        await _record_raw_answer(db, a["id"], peer2.id, l1_i1.id, option=w2)
        await _record_raw_answer(db, a["id"], peer2.id, l1_i2.id, option=w2)
        await _record_raw_answer(db, a["id"], peer2.id, l2_i1.id, option=w2)
        # subordinate: level1 = 4,4; level2 = 2
        await _record_raw_answer(db, a["id"], sub.id, l1_i1.id, option=w4)
        await _record_raw_answer(db, a["id"], sub.id, l1_i2.id, option=w4)
        await _record_raw_answer(db, a["id"], sub.id, l2_i1.id, option=w2)
        # mark all participants completed (we wrote answers directly)
        for pid in (self_part_id, manager.id, peer1.id, peer2.id, sub.id):
            p = await db.get(AssessmentParticipant, pid)
            p.is_completed = True
        await db.commit()

        await advance_to_in_progress(db, tenant.id, a["id"])
        from tests.unit._send_prereqs import advance_to_done

        await advance_to_done(db, tenant.id, a["id"])

        results = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalars().all()
        assert len(results) == 1
        r = results[0]
        # 81.25 rounds to 81; the value is far enough from a half-integer
        # that Python's banker's rounding doesn't change the outcome.
        assert r.percent == 81
        assert r.avg_score == pytest.approx(0.8125, rel=1e-3)

    async def test_level_with_mixed_neutral_and_real_answers(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Within one level, an indicator with only neutral answers must
        drop out of the weighted average without nuking the level — the
        sibling indicator with real answers still drives the level
        percent."""
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind_a, ind_b] = await _make_competence_with_levels(
            db, tenant, "mixedneutral", indicators_per_level=[[1, 2]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Mixed",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(
            p["id"] for p in detail["participants"] if p["role"] == "self"
        )

        await service.change_status(db, tenant.id, a["id"], "sent")
        snap = await service._load_scale_full(
            db, (await db.get(Assessment, a["id"])).scale_id
        )
        w4 = next(o for o in snap.options if o.weight == 4)
        neutral = next(o for o in snap.options if o.is_neutral)

        # ind_a (weight 1) → neutral, ind_b (weight 2) → top of scale
        await _record_raw_answer(
            db, a["id"], self_part_id, ind_a.id, option=neutral
        )
        await _record_raw_answer(db, a["id"], self_part_id, ind_b.id, option=w4)
        p = await db.get(AssessmentParticipant, self_part_id)
        p.is_completed = True
        await db.commit()

        await advance_to_in_progress(db, tenant.id, a["id"])
        from tests.unit._send_prereqs import advance_to_done

        await advance_to_done(db, tenant.id, a["id"])

        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        # Only ind_b contributed: weighted avg = 4*2/2 = 4 → 100%.
        assert result.percent == 100

    async def test_orphan_score_only_answer_counts(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """A raw ``score`` (no ``answer_option_id``) must feed the same
        pipeline as option-based answers. Locks the contract for
        ``record_answer`` callers that submit only a numeric score."""
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "rawscore", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="RawScore",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(
            p["id"] for p in detail["participants"] if p["role"] == "self"
        )
        await service.change_status(db, tenant.id, a["id"], "sent")
        await _record_raw_answer(
            db, a["id"], self_part_id, ind.id, option=None, score=2
        )
        p = await db.get(AssessmentParticipant, self_part_id)
        p.is_completed = True
        await db.commit()

        await advance_to_in_progress(db, tenant.id, a["id"])
        from tests.unit._send_prereqs import advance_to_done

        await advance_to_done(db, tenant.id, a["id"])

        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        # score 2 / max_weight 4 = 50%.
        assert result.percent == 50

    async def test_neutral_answers_are_skipped(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "neutral", indicators_per_level=[[1]]
        )

        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Self+neutral",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

        await service.change_status(db, tenant.id, a["id"], "sent")
        snap = await service._load_scale_full(
            db, (await db.get(Assessment, a["id"])).scale_id
        )
        neutral = next(o for o in snap.options if o.is_neutral)
        await _record_raw_answer(db, a["id"], self_part_id, ind.id, option=neutral)
        p = await db.get(AssessmentParticipant, self_part_id)
        p.is_completed = True
        await db.commit()

        await advance_to_in_progress(db, tenant.id, a["id"])
        from tests.unit._send_prereqs import advance_to_done

        await advance_to_done(db, tenant.id, a["id"])

        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        # Only neutral answer was recorded → percent stays None and
        # avg_score is 0 (no usable scores collected for any role).
        assert result.percent is None
        assert result.avg_score == 0


# --- HRP-27 status & calibration -----------------------------------------


class TestOnReviewStatus:
    async def test_auto_transition_when_all_participants_complete(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "auto", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Auto",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

        # The only participant answers the only indicator → completion
        # cascades through _maybe_mark_participant_completed and
        # auto-flips the assessment to on_review.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            a["id"],
            AnswerRecord(participant_id=self_part_id, indicator_id=ind.id, score=4),
        )

        refreshed = await db.get(Assessment, a["id"])
        await db.refresh(refreshed, ["status"])
        assert refreshed.status.code == "on_review"

        # Preliminary results should already be there.
        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result.percent == 100

    async def test_manual_transition_requires_one_completed(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "manualreq", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="ManualReq",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        await advance_to_in_progress(db, tenant.id, a["id"])

        # Nobody completed yet → manual on_review is rejected.
        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, a["id"], "on_review")
        assert exc.value.status_code == 400
        assert "completed participant" in exc.value.detail

    async def test_manual_transition_allowed_with_one_completed(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "manualok", indicators_per_level=[[1]]
        )
        a = await _create_360(
            db, tenant, user, employee, competence_id=comp_id, scale=scale
        )
        manager = await _add_participant_with_role(
            db, tenant, a["id"], "mok-mgr", "manager"
        )

        await service.change_status(db, tenant.id, a["id"], "sent")
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

        # Only the self participant submits — manager remains pending.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            a["id"],
            AnswerRecord(participant_id=self_part_id, indicator_id=ind.id, score=4),
        )

        # self is completed; manager is not → assessment is still in
        # in_progress (auto-flow waits until all are done). Manual
        # transition should succeed and trigger preliminary results.
        a_obj = await db.get(Assessment, a["id"])
        await db.refresh(a_obj, ["status"])
        assert a_obj.status.code == "in_progress"

        await service.change_status(db, tenant.id, a["id"], "on_review")

        a_obj2 = await db.get(Assessment, a["id"])
        await db.refresh(a_obj2, ["status"])
        assert a_obj2.status.code == "on_review"

        # Manager hasn't answered, so the level has scores from one role
        # only — but the per-competence percent should still come out
        # because the self role contributes 100%.
        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result.percent == 100

        # manager.id is referenced just to ensure the participant exists
        assert manager.id is not None

    async def test_calibrate_during_on_review_persists(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import CalibrateItem

        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "calib", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Calib",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

        await service.record_answer(
            db,
            tenant.id,
            user.id,
            a["id"],
            AnswerRecord(participant_id=self_part_id, indicator_id=ind.id, score=2),
        )
        a_obj2 = await db.get(Assessment, a["id"])
        await db.refresh(a_obj2, ["status"])
        assert a_obj2.status.code == "on_review"

        await service.calibrate(
            db,
            tenant.id,
            a["id"],
            [CalibrateItem(competence_id=comp_id, calibrated_score=3.5)],
        )

        result = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result.calibrated_score == 3.5
        # HRP-126: percent now reflects the calibrated score against the
        # scale's max weight (3.5 / 4 = 87.5 → 88), so the Results block
        # stays consistent with the override.
        assert result.percent == 88

    async def test_calibration_updates_level_and_survives_done(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-126 regression: calibration must update the matching level
        and the calibrated percent must not be reverted by the final
        recompute that runs on the on_review → done transition.
        """
        from app.modules.assessment.schemas import CalibrateItem

        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "calib-done", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="CalibDone",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(
            p["id"] for p in detail["participants"] if p["role"] == "self"
        )

        # Raw answer would land the result in the Low (0-50) bucket.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            a["id"],
            AnswerRecord(participant_id=self_part_id, indicator_id=ind.id, score=2),
        )
        a_obj = await db.get(Assessment, a["id"])
        await db.refresh(a_obj, ["status"])
        assert a_obj.status.code == "on_review"

        # The active scale is the snapshot taken at "sent", not the source
        # scale defined above. Resolve levels through the snapshot to match
        # the IDs stored on AssessmentResult.
        levels_q = await db.execute(
            select(AnswerScaleLevel).where(
                AnswerScaleLevel.scale_id == a_obj.scale_id
            )
        )
        levels = {lv.system_title: lv for lv in levels_q.scalars().all()}

        result_pre = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result_pre.percent == 50
        assert result_pre.level_id == levels["Low"].id

        await service.calibrate(
            db,
            tenant.id,
            a["id"],
            [CalibrateItem(competence_id=comp_id, calibrated_score=3.5)],
        )

        result_post = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result_post.percent == 88
        assert result_post.level_id == levels["High"].id

        # Finalize: the on_review → done recompute must not silently revert
        # percent/level back to the raw answer-derived values.
        await service.change_status(db, tenant.id, a["id"], "done")

        result_final = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a["id"]
                )
            )
        ).scalar_one()
        assert result_final.calibrated_score == 3.5
        assert result_final.percent == 88
        assert result_final.level_id == levels["High"].id

    async def test_in_progress_to_done_direct_is_blocked(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "directdone", indicators_per_level=[[1]]
        )
        del ind  # silence unused
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Direct",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        await advance_to_in_progress(db, tenant.id, a["id"])
        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, a["id"], "done")
        assert exc.value.status_code == 400
        assert "On Review" in exc.value.detail

    async def test_on_review_to_done_finalizes(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, [ind] = await _make_competence_with_levels(
            db, tenant, "todone", indicators_per_level=[[1]]
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="ToDone",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            a["id"],
            AnswerRecord(participant_id=self_part_id, indicator_id=ind.id, score=4),
        )

        # Auto-moved to on_review. Finalize.
        await service.change_status(db, tenant.id, a["id"], "done")

        a_obj = await db.get(Assessment, a["id"])
        await db.refresh(a_obj, ["status"])
        assert a_obj.status.code == "done"
        assert a_obj.finished_at is not None


class TestPerLevelBreakdown:
    """HRP-90: per-skill-level results popup data in assessment detail."""

    async def test_per_level_results_populated_per_competence(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, indicators = await _make_competence_with_levels(
            db,
            tenant,
            "perlevel",
            # 3 skill levels, one indicator each: Basic, Intermediate, Advanced.
            indicators_per_level=[[1], [1], [1]],
        )
        basic_ind, inter_ind, adv_ind = indicators

        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="PerLevel",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        # Target = Advanced so the cascade covers all three levels.
        db.add(
            AssessmentCompetence(
                assessment_id=a["id"],
                competence_id=comp_id,
                skill_level_id=adv_ind.skill_level_id,
            )
        )
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        self_part = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == a["id"],
                    AssessmentParticipant.role == "self",
                )
            )
        ).scalar_one()
        for ind, score in [(basic_ind, 4), (inter_ind, 2), (adv_ind, 0)]:
            await service.record_answer(
                db,
                tenant.id,
                user.id,
                a["id"],
                AnswerRecord(
                    participant_id=self_part.id, indicator_id=ind.id, score=score
                ),
            )

        a_fresh = await db.get(Assessment, a["id"])
        per_level = await service._compute_per_level_breakdown(db, a_fresh)
        rows = per_level[comp_id]
        assert [r["sort_index"] for r in rows] == [0, 1, 2]
        assert [r["percent"] for r in rows] == [100, 50, 0]
        # Titles flow through from the SkillLevel records created by the helper.
        assert all(r["skill_level_title"] for r in rows)

    async def test_per_level_drops_levels_above_target(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant, weights=[0, 1, 2, 3, 4])
        comp_id, indicators = await _make_competence_with_levels(
            db,
            tenant,
            "perlevel-target",
            indicators_per_level=[[1], [1], [1]],
        )
        basic_ind, inter_ind, _adv_ind = indicators

        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="PerLevelTarget",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        # Target = Intermediate; questionnaire cascade only includes Basic +
        # Intermediate, so the popup should not surface Advanced.
        db.add(
            AssessmentCompetence(
                assessment_id=a["id"],
                competence_id=comp_id,
                skill_level_id=inter_ind.skill_level_id,
            )
        )
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        await service.change_status(db, tenant.id, a["id"], "sent")
        self_part = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == a["id"],
                    AssessmentParticipant.role == "self",
                )
            )
        ).scalar_one()
        for ind, score in [(basic_ind, 4), (inter_ind, 3)]:
            await service.record_answer(
                db,
                tenant.id,
                user.id,
                a["id"],
                AnswerRecord(
                    participant_id=self_part.id, indicator_id=ind.id, score=score
                ),
            )

        a_fresh = await db.get(Assessment, a["id"])
        per_level = await service._compute_per_level_breakdown(db, a_fresh)
        rows = per_level[comp_id]
        assert [r["sort_index"] for r in rows] == [0, 1]
        assert [r["percent"] for r in rows] == [100, 75]
