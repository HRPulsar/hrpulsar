"""HRP-189 REDO Task 2: PDP items auto-seeded from the (specialization,
grade) link must only include materials at or below the target level for
each competence. QA flagged that the previous full-replace recompute
pulled every material on the competence regardless of grade — a Junior
plan would inherit Senior-level study time.
"""

import pytest
from app.modules.assessment import pdp_service as service
from app.modules.assessment.schemas import PDPCreate, PDPUpdate
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def grade_chain(db: AsyncSession, tenant):
    """Build a competence with three materials at three increasing skill
    levels (Basic / Intermediate / Advanced), plus two grades — Junior
    targeting Basic and Senior targeting Advanced — both attached to the
    same specialization.
    """
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        Material,
        SkillLevel,
    )
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    spec = DictionaryItem(
        type="specialization", title="Backend", tenant_id=tenant.id
    )
    grade_jr = DictionaryItem(type="grade", title="Junior", tenant_id=tenant.id)
    grade_sr = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
    group = DictionaryItem(type="dummy", title="ignore", tenant_id=tenant.id)
    db.add_all([spec, grade_jr, grade_sr, group])
    await db.flush()

    competence_group = CompetenceGroup(title="General", tenant_id=tenant.id)
    basic = SkillLevel(title="Basic", sort_index=0, tenant_id=tenant.id)
    intermediate = SkillLevel(
        title="Intermediate", sort_index=1, tenant_id=tenant.id
    )
    advanced = SkillLevel(title="Advanced", sort_index=2, tenant_id=tenant.id)
    db.add_all([competence_group, basic, intermediate, advanced])
    await db.flush()

    competence = Competence(
        title="Python", group_id=competence_group.id, tenant_id=tenant.id
    )
    db.add(competence)
    await db.flush()

    mat_basic = Material(
        title="Beginner book",
        competence_id=competence.id,
        skill_level_id=basic.id,
        tenant_id=tenant.id,
        sort_index=0,
    )
    mat_mid = Material(
        title="Mid course",
        competence_id=competence.id,
        skill_level_id=intermediate.id,
        tenant_id=tenant.id,
        sort_index=1,
    )
    mat_adv = Material(
        title="Architecture deep-dive",
        competence_id=competence.id,
        skill_level_id=advanced.id,
        tenant_id=tenant.id,
        sort_index=2,
    )
    db.add_all([mat_basic, mat_mid, mat_adv])
    await db.flush()

    gs_jr = GradeSpecialization(
        tenant_id=tenant.id, grade_id=grade_jr.id, specialization_id=spec.id
    )
    gs_sr = GradeSpecialization(
        tenant_id=tenant.id, grade_id=grade_sr.id, specialization_id=spec.id
    )
    db.add_all([gs_jr, gs_sr])
    await db.flush()

    db.add_all(
        [
            GradeCompetenceLink(
                grade_specialization_id=gs_jr.id,
                competence_id=competence.id,
                skill_level_id=basic.id,
            ),
            GradeCompetenceLink(
                grade_specialization_id=gs_sr.id,
                competence_id=competence.id,
                skill_level_id=advanced.id,
            ),
        ]
    )
    await db.commit()
    return {
        "spec": spec,
        "grade_jr": grade_jr,
        "grade_sr": grade_sr,
        "mat_basic": mat_basic,
        "mat_mid": mat_mid,
        "mat_adv": mat_adv,
    }


class TestPDPMaterialsCappedByGrade:
    async def test_junior_plan_only_includes_basic_level(
        self, db: AsyncSession, tenant, user, employee, grade_chain
    ):
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Junior growth",
                employee_id=employee.id,
                specialization_id=grade_chain["spec"].id,
                grade_id=grade_chain["grade_jr"].id,
            ),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["items"]) == 1
        titles = sorted(m["title"] for m in detail["items"][0]["materials"])
        assert titles == ["Beginner book"]

    async def test_senior_plan_includes_current_and_previous_levels(
        self, db: AsyncSession, tenant, user, employee, grade_chain
    ):
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Senior growth",
                employee_id=employee.id,
                specialization_id=grade_chain["spec"].id,
                grade_id=grade_chain["grade_sr"].id,
            ),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["items"]) == 1
        titles = sorted(m["title"] for m in detail["items"][0]["materials"])
        assert titles == [
            "Architecture deep-dive",
            "Beginner book",
            "Mid course",
        ]

    async def test_grade_change_recompute_filters_by_new_grade(
        self, db: AsyncSession, tenant, user, employee, grade_chain
    ):
        # Start as Senior (all three materials), then drop to Junior and
        # confirm the recompute keeps only the Basic-level material.
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Reshape",
                employee_id=employee.id,
                specialization_id=grade_chain["spec"].id,
                grade_id=grade_chain["grade_sr"].id,
            ),
        )
        await service.update_pdp(
            db,
            tenant.id,
            pdp["id"],
            PDPUpdate(grade_id=grade_chain["grade_jr"].id),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["items"]) == 1
        titles = sorted(m["title"] for m in detail["items"][0]["materials"])
        assert titles == ["Beginner book"]
