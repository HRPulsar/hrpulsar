"""HRP-145: preliminary results must refresh when a new respondent
finishes after the assessment is already in ``on_review``.

Before the fix the recompute path ran only on the manual / automatic
``in_progress → on_review`` transition, so any survey submitted later
was silently ignored on the Results table. Calibration overrides
already had a guard (HRP-126) and must continue to win for
``percent``/``level_id`` while ``avg_score`` keeps tracking the live
answer set.
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
    AssessmentCreate,
    ParticipantAdd,
)
from app.modules.auth.models import User as AuthUser
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import advance_to_in_progress

pytestmark = pytest.mark.asyncio


async def _make_user_with_employee(
    db: AsyncSession, tenant, suffix: str
) -> tuple[AuthUser, Employee]:
    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.flush()

    u = AuthUser(
        email=f"hrp145-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
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


async def _make_scale(db: AsyncSession, tenant) -> AnswerScale:
    scale = AnswerScale(tenant_id=tenant.id, title=f"Scale-{uuid.uuid4().hex[:6]}")
    db.add(scale)
    await db.flush()
    for i, w in enumerate([0, 1, 2, 3, 4]):
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
            sort_index=99,
            is_neutral=True,
        )
    )
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


async def _make_single_indicator_competence(
    db: AsyncSession, tenant, suffix: str
) -> tuple[uuid.UUID, Indicator]:
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
    sl = SkillLevel(
        title=f"Level-{suffix}",
        sort_index=0,
        tenant_id=tenant.id,
    )
    db.add(sl)
    await db.flush()
    ind = Indicator(
        title=f"Ind-{suffix}",
        weight=1,
        sort_index=0,
        skill_level_id=sl.id,
        competence_id=comp.id,
        tenant_id=tenant.id,
    )
    db.add(ind)
    await db.commit()
    await db.refresh(ind)
    return comp.id, ind


async def _scenario_assessment_in_on_review(db, tenant, user, employee):
    """Spin up a 360° with two participants where the self participant
    finished and the assessment was manually moved to on_review (one
    completed survey out of two)."""
    scale = await _make_scale(db, tenant)
    comp_id, _indicator = await _make_single_indicator_competence(db, tenant, "h145")

    a = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title=f"360-h145-{uuid.uuid4().hex[:6]}",
            employee_id=employee.id,
            type_code="360",
            scale_id=scale.id,
        ),
    )
    db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
    a_obj = await db.get(Assessment, a["id"])
    a_obj.criteria_type = "current_positions"
    await db.commit()

    detail = await service.get_assessment_detail(db, tenant.id, a["id"])
    self_part_id = next(p["id"] for p in detail["participants"] if p["role"] == "self")

    _mgr_user, mgr_emp = await _make_user_with_employee(db, tenant, "mgr")
    mgr_part = await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=mgr_emp.id, role="manager"),
    )
    mgr_part_id = mgr_part["id"]

    await service.change_status(db, tenant.id, a["id"], "sent")
    snap = await service._load_scale_full(
        db, (await db.get(Assessment, a["id"])).scale_id
    )
    opt_by_weight = {o.weight: o for o in snap.options if not o.is_neutral}

    indicator_q = await db.execute(
        select(Indicator).where(Indicator.competence_id == comp_id)
    )
    indicator_id = indicator_q.scalar_one().id

    # Self answers with the top option (weight 4).
    db.add(
        AssessmentAnswer(
            assessment_id=a["id"],
            participant_id=self_part_id,
            indicator_id=indicator_id,
            answer_option_id=opt_by_weight[4].id,
        )
    )
    self_part = await db.get(AssessmentParticipant, self_part_id)
    self_part.is_completed = True
    await db.commit()

    await advance_to_in_progress(db, tenant.id, a["id"])
    await service.change_status(db, tenant.id, a["id"], "on_review")

    return {
        "assessment_id": a["id"],
        "competence_id": comp_id,
        "self_part_id": self_part_id,
        "mgr_part_id": mgr_part_id,
        "indicator_id": indicator_id,
        "opt_by_weight": opt_by_weight,
    }


async def _result_for(
    db: AsyncSession, assessment_id: uuid.UUID, competence_id: uuid.UUID
) -> AssessmentResult:
    rows = (
        (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == assessment_id,
                    AssessmentResult.competence_id == competence_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected single result row, got {len(rows)}"
    return rows[0]


class TestPreliminaryRecompute:
    async def test_avg_score_updates_when_new_respondent_finishes_on_review(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Self answered top-of-scale → preliminary avg ≈ 1.0. Manager
        finishes later with mid-scale (weight 2) → recompute averages
        the role scores ((100 + 50) / 2 = 75%, avg 0.75)."""
        ctx = await _scenario_assessment_in_on_review(db, tenant, user, employee)

        baseline = await _result_for(db, ctx["assessment_id"], ctx["competence_id"])
        assert baseline.avg_score == pytest.approx(1.0, rel=1e-3)
        assert baseline.percent == 100

        # Manager submits weight=2 → triggers _maybe_mark_participant_completed →
        # _maybe_auto_move_to_on_review which now refreshes results in place.
        db.add(
            AssessmentAnswer(
                assessment_id=ctx["assessment_id"],
                participant_id=ctx["mgr_part_id"],
                indicator_id=ctx["indicator_id"],
                answer_option_id=ctx["opt_by_weight"][2].id,
            )
        )
        await db.flush()
        await service._maybe_mark_participant_completed(
            db, ctx["assessment_id"], ctx["mgr_part_id"]
        )
        await db.commit()

        refreshed = await _result_for(db, ctx["assessment_id"], ctx["competence_id"])
        assert refreshed.avg_score == pytest.approx(0.75, rel=1e-3)
        assert refreshed.percent == 75
        # Status must stay on_review — recompute is for the preliminary
        # state, not a done transition.
        a = await db.get(
            Assessment,
            ctx["assessment_id"],
        )
        await db.refresh(a, ["status"])
        assert a.status.code == "on_review"

    async def test_calibration_survives_when_new_respondent_finishes(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-126 guard combined with HRP-145: calibrated percent/level
        win, but avg_score still follows the freshest answer set."""
        ctx = await _scenario_assessment_in_on_review(db, tenant, user, employee)

        # Lock in a calibration override at half the scale (2 / 4) →
        # percent should clamp to 50.
        row = await _result_for(db, ctx["assessment_id"], ctx["competence_id"])
        row.calibrated_score = 2.0
        await db.commit()
        calibrated_id = row.id

        # New respondent finishes — avg_score must move, percent must stay
        # 50 (calibrated) and the row identity stays put.
        db.add(
            AssessmentAnswer(
                assessment_id=ctx["assessment_id"],
                participant_id=ctx["mgr_part_id"],
                indicator_id=ctx["indicator_id"],
                answer_option_id=ctx["opt_by_weight"][2].id,
            )
        )
        await db.flush()
        await service._maybe_mark_participant_completed(
            db, ctx["assessment_id"], ctx["mgr_part_id"]
        )
        await db.commit()

        refreshed = await _result_for(db, ctx["assessment_id"], ctx["competence_id"])
        assert refreshed.id == calibrated_id
        assert refreshed.avg_score == pytest.approx(0.75, rel=1e-3)
        assert refreshed.calibrated_score == pytest.approx(2.0, rel=1e-3)
        # percent and level come from the calibrated score (2 / 4 = 50%),
        # not from the freshly recomputed role mean (75%).
        assert refreshed.percent == 50
        # Level "Low" covers 0..50 — that's where percent=50 lands.
        await db.refresh(refreshed, ["level"])
        assert refreshed.level is not None
        assert refreshed.level.system_title == "Low"
