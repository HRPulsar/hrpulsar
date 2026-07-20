"""HRP-170: Recommended grade chart fixes.

Covers the three deliverables on the ticket:

1. Chart is computed at ``on_review`` (was Done-only) and stays for
   ``cancelled`` when the assessment crossed On Review first.
2. Chart now applies to ``current_positions`` (specialization derived
   from the assessee's Position) as well as ``target_position``.
3. Per-grade math averages competence percents, where each competence's
   percent is the mean of skill-level percents from Basic up to the
   grade's required level — matches the spec example in the PROMPT.
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
    Assessment,
    AssessmentAnswer,
    AssessmentParticipant,
    AssessmentResult,
)
from app.modules.assessment.recommendation import compute_grade_recommendation
from app.modules.assessment.schemas import (
    AssessmentCreate,
    CriteriaUpdate,
)
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)


async def _make_skill_level(db, title: str, sort_index: int) -> SkillLevel:
    sl = SkillLevel(title=title, sort_index=sort_index)
    db.add(sl)
    await db.commit()
    await db.refresh(sl)
    return sl


async def _make_competence(db, tenant, title: str):
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"G-{title}-{uuid.uuid4().hex[:6]}")
    )
    return await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=title, group_id=group.id)
    )


async def _make_indicator(db, tenant, *, competence_id, skill_level_id, weight=1):
    ind = Indicator(
        title=f"Ind-{uuid.uuid4().hex[:6]}",
        weight=weight,
        sort_index=0,
        skill_level_id=skill_level_id,
        competence_id=competence_id,
        tenant_id=tenant.id,
    )
    db.add(ind)
    await db.commit()
    await db.refresh(ind)
    return ind


async def _make_dict_item(db, tenant, type_: str, title: str) -> DictionaryItem:
    item = DictionaryItem(tenant_id=tenant.id, type=type_, title=title, is_active=True)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _make_scale(db, tenant) -> AnswerScale:
    """6-option scale weights 0..5 → max weight 5, percent = weight/5*100."""
    scale = AnswerScale(
        title=f"S-{uuid.uuid4().hex[:6]}",
        tenant_id=tenant.id,
        is_default=False,
    )
    db.add(scale)
    await db.flush()
    for i in range(6):
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
    res = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == scale.id)
    )
    return res.scalar_one()


def _option_by_weight(scale: AnswerScale, weight: int) -> AnswerOption:
    for o in scale.options:
        if o.weight == weight:
            return o
    raise AssertionError(f"weight {weight} missing from scale")


async def _record(db, *, assessment_id, participant_id, indicator_id, option_id):
    db.add(
        AssessmentAnswer(
            assessment_id=assessment_id,
            participant_id=participant_id,
            indicator_id=indicator_id,
            answer_option_id=option_id,
        )
    )
    await db.commit()


async def _live_scale(db, assessment_id) -> AnswerScale:
    a = await db.get(Assessment, assessment_id)
    res = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == a.scale_id)
    )
    return res.scalar_one()


@pytest.mark.asyncio
async def test_chart_available_at_on_review(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Recommendation is computed at On Review, not only at Done."""
    spec = await _make_dict_item(db, tenant, "specialization", "Backend")
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "C")
    ind = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=sl.id
    )
    grade = await _make_dict_item(db, tenant, "grade", "Junior")
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade.id,
        specialization_id=spec.id,
        sort_index=1,
        passing_score=50,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="OnReviewChart",
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
            criteria_type="target_position",
            specialization_id=spec.id,
            grade_id=grade.id,
            passing_score=50,
        ),
    )

    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await _live_scale(db, created["id"])
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind.id,
        option_id=_option_by_weight(live, 4).id,
    )
    await advance_to_in_progress(db, tenant.id, created["id"])

    # Drive the participant to "completed" + flip to on_review (NOT done).
    parts = (
        (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == uuid.UUID(str(created["id"]))
                )
            )
        )
        .scalars()
        .all()
    )
    for p in parts:
        p.is_completed = True
    await db.commit()
    await service.change_status(db, tenant.id, created["id"], "on_review")

    detail2 = await service.get_assessment_detail(db, tenant.id, created["id"])
    assert detail2["status_code"] == "on_review"
    rec = detail2["recommendation"]
    assert rec is not None, "chart must appear at on_review"
    assert rec["grades"][0]["percent"] == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_chart_for_current_positions_criteria(
    db, tenant, user, assessment_statuses, assessment_types
):
    """current_positions assessments now produce a recommendation too."""
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    spec = await _make_dict_item(db, tenant, "specialization", "Frontend")
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "FE")
    ind = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=sl.id
    )
    grade = await _make_dict_item(db, tenant, "grade", "Mid")
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade.id,
        specialization_id=spec.id,
        sort_index=1,
        passing_score=40,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()

    pos = Position(
        tenant_id=tenant.id,
        title="FE-pos",
        source="manual",
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    u = AuthUser(
        email=f"cp-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("p"),
        first_name="Cur",
        last_name="Pos",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="CP-chart",
            employee_id=emp.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    await service.set_assessment_criteria(
        db,
        tenant.id,
        created["id"],
        CriteriaUpdate(criteria_type="current_positions", passing_score=40),
    )

    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await _live_scale(db, created["id"])
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind.id,
        option_id=_option_by_weight(live, 3).id,
    )
    await advance_to_in_progress(db, tenant.id, created["id"])
    await advance_to_done(db, tenant.id, created["id"])

    detail2 = await service.get_assessment_detail(db, tenant.id, created["id"])
    rec = detail2["recommendation"]
    assert rec is not None
    assert rec["grades"][0]["percent"] == pytest.approx(60.0)
    assert rec["recommended_grade_passed"] is True


@pytest.mark.asyncio
async def test_grade_formula_averages_levels_up_to_required(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Spec example: Junior(Basic) competence with answers at Basic and
    Intermediate levels — Junior only sees Basic, Middle averages
    (Basic + Intermediate)/2, Senior averages all three."""
    spec = await _make_dict_item(db, tenant, "specialization", "Designer")
    basic = await _make_skill_level(db, "Basic", 1)
    inter = await _make_skill_level(db, "Intermediate", 2)
    advanced = await _make_skill_level(db, "Advanced", 3)
    comp = await _make_competence(db, tenant, "Design")
    ind_basic = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=basic.id
    )
    ind_inter = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=inter.id
    )
    ind_adv = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=advanced.id
    )

    grades = []
    for i, (title, sl) in enumerate(
        (("Junior", basic), ("Middle", inter), ("Senior", advanced))
    ):
        grade = await _make_dict_item(db, tenant, "grade", title)
        grades.append((title, grade, sl))
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=spec.id,
            sort_index=i + 1,
            passing_score=50,
        )
        db.add(gs)
        await db.commit()
        await db.refresh(gs)
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=sl.id,
            )
        )
        await db.commit()

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="Cascade",
            employee_id=employee.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    # All-grades target_position so the assessment scope covers every level.
    await service.set_assessment_criteria(
        db,
        tenant.id,
        created["id"],
        CriteriaUpdate(
            criteria_type="target_position",
            specialization_id=spec.id,
            grade_id=None,
            passing_score=50,
        ),
    )

    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await _live_scale(db, created["id"])
    # Basic = 100% (weight 5), Intermediate = 60% (weight 3), Advanced = 20%
    # (weight 1) on the 0..5 scale.
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind_basic.id,
        option_id=_option_by_weight(live, 5).id,
    )
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind_inter.id,
        option_id=_option_by_weight(live, 3).id,
    )
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind_adv.id,
        option_id=_option_by_weight(live, 1).id,
    )
    await advance_to_in_progress(db, tenant.id, created["id"])
    await advance_to_done(db, tenant.id, created["id"])

    detail2 = await service.get_assessment_detail(db, tenant.id, created["id"])
    rec = detail2["recommendation"]
    by_title = {g["grade_title"]: g["percent"] for g in rec["grades"]}
    # Junior — Basic only.
    assert by_title["Junior"] == pytest.approx(100.0)
    # Middle — mean of Basic + Intermediate = (100+60)/2 = 80.
    assert by_title["Middle"] == pytest.approx(80.0)
    # Senior — mean of all three = (100+60+20)/3 ≈ 60.
    assert by_title["Senior"] == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_grades_above_assessed_levels_are_omitted(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-170 redo: when the assessment was generated only up to Middle
    (Basic + Intermediate indicators), the Senior bar — whose link
    requires Advanced — must be dropped from the chart entirely.
    """
    spec = await _make_dict_item(db, tenant, "specialization", "Spec-redo")
    basic = await _make_skill_level(db, "Basic-redo", 1)
    inter = await _make_skill_level(db, "Intermediate-redo", 2)
    advanced = await _make_skill_level(db, "Advanced-redo", 3)
    comp = await _make_competence(db, tenant, "Redo-comp")
    ind_basic = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=basic.id
    )
    ind_inter = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=inter.id
    )
    # Senior would need this one — but the assessment will not answer it.
    await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=advanced.id
    )

    grades_by_title: dict[str, DictionaryItem] = {}
    for i, (title, sl) in enumerate(
        (("Junior-r", basic), ("Middle-r", inter), ("Senior-r", advanced))
    ):
        grade = await _make_dict_item(db, tenant, "grade", title)
        grades_by_title[title] = grade
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=spec.id,
            sort_index=i + 1,
            passing_score=50,
        )
        db.add(gs)
        await db.commit()
        await db.refresh(gs)
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=sl.id,
            )
        )
        await db.commit()

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="MiddleOnly",
            employee_id=employee.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    # Target Middle — questionnaire only covers Basic + Intermediate.
    await service.set_assessment_criteria(
        db,
        tenant.id,
        created["id"],
        CriteriaUpdate(
            criteria_type="target_position",
            specialization_id=spec.id,
            grade_id=grades_by_title["Middle-r"].id,
            passing_score=50,
        ),
    )

    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await _live_scale(db, created["id"])
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind_basic.id,
        option_id=_option_by_weight(live, 5).id,
    )
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind_inter.id,
        option_id=_option_by_weight(live, 3).id,
    )
    await advance_to_in_progress(db, tenant.id, created["id"])
    await advance_to_done(db, tenant.id, created["id"])

    detail2 = await service.get_assessment_detail(db, tenant.id, created["id"])
    rec = detail2["recommendation"]
    assert rec is not None
    titles = [g["grade_title"] for g in rec["grades"]]
    assert "Senior-r" not in titles, (
        "Senior must be hidden when the assessment never reached its level"
    )
    assert titles == ["Junior-r", "Middle-r"], titles


@pytest.mark.asyncio
async def test_chart_persists_after_cancel_from_on_review(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """An assessment cancelled out of On Review keeps its chart payload."""
    spec = await _make_dict_item(db, tenant, "specialization", "C-spec")
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "C")
    ind = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=sl.id
    )
    grade = await _make_dict_item(db, tenant, "grade", "L")
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade.id,
        specialization_id=spec.id,
        sort_index=1,
        passing_score=10,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="Cancel",
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
            criteria_type="target_position",
            specialization_id=spec.id,
            grade_id=grade.id,
            passing_score=10,
        ),
    )
    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await _live_scale(db, created["id"])
    await _record(
        db,
        assessment_id=created["id"],
        participant_id=self_p["id"],
        indicator_id=ind.id,
        option_id=_option_by_weight(live, 4).id,
    )
    await advance_to_in_progress(db, tenant.id, created["id"])
    parts = (
        (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == uuid.UUID(str(created["id"]))
                )
            )
        )
        .scalars()
        .all()
    )
    for p in parts:
        p.is_completed = True
    await db.commit()
    await service.change_status(db, tenant.id, created["id"], "on_review")
    await service.change_status(db, tenant.id, created["id"], "cancelled")

    detail2 = await service.get_assessment_detail(db, tenant.id, created["id"])
    assert detail2["status_code"] == "cancelled"
    rec = detail2["recommendation"]
    assert rec is not None, "cancelled-from-on_review must keep the chart"
    assert rec["grades"][0]["percent"] == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_chart_skipped_for_pre_on_review_cancel(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Cancelling before On Review (no AssessmentResult rows) leaves the
    recommendation empty so the UI hides the chart for those records."""
    spec = await _make_dict_item(db, tenant, "specialization", "P-spec")
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "P")
    await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=sl.id
    )
    grade = await _make_dict_item(db, tenant, "grade", "P")
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade.id,
        specialization_id=spec.id,
        sort_index=1,
        passing_score=10,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()

    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="PreCancel",
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
            criteria_type="target_position",
            specialization_id=spec.id,
            grade_id=grade.id,
            passing_score=10,
        ),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "cancelled")

    # Sanity — no preliminary AssessmentResult row was written.
    a = await db.get(
        Assessment, uuid.UUID(str(created["id"])), options=[selectinload(Assessment.status)]
    )
    rec = await compute_grade_recommendation(db, tenant.id, a)
    assert rec is None
    # And no rows have been stored either.
    rows = (
        (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == uuid.UUID(str(created["id"]))
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
