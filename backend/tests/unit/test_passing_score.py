"""Passing score & grade recommendation tests."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentParticipant,
)
from app.modules.assessment.recommendation import compute_grade_recommendation
from app.modules.assessment.schemas import (
    AssessmentCreate,
    CompetenceCriteriaItem,
    CriteriaUpdate,
    MassAssessmentCreate,
)
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


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


async def _make_indicator(
    db, tenant, *, competence_id, skill_level_id, weight: int = 1
) -> Indicator:
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


async def _make_grade_specialization(
    db, tenant, *, spec_id, grade_id, sort_index, passing_score=75
) -> GradeSpecialization:
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade_id,
        specialization_id=spec_id,
        sort_index=sort_index,
        passing_score=passing_score,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)
    return gs


async def _link_competence(
    db, *, gs_id, competence_id, skill_level_id
) -> GradeCompetenceLink:
    link = GradeCompetenceLink(
        grade_specialization_id=gs_id,
        competence_id=competence_id,
        skill_level_id=skill_level_id,
    )
    db.add(link)
    await db.commit()
    return link


async def _make_scale_5(db, tenant, *, with_neutral: bool = False) -> AnswerScale:
    """5-point scale, weights 1..5. Optional 'I don't know' neutral option."""
    scale = AnswerScale(
        title=f"Scale-{uuid.uuid4().hex[:6]}",
        is_default=False,
        tenant_id=tenant.id,
    )
    db.add(scale)
    await db.flush()

    for i, weight in enumerate([1, 2, 3, 4, 5], start=0):
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=f"L{weight}",
                code=f"l{weight}",
                weight=weight,
                sort_index=i,
                is_neutral=False,
            )
        )
    if with_neutral:
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title="N/A",
                code="na",
                weight=None,
                sort_index=99,
                is_neutral=True,
            )
        )

    await db.commit()

    res = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == scale.id)
    )
    return res.scalar_one()


async def _record_answer_direct(
    db, *, assessment_id, participant_id, indicator_id, option_id
) -> None:
    """Insert AssessmentAnswer directly. Bypasses ownership / status checks
    needed for setting up a 'done' scenario inside the recommendation tests."""
    db.add(
        AssessmentAnswer(
            assessment_id=assessment_id,
            participant_id=participant_id,
            indicator_id=indicator_id,
            answer_option_id=option_id,
        )
    )
    await db.commit()


async def _load_active_scale(db, assessment_id) -> AnswerScale:
    """After draft→sent, ``assessment.scale_id`` points at the snapshot scale.
    Resolve whatever the live scale is so tests can map weights to current
    option IDs."""
    a = await db.get(Assessment, assessment_id)
    res = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == a.scale_id)
    )
    return res.scalar_one()


async def _add_participant_direct(db, *, assessment_id, user_id, role: str):
    p = AssessmentParticipant(
        assessment_id=assessment_id,
        user_id=user_id,
        role=role,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest_asyncio.fixture
async def extra_user(db, tenant):
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser

    u = AuthUser(
        email=f"reviewer-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="Rev",
        last_name="Iewer",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _set_assessment_status(db, assessment_id, status_code, statuses):
    """Force-set the status without going through change_status() (which
    would also trigger recompute). Used for low-level recommendation unit
    tests where we want full control over the input state."""
    a = await db.get(
        Assessment, assessment_id, options=[selectinload(Assessment.status)]
    )
    a.status_id = statuses[status_code].id
    await db.commit()
    res = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.id == assessment_id)
    )
    return res.scalar_one()


async def _build_target_position_scenario(
    db,
    tenant,
    user,
    employee,
    assessment_statuses,
    assessment_types,
    *,
    scale_with_neutral: bool = False,
    grade_count: int = 3,
    indicator_weights: tuple[int, ...] = (1,),
    grade_threshold: int = 75,
    extra_grades_without_links: int = 0,
):
    """Wire a target_position assessment with N grades, one shared competence,
    and a configurable indicator-weight pattern. Returns a context dict the
    individual tests further specialize (answers, calibration, etc).
    """
    spec = await _make_dict_item(db, tenant, "specialization", "Backend")
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "Comp")

    indicators = []
    for w in indicator_weights:
        ind = await _make_indicator(
            db, tenant, competence_id=comp.id, skill_level_id=sl.id, weight=w
        )
        indicators.append(ind)

    grades = []
    grade_specs = []
    for i in range(grade_count):
        grade = await _make_dict_item(db, tenant, "grade", f"Grade-{i + 1}")
        grades.append(grade)
        gs = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=i + 1,
            passing_score=grade_threshold,
        )
        grade_specs.append(gs)
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=sl.id
        )

    for j in range(extra_grades_without_links):
        empty_grade = await _make_dict_item(db, tenant, "grade", f"Empty-{j + 1}")
        gs_empty = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=empty_grade.id,
            sort_index=grade_count + j + 1,
            passing_score=grade_threshold,
        )
        grades.append(empty_grade)
        grade_specs.append(gs_empty)

    scale = await _make_scale_5(db, tenant, with_neutral=scale_with_neutral)

    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="Recommendation",
            employee_id=employee.id,
            type_code="360",
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
            grade_id=None,
            passing_score=grade_threshold,
        ),
    )

    return {
        "spec": spec,
        "skill_level": sl,
        "competence": comp,
        "indicators": indicators,
        "grades": grades,
        "grade_specs": grade_specs,
        "scale": scale,
        "assessment_id": created["id"],
    }


def _option_by_weight(scale: AnswerScale, weight: int | None) -> AnswerOption:
    for o in scale.options:
        if o.weight == weight and not o.is_neutral:
            return o
    raise AssertionError(f"No option with weight={weight}")


def _neutral_option(scale: AnswerScale) -> AnswerOption:
    for o in scale.options:
        if o.is_neutral:
            return o
    raise AssertionError("No neutral option")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPassingScoreDefaults:
    async def test_grade_specialization_default_75(self, db, tenant):
        """Test 1 — grade-specialization dictionary defaults passing_score to 75%."""
        spec = await _make_dict_item(db, tenant, "specialization", "QA")
        grade = await _make_dict_item(db, tenant, "grade", "Junior")
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=spec.id,
            sort_index=0,
        )
        db.add(gs)
        await db.commit()
        await db.refresh(gs)
        assert gs.passing_score == 75


class TestSetCriteriaPassingScore:
    async def test_target_position_pulls_from_grade_specialization(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 2 — target_position + a concrete grade pulls passing_score from the dictionary."""
        spec = await _make_dict_item(db, tenant, "specialization", "Dev")
        grade = await _make_dict_item(db, tenant, "grade", "Junior")
        sl = await _make_skill_level(db, "Basic", 1)
        comp = await _make_competence(db, tenant, "C1")
        gs = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=1,
            passing_score=82,
        )
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=sl.id
        )

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Pull from spec",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=grade.id,
                # no explicit passing_score → pulled from gs (82)
            ),
        )
        assert result["passing_score"] == 82

    async def test_explicit_passing_score_overrides_default(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 3 — data.passing_score overrides the dictionary value."""
        spec = await _make_dict_item(db, tenant, "specialization", "PM")
        grade = await _make_dict_item(db, tenant, "grade", "Lead")
        sl = await _make_skill_level(db, "L", 1)
        comp = await _make_competence(db, tenant, "C2")
        gs = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=1,
            passing_score=75,
        )
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=sl.id
        )
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Override",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=grade.id,
                passing_score=90,
            ),
        )
        assert result["passing_score"] == 90

    async def test_hrp183_current_positions_defaults_to_75(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """HRP-183: current_positions now keeps a passing_score (75 default)
        because the Recommended grade chart is built for it too."""
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="CP-PS",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(criteria_type="current_positions"),
        )
        assert result["passing_score"] == 75

    async def test_hrp183_individual_competences_returns_null(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """HRP-183: Individual competences criteria stores NULL even when
        the request includes a passing_score — the field has no UI and
        produces no chart."""
        comp = await _make_competence(db, tenant, "ICComp")
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="IC-PS",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="competences",
                competences=[CompetenceCriteriaItem(competence_id=comp.id)],
                passing_score=80,
            ),
        )
        assert result["passing_score"] is None

    async def test_target_position_all_grades_defaults_to_75(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """target_position + every grade without an explicit value falls back to 75."""
        spec = await _make_dict_item(db, tenant, "specialization", "Spec3")
        grade = await _make_dict_item(db, tenant, "grade", "Mid")
        sl = await _make_skill_level(db, "L", 1)
        comp = await _make_competence(db, tenant, "Cm")
        gs = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=1,
            passing_score=80,
        )
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=sl.id
        )
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="AllG",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=None,
            ),
        )
        assert result["passing_score"] == 75

    async def test_set_group_criteria_propagates_passing_score(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 4 — set_group_criteria propagates passing_score to every non-terminal child.

        HRP-183: ``competences`` doesn't render the input (no Recommended
        grade chart), so the snapshot stays NULL even when callers pass an
        explicit value. The propagation still happens, just to NULL.
        """
        comp = await _make_competence(db, tenant, "GroupComp")

        mass = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="MassPS",
                employee_ids=[employee.id],
                type_code="self",
            ),
        )

        result = await service.set_group_criteria(
            db,
            tenant.id,
            mass["id"],
            CriteriaUpdate(
                criteria_type="competences",
                competences=[CompetenceCriteriaItem(competence_id=comp.id)],
                passing_score=66,
            ),
        )
        assert result["passing_score"] is None
        for a in result["assessments"]:
            detail = await service.get_assessment_detail(db, tenant.id, a["id"])
            assert detail["passing_score"] is None


class TestRecommendationGuards:
    async def test_returns_none_for_current_positions(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 5 — criteria_type='current_positions' → None."""
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="CP", employee_id=employee.id, type_code="self"),
        )
        a = await db.get(
            Assessment,
            created["id"],
            options=[selectinload(Assessment.status)],
        )
        a.criteria_type = "current_positions"
        a.passing_score = 75
        a.status_id = assessment_statuses["done"].id
        await db.commit()
        a = await db.get(
            Assessment,
            created["id"],
            options=[selectinload(Assessment.status)],
        )

        rec = await compute_grade_recommendation(db, tenant.id, a)
        assert rec is None

    async def test_returns_none_when_not_done(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 6 — status != done → None."""
        ctx = await _build_target_position_scenario(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        a = await db.get(
            Assessment,
            ctx["assessment_id"],
            options=[selectinload(Assessment.status)],
        )
        # Status is still draft after set_criteria
        rec = await compute_grade_recommendation(db, tenant.id, a)
        assert rec is None

    async def test_returns_none_when_passing_score_null(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 17 — legacy passing_score=NULL → None."""
        ctx = await _build_target_position_scenario(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        # Wipe passing_score to simulate a legacy assessment
        a = await db.get(Assessment, ctx["assessment_id"])
        a.passing_score = None
        a.status_id = assessment_statuses["done"].id
        await db.commit()
        a = await db.get(
            Assessment,
            ctx["assessment_id"],
            options=[selectinload(Assessment.status)],
        )

        rec = await compute_grade_recommendation(db, tenant.id, a)
        assert rec is None


class TestRecommendationFormula:
    async def test_happy_path_picks_highest_passed_grade(
        self,
        db,
        tenant,
        user,
        employee,
        extra_user,
        assessment_statuses,
        assessment_types,
    ):
        """Test 7 — 3 grades, 2 roles: pick the highest grade that meets the score."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=3,
            grade_threshold=75,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        # Self participant exists from create_assessment auto-add
        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")
        manager_p = await _add_participant_direct(
            db, assessment_id=a_id, user_id=extra_user.id, role="manager"
        )

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt4 = _option_by_weight(scale, 4)  # 4/5 = 80%
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt4.id,
        )
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=manager_p.id,
            indicator_id=ind.id,
            option_id=opt4.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        assert rec is not None
        assert rec["passing_score"] == 75
        # All 3 grades sit at 80% — pick highest sort_index (Grade-3, sort=3).
        assert rec["recommended_grade_passed"] is True
        assert rec["recommended_grade_title"] == "Grade-3"
        for item in rec["grades"]:
            assert item["passed"] is True
            assert item["percent"] == pytest.approx(80.0)

    async def test_nobody_passed_picks_max_percent(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 8 — nobody passes → fall back to the grade with the highest %."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=2,
            grade_threshold=90,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt3 = _option_by_weight(scale, 3)  # 3/5 = 60%
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt3.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        assert rec is not None
        assert rec["recommended_grade_passed"] is False
        # Both grades are at 60% — tie broken by max(percent), then list order;
        # both have percent==60 so any of them is acceptable, but it must be eligible.
        assert rec["recommended_grade_id"] is not None
        for item in rec["grades"]:
            assert item["passed"] is False
            assert item["missing_percent"] == pytest.approx(30.0)

    async def test_grade_without_competences_is_excluded(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 9 — grade with no competences → excluded=True."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=2,
            extra_grades_without_links=1,
            grade_threshold=70,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt4 = _option_by_weight(scale, 4)
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt4.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        excluded = [g for g in rec["grades"] if g["excluded"]]
        assert len(excluded) == 1
        # Excluded grade not selected as recommendation
        assert rec["recommended_grade_id"] != excluded[0]["grade_id"]

    async def test_role_without_answers_skipped_in_average(
        self,
        db,
        tenant,
        user,
        employee,
        extra_user,
        assessment_statuses,
        assessment_types,
    ):
        """Test 10 — a role with no answers is excluded from averaging."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=1,
            grade_threshold=75,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")
        # Add a manager participant but record no answers for them
        await _add_participant_direct(
            db, assessment_id=a_id, user_id=extra_user.id, role="manager"
        )

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt5 = _option_by_weight(scale, 5)  # 100%
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt5.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        # Only self contributed — the percent must equal self's 100%, not be
        # diluted by the silent manager.
        assert rec["grades"][0]["percent"] == pytest.approx(100.0)

    async def test_indicator_weight_changes_result(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 11 — indicator weights re-weight the final result."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=1,
            indicator_weights=(1, 9),
            grade_threshold=50,
        )
        ind1, ind2 = ctx["indicators"]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        # Low score for the low-weight indicator, high score for the heavy one.
        opt2 = _option_by_weight(scale, 2)  # 2/5
        opt4 = _option_by_weight(scale, 4)  # 4/5
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind1.id,
            option_id=opt2.id,
        )
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind2.id,
            option_id=opt4.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        # Weighted: (2*1 + 4*9) / (1+9) / 5 * 100 = 76. Simple mean would be 60.
        assert detail2["recommendation"]["grades"][0]["percent"] == pytest.approx(76.0)

    async def test_neutral_answers_ignored(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 12 — neutral answers are excluded from the score."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            scale_with_neutral=True,
            grade_count=1,
            indicator_weights=(1, 1),
            grade_threshold=50,
        )
        ind1, ind2 = ctx["indicators"]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        # ind1: weight=4 (80%); ind2: neutral → ignored. Result must be 80%.
        opt4 = _option_by_weight(scale, 4)
        n = _neutral_option(scale)
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind1.id,
            option_id=opt4.id,
        )
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind2.id,
            option_id=n.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        assert detail2["recommendation"]["grades"][0]["percent"] == pytest.approx(80.0)

    async def test_hierarchy_picks_highest_sort_index(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 13 — on ties, pick the grade with the higher sort_index."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=3,
            grade_threshold=50,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt5 = _option_by_weight(scale, 5)  # 100% → all 3 grades pass
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt5.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        winning = next(
            g for g in rec["grades"] if g["grade_id"] == rec["recommended_grade_id"]
        )
        # The grade with the largest sort_index must win when all three pass.
        assert winning["sort_index"] == max(g["sort_index"] for g in rec["grades"])

    async def test_calibration_does_not_override_recommendation(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 14 — calibration does not replace the raw % in the recommendation."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=1,
            grade_threshold=50,
        )
        ind = ctx["indicators"][0]
        comp = ctx["competence"]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt4 = _option_by_weight(scale, 4)  # 80%
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt4.id,
        )

        # Manually inject a calibrated_score that *disagrees* with the raw 80%.
        # Recommendation must stay anchored on the raw average.
        from app.modules.assessment.schemas import (
            CalibrateItem as _CI,
        )

        await service.calibrate(
            db, tenant.id, a_id, [_CI(competence_id=comp.id, calibrated_score=1.0)]
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        assert detail2["recommendation"]["grades"][0]["percent"] == pytest.approx(80.0)

    async def test_passing_score_zero_passes_everything(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 15a — passing_score=0 → every grade passes."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=2,
            grade_threshold=0,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt1 = _option_by_weight(scale, 1)  # 20%
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt1.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        assert rec["recommended_grade_passed"] is True
        for g in rec["grades"]:
            assert g["passed"] is True

    async def test_passing_score_hundred_requires_perfect(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 15b — passing_score=100 → only a perfect score qualifies."""
        ctx = await _build_target_position_scenario(
            db,
            tenant,
            user,
            employee,
            assessment_statuses,
            assessment_types,
            grade_count=1,
            grade_threshold=100,
        )
        ind = ctx["indicators"][0]
        a_id = ctx["assessment_id"]

        detail = await service.get_assessment_detail(db, tenant.id, a_id)
        self_p = next(p for p in detail["participants"] if p["role"] == "self")

        await seed_send_prereqs(db, tenant.id, a_id)

        await service.change_status(db, tenant.id, a_id, "sent")
        scale = await _load_active_scale(db, a_id)
        opt4 = _option_by_weight(scale, 4)  # 80% — not perfect
        await _record_answer_direct(
            db,
            assessment_id=a_id,
            participant_id=self_p["id"],
            indicator_id=ind.id,
            option_id=opt4.id,
        )

        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        detail2 = await service.get_assessment_detail(db, tenant.id, a_id)
        rec = detail2["recommendation"]
        assert rec["recommended_grade_passed"] is False
        assert rec["grades"][0]["passed"] is False


class TestCriteriaLockAfterStart:
    async def test_set_criteria_blocked_after_sent(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Test 16 — set_assessment_criteria fails once the assessment is past 'sent'."""
        spec = await _make_dict_item(db, tenant, "specialization", "Locked")
        grade = await _make_dict_item(db, tenant, "grade", "Lvl")
        sl = await _make_skill_level(db, "Lvl", 1)
        comp = await _make_competence(db, tenant, "LC")
        gs = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=1,
            passing_score=75,
        )
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=sl.id
        )

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Lock", employee_id=employee.id, type_code="self"),
        )
        await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        await seed_send_prereqs(db, tenant.id, created["id"])

        await service.change_status(db, tenant.id, created["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.set_assessment_criteria(
                db,
                tenant.id,
                created["id"],
                CriteriaUpdate(
                    criteria_type="target_position",
                    specialization_id=spec.id,
                    grade_id=grade.id,
                    passing_score=99,
                ),
            )
        assert exc.value.status_code == 400
