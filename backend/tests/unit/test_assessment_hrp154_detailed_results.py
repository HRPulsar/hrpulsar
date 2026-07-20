"""HRP-154: Detailed results block — per-competence/skill-level/indicator
breakdown for the Results page.

Covers:
- Structured shape (competence → skill levels → questions → roles +
  comments + overall).
- ``Specialization-All grades`` case: required level falls back to the
  highest skill level configured on the competence.
- All-``Don't know`` answers collapse to the dash markers documented in
  the ticket.
- RBAC: Platform admin / Admin / Manager pass; Employees get 403.
- Scope fence: a manager outside the assessee's division gets 404.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
)
from app.modules.assessment.schemas import (
    AssessmentCreate,
    ParticipantAdd,
)
from app.modules.auth.models import Role, user_roles
from app.modules.auth.models import User as AuthUser
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import advance_to_in_progress

pytestmark = pytest.mark.asyncio


# --- Helpers --------------------------------------------------------------


async def _make_user_with_employee(
    db: AsyncSession, tenant, suffix: str
) -> tuple[AuthUser, Employee]:
    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.flush()

    u = AuthUser(
        email=f"hrp154-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
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


async def _make_competence_with_levels(
    db: AsyncSession, tenant, suffix: str
) -> tuple[uuid.UUID, list[Indicator], list[SkillLevel], uuid.UUID]:
    """Two skill levels, one indicator each, plus a ``Hard skill``
    competence type via the dictionary."""
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    # Competence type lives in dictionary_items under type=competence_type.
    type_item = DictionaryItem(
        tenant_id=tenant.id,
        type="competence_type",
        title=f"Hard skill {suffix}",
    )
    db.add(type_item)
    await db.flush()

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"Grp-{suffix}")
    )
    comp = await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=f"Comp-{suffix}", group_id=group.id)
    )
    # Wire the type onto the freshly created competence row.
    from app.modules.competence.models import Competence

    comp_row = await db.get(Competence, comp.id)
    comp_row.competence_type_id = type_item.id
    await db.flush()

    skill_levels: list[SkillLevel] = []
    indicators: list[Indicator] = []
    for level_idx, level_title in enumerate(["Basic", "Advanced"]):
        sl = SkillLevel(
            title=f"{level_title}-{suffix}",
            sort_index=level_idx,
            tenant_id=tenant.id,
        )
        db.add(sl)
        await db.flush()
        skill_levels.append(sl)
        ind = Indicator(
            title=f"Ind-{suffix}-{level_idx}",
            weight=1,
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=tenant.id,
        )
        db.add(ind)
        await db.flush()
        indicators.append(ind)
    await db.commit()
    for ind in indicators:
        await db.refresh(ind)
    for sl in skill_levels:
        await db.refresh(sl)
    return comp.id, indicators, skill_levels, type_item.id


async def _seed_assessment_in_on_review(
    db: AsyncSession, tenant, user, employee, *, required_skill_level_id=None
):
    scale = await _make_scale(db, tenant)
    comp_id, indicators, skill_levels, type_item_id = (
        await _make_competence_with_levels(db, tenant, "det")
    )

    a = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title=f"360-det-{uuid.uuid4().hex[:6]}",
            employee_id=employee.id,
            type_code="360",
            scale_id=scale.id,
        ),
    )
    ac = AssessmentCompetence(
        assessment_id=a["id"],
        competence_id=comp_id,
        skill_level_id=required_skill_level_id,
    )
    db.add(ac)
    a_obj = await db.get(Assessment, a["id"])
    a_obj.criteria_type = "current_positions"
    await db.commit()

    detail = await service.get_assessment_detail(db, tenant.id, a["id"])
    self_part_id = next(
        p["id"] for p in detail["participants"] if p["role"] == "self"
    )
    _mgr_user, mgr_emp = await _make_user_with_employee(db, tenant, "mgrdet")
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
    neutral_opt = next(o for o in snap.options if o.is_neutral)

    # Re-fetch indicator ids on the live competence (they came back from
    # the helper but we want a fresh handle on them).
    ind_basic, ind_advanced = indicators

    # Self: weight=4 on Basic, weight=4 on Advanced (with a comment).
    db.add_all(
        [
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=self_part_id,
                indicator_id=ind_basic.id,
                answer_option_id=opt_by_weight[4].id,
            ),
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=self_part_id,
                indicator_id=ind_advanced.id,
                answer_option_id=opt_by_weight[4].id,
                comment="self thinks they nailed it",
            ),
        ]
    )
    # Manager: weight=2 on Basic, Don't know on Advanced (with a comment).
    db.add_all(
        [
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=mgr_part_id,
                indicator_id=ind_basic.id,
                answer_option_id=opt_by_weight[2].id,
                comment="seen better days",
            ),
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=mgr_part_id,
                indicator_id=ind_advanced.id,
                answer_option_id=neutral_opt.id,
            ),
        ]
    )
    for pid in (self_part_id, mgr_part_id):
        p = await db.get(AssessmentParticipant, pid)
        p.is_completed = True
    await db.commit()

    await advance_to_in_progress(db, tenant.id, a["id"])
    await service.change_status(db, tenant.id, a["id"], "on_review")

    return {
        "assessment_id": a["id"],
        "competence_id": comp_id,
        "indicators": indicators,
        "skill_levels": skill_levels,
        "type_item_id": type_item_id,
    }


# --- Service-level tests --------------------------------------------------


class TestDetailedResultsShape:
    async def test_structure_with_specific_required_level(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):

        # Pre-create context first so we know the Advanced level id, then
        # pass it as the explicit required level.
        scale = await _make_scale(db, tenant)
        comp_id, indicators, skill_levels, type_item_id = (
            await _make_competence_with_levels(db, tenant, "specific")
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Specific",
                employee_id=employee.id,
                type_code="360",
                scale_id=scale.id,
            ),
        )
        db.add(
            AssessmentCompetence(
                assessment_id=a["id"],
                competence_id=comp_id,
                skill_level_id=skill_levels[0].id,  # Basic
            )
        )
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        self_part_id = next(
            p["id"] for p in detail["participants"] if p["role"] == "self"
        )
        _, mgr_emp = await _make_user_with_employee(db, tenant, "specmgr")
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
        opt_by_weight = {
            o.weight: o for o in snap.options if not o.is_neutral
        }
        ind_basic, ind_advanced = indicators
        db.add_all(
            [
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=self_part_id,
                    indicator_id=ind_basic.id,
                    answer_option_id=opt_by_weight[4].id,
                ),
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=self_part_id,
                    indicator_id=ind_advanced.id,
                    answer_option_id=opt_by_weight[4].id,
                ),
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=mgr_part_id,
                    indicator_id=ind_basic.id,
                    answer_option_id=opt_by_weight[2].id,
                    comment="manager note",
                ),
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=mgr_part_id,
                    indicator_id=ind_advanced.id,
                    answer_option_id=opt_by_weight[2].id,
                ),
            ]
        )
        for pid in (self_part_id, mgr_part_id):
            p = await db.get(AssessmentParticipant, pid)
            p.is_completed = True
        await db.commit()
        await advance_to_in_progress(db, tenant.id, a["id"])
        await service.change_status(db, tenant.id, a["id"], "on_review")

        out = await service.get_detailed_results(db, tenant.id, a["id"])
        assert out["assessment_id"] == a["id"]
        assert len(out["competences"]) == 1
        comp = out["competences"][0]
        assert comp["competence_id"] == comp_id
        assert comp["competence_type_id"] == type_item_id
        assert comp["competence_type_title"].startswith("Hard skill")
        assert comp["required_skill_level_id"] == skill_levels[0].id
        assert comp["required_skill_level_title"].startswith("Basic")
        # Both roles answered with weights, so the avg lands at 75%.
        assert comp["percent"] == 75
        assert comp["all_dont_know"] is False

        # HRP-184: Detailed results only surfaces the skill levels that
        # were actually evaluated — Advanced is above the required Basic
        # cap, so it must be filtered out (same cascade as Question
        # preview / Take this assessment).
        assert [sl["skill_level_title"] for sl in comp["skill_levels"]] == [
            "Basic-specific",
        ]
        basic_level = comp["skill_levels"][0]
        # Per-level percent for Basic: self=100, manager=50 → mean 75.
        assert basic_level["percent_for_skill_level"] == 75
        # Per-question shape — single indicator, two roles, one comment.
        assert len(basic_level["questions"]) == 1
        q = basic_level["questions"][0]
        assert q["indicator_id"] == ind_basic.id
        assert [r["role"] for r in q["roles"]] == ["self", "manager"]
        assert q["roles"][0]["answer_weight"] == pytest.approx(4.0)
        assert q["roles"][0]["is_neutral"] is False
        assert q["roles"][1]["answer_weight"] == pytest.approx(2.0)
        assert q["overall_avg_weight"] == pytest.approx(3.0)
        assert q["overall_percent"] == 75
        assert len(q["comments"]) == 1
        assert q["comments"][0]["text"] == "manager note"
        assert q["comments"][0]["role"] == "manager"

    async def test_specialization_all_grades_uses_highest_required_level(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _seed_assessment_in_on_review(
            db, tenant, user, employee, required_skill_level_id=None
        )
        out = await service.get_detailed_results(db, tenant.id, ctx["assessment_id"])
        comp = out["competences"][0]
        # The Advanced level (sort_index 1) is highest, so it should win.
        assert comp["required_skill_level_id"] == ctx["skill_levels"][1].id
        assert comp["required_skill_level_title"].startswith("Advanced")

    async def test_hrp184_filters_levels_above_required(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-184: with an explicit required level of Basic, the Advanced
        level's questions must not show up — same cascade rule the
        questionnaire walks. The competence aggregate still reflects every
        answer the recompute saw (it runs before the filter), so this
        targets the skill-level surface only."""
        scale = await _make_scale(db, tenant)
        comp_id, indicators, skill_levels, _type_item_id = (
            await _make_competence_with_levels(db, tenant, "hrp184")
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="HRP-184",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        # Required = Basic (sort_index 0). Advanced (sort_index 1) is the
        # level we expect filtered out.
        db.add(
            AssessmentCompetence(
                assessment_id=a["id"],
                competence_id=comp_id,
                skill_level_id=skill_levels[0].id,
            )
        )
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
        opt_by_weight = {o.weight: o for o in snap.options if not o.is_neutral}
        ind_basic, ind_advanced = indicators
        # Answer both levels — the filter is what trims the response.
        db.add_all(
            [
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=self_part_id,
                    indicator_id=ind_basic.id,
                    answer_option_id=opt_by_weight[4].id,
                ),
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=self_part_id,
                    indicator_id=ind_advanced.id,
                    answer_option_id=opt_by_weight[4].id,
                ),
            ]
        )
        p = await db.get(AssessmentParticipant, self_part_id)
        p.is_completed = True
        await db.commit()
        await advance_to_in_progress(db, tenant.id, a["id"])
        await service.change_status(db, tenant.id, a["id"], "on_review")

        out = await service.get_detailed_results(db, tenant.id, a["id"])
        comp = out["competences"][0]
        titles = [sl["skill_level_title"] for sl in comp["skill_levels"]]
        assert titles == ["Basic-hrp184"]
        # The single included level still surfaces its question.
        questions = comp["skill_levels"][0]["questions"]
        assert [q["indicator_id"] for q in questions] == [ind_basic.id]

    async def test_all_dont_know_collapses_to_dashes(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant)
        comp_id, indicators, skill_levels, _type_item_id = (
            await _make_competence_with_levels(db, tenant, "dontknow")
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="DK",
                employee_id=employee.id,
                type_code="360",
                scale_id=scale.id,
            ),
        )
        db.add(
            AssessmentCompetence(
                assessment_id=a["id"],
                competence_id=comp_id,
                skill_level_id=skill_levels[0].id,
            )
        )
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
        neutral = next(o for o in snap.options if o.is_neutral)
        for ind in indicators:
            db.add(
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=self_part_id,
                    indicator_id=ind.id,
                    answer_option_id=neutral.id,
                )
            )
        p = await db.get(AssessmentParticipant, self_part_id)
        p.is_completed = True
        await db.commit()
        await advance_to_in_progress(db, tenant.id, a["id"])
        await service.change_status(db, tenant.id, a["id"], "on_review")

        out = await service.get_detailed_results(db, tenant.id, a["id"])
        comp = out["competences"][0]
        assert comp["all_dont_know"] is True
        assert comp["percent"] is None
        for sl in comp["skill_levels"]:
            assert sl["percent_for_skill_level"] is None
            assert sl["all_dont_know"] is True
            for q in sl["questions"]:
                assert q["overall_percent"] is None
                assert q["all_dont_know"] is True
                # The neutral marker still shows up on the role row.
                assert q["roles"][0]["is_neutral"] is True

    async def test_returns_empty_when_status_pre_review(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await _make_scale(db, tenant)
        comp_id, _ind, _sl, _t = await _make_competence_with_levels(
            db, tenant, "predraft"
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Pre",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp_id))
        a_obj = await db.get(Assessment, a["id"])
        a_obj.criteria_type = "current_positions"
        await db.commit()
        out = await service.get_detailed_results(db, tenant.id, a["id"])
        assert out == {"assessment_id": a["id"], "competences": []}


# --- HTTP / RBAC tests ----------------------------------------------------


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    """Vanilla employee role with no admin/manager privileges — perfect
    for the 403 check on the detailed-results endpoint."""
    result = await db.execute(
        select(Role).where(Role.code == "employee", Role.is_system == True)  # noqa: E712
    )
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_user_token(db: AsyncSession, tenant, employee_role) -> str:
    u = AuthUser(
        email=f"emp-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Plain",
        last_name="Employee",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(
        user_roles.insert().values(user_id=u.id, role_id=employee_role.id)
    )
    await db.commit()
    pos = Position(tenant_id=tenant.id, title="Plain Pos", source="manual")
    db.add(pos)
    await db.flush()
    db.add(
        Employee(
            user_id=u.id,
            tenant_id=tenant.id,
            position_id=pos.id,
            position_title=pos.title,
            hire_date=date(2024, 1, 15),
        )
    )
    await db.commit()
    return create_access_token(str(u.id), str(tenant.id))


class TestDetailedResultsHTTP:
    async def test_admin_can_read_detailed_results(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _seed_assessment_in_on_review(db, tenant, user, employee)
        resp = await auth_client.get(
            f"/api/assessments/{ctx['assessment_id']}/detailed-results"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["assessment_id"] == str(ctx["assessment_id"])
        assert len(body["competences"]) == 1

    async def test_employee_role_is_forbidden(
        self,
        client,
        employee_user_token,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _seed_assessment_in_on_review(db, tenant, user, employee)
        resp = await client.get(
            f"/api/assessments/{ctx['assessment_id']}/detailed-results",
            headers={"Authorization": f"Bearer {employee_user_token}"},
        )
        assert resp.status_code == 403
