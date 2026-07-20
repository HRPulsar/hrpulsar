"""Tests for the per-(material × specialization) override formula (POS7).

Covers:
- pure base set (no overrides)
- `hide` removes a base material in context
- `add` reveals a competence material only in context
- combination of `hide` and `add`
- override scoped to another specialization is ignored
- tenant isolation: overrides from another tenant don't leak
- guard: cannot create an override on a material that belongs to a different
  competence
- PDP integration: PDPItemMaterial-rows respect overrides at PDP creation
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from app.modules.assessment import pdp_service
from app.modules.assessment.models import PDPItem, PDPItemMaterial
from app.modules.assessment.schemas import PDPCreate
from app.modules.competence import material_overrides
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Material,
    SkillLevel,
)
from app.modules.dictionary.models import DictionaryItem
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def comp_with_two_materials(db: AsyncSession, tenant):
    group = CompetenceGroup(title="General", tenant_id=tenant.id)
    skill = SkillLevel(title="Basic")
    db.add_all([group, skill])
    await db.flush()

    competence = Competence(title="SQL", group_id=group.id, tenant_id=tenant.id)
    db.add(competence)
    await db.flush()

    m1 = Material(
        title="SQL Basics Book",
        competence_id=competence.id,
        skill_level_id=skill.id,
        tenant_id=tenant.id,
        sort_index=0,
    )
    m2 = Material(
        title="SQL Advanced Course",
        competence_id=competence.id,
        skill_level_id=skill.id,
        tenant_id=tenant.id,
        sort_index=1,
    )
    db.add_all([m1, m2])
    await db.commit()
    return {
        "group": group,
        "competence": competence,
        "skill": skill,
        "materials": [m1, m2],
    }


@pytest.fixture
async def specs(db: AsyncSession, tenant):
    backend = DictionaryItem(
        type="specialization", title="Backend", tenant_id=tenant.id
    )
    data = DictionaryItem(type="specialization", title="Data", tenant_id=tenant.id)
    db.add_all([backend, data])
    await db.commit()
    return {"backend": backend, "data": data}


class TestFormula:
    async def test_pure_base_no_overrides(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        result = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp_with_two_materials["competence"].id, specs["backend"].id
        )
        assert {m.title for m in result} == {"SQL Basics Book", "SQL Advanced Course"}

    async def test_hide_removes_base(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]
        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=m1.id,
            specialization_id=specs["backend"].id,
            mode="hide",
        )
        result = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["backend"].id
        )
        assert {m.title for m in result} == {"SQL Advanced Course"}

        # Other specialization keeps both
        other = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["data"].id
        )
        assert {m.title for m in other} == {"SQL Basics Book", "SQL Advanced Course"}

    async def test_add_only_in_context(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        """An `add` override marks a material as contextual: it disappears
        from the base set and only surfaces for specializations that have an
        `add` row."""
        comp = comp_with_two_materials["competence"]
        skill = comp_with_two_materials["skill"]

        contextual = Material(
            title="Backend-only postgres talk",
            competence_id=comp.id,
            skill_level_id=skill.id,
            tenant_id=tenant.id,
            sort_index=2,
        )
        db.add(contextual)
        await db.commit()

        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=contextual.id,
            specialization_id=specs["backend"].id,
            mode="add",
        )

        backend = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["backend"].id
        )
        assert "Backend-only postgres talk" in {m.title for m in backend}

        data = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["data"].id
        )
        # Single `add` for backend turns the material into a contextual one,
        # so other specializations no longer see it.
        assert "Backend-only postgres talk" not in {m.title for m in data}

        # No-spec callers (employees without specialization) still see the
        # plain base set, so the material stays visible there.
        plain = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, None
        )
        assert "Backend-only postgres talk" in {m.title for m in plain}

    async def test_combined_hide_and_add(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]
        skill = comp_with_two_materials["skill"]

        contextual = Material(
            title="Backend Cookbook",
            competence_id=comp.id,
            skill_level_id=skill.id,
            tenant_id=tenant.id,
            sort_index=10,
        )
        db.add(contextual)
        await db.commit()

        # Hide the basics book in backend, but include the cookbook there.
        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=m1.id,
            specialization_id=specs["backend"].id,
            mode="hide",
        )
        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=contextual.id,
            specialization_id=specs["data"].id,
            mode="hide",
        )

        backend = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["backend"].id
        )
        titles = {m.title for m in backend}
        assert "SQL Basics Book" not in titles
        assert "Backend Cookbook" in titles

    async def test_no_specialization_returns_base(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]
        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=m1.id,
            specialization_id=specs["backend"].id,
            mode="hide",
        )

        result = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, None
        )
        # specialization_id=None → fall back to base: hide must NOT apply
        assert {m.title for m in result} == {"SQL Basics Book", "SQL Advanced Course"}


class TestGuards:
    async def test_invalid_mode_rejected(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]
        with pytest.raises(HTTPException) as exc:
            await material_overrides.add_material_override(
                db,
                tenant.id,
                comp.id,
                material_id=m1.id,
                specialization_id=specs["backend"].id,
                mode="silence",
            )
        assert exc.value.status_code == 400

    async def test_material_must_belong_to_competence(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        # Create another competence with its own material
        group = comp_with_two_materials["group"]
        skill = comp_with_two_materials["skill"]
        other = Competence(title="Python", group_id=group.id, tenant_id=tenant.id)
        db.add(other)
        await db.flush()
        foreign_mat = Material(
            title="Python guide",
            competence_id=other.id,
            skill_level_id=skill.id,
            tenant_id=tenant.id,
        )
        db.add(foreign_mat)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await material_overrides.add_material_override(
                db,
                tenant.id,
                comp_with_two_materials["competence"].id,
                material_id=foreign_mat.id,
                specialization_id=specs["backend"].id,
                mode="hide",
            )
        assert exc.value.status_code == 400

    async def test_unknown_specialization_rejected(
        self, db: AsyncSession, tenant, comp_with_two_materials
    ):
        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]
        with pytest.raises(HTTPException) as exc:
            await material_overrides.add_material_override(
                db,
                tenant.id,
                comp.id,
                material_id=m1.id,
                specialization_id=uuid.uuid4(),
                mode="hide",
            )
        assert exc.value.status_code == 404


class TestTenantIsolation:
    async def test_other_tenant_overrides_ignored(
        self, db: AsyncSession, tenant, comp_with_two_materials, specs
    ):
        from app.modules.company.models import Tenant
        from app.modules.competence.models import MaterialSpecializationOverride

        other_tenant = Tenant(
            name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
        )
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)

        comp = comp_with_two_materials["competence"]
        m1 = comp_with_two_materials["materials"][0]

        # Forge an override for the other tenant directly to bypass guards.
        db.add(
            MaterialSpecializationOverride(
                tenant_id=other_tenant.id,
                material_id=m1.id,
                specialization_id=specs["backend"].id,
                mode="hide",
            )
        )
        await db.commit()

        # First tenant still sees both materials — other tenant's override
        # must not leak.
        result = await material_overrides.get_materials_for_specialization(
            db, tenant.id, comp.id, specs["backend"].id
        )
        assert {m.title for m in result} == {"SQL Basics Book", "SQL Advanced Course"}


class TestPDPIntegration:
    async def test_pdp_auto_materials_respect_hide(
        self, db: AsyncSession, tenant, user, comp_with_two_materials, specs
    ):
        from app.modules.employee.models import Employee
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        employee = Employee(
            user_id=user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 15),
        )
        db.add(employee)
        await db.flush()

        comp = comp_with_two_materials["competence"]
        skill = comp_with_two_materials["skill"]
        grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        db.add(grade)
        await db.flush()

        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=specs["backend"].id,
        )
        db.add(gs)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=skill.id,
            )
        )
        await db.commit()

        # Hide the basics book for backend.
        m1 = comp_with_two_materials["materials"][0]
        await material_overrides.add_material_override(
            db,
            tenant.id,
            comp.id,
            material_id=m1.id,
            specialization_id=specs["backend"].id,
            mode="hide",
        )

        pdp = await pdp_service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Backend plan",
                employee_id=employee.id,
                specialization_id=specs["backend"].id,
                grade_id=grade.id,
            ),
        )

        items_q = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp["id"]))
        items = list(items_q.scalars().all())
        assert len(items) == 1

        mats_q = await db.execute(
            select(PDPItemMaterial).where(PDPItemMaterial.item_id == items[0].id)
        )
        titles = {m.title for m in mats_q.scalars().all()}
        assert titles == {"SQL Advanced Course"}
