import uuid

import pytest
from app.modules.competence import service
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
    SkillLevel,
)
from app.modules.competence.schemas import (
    CompetenceBulkCreate,
    CompetenceBulkCreateItem,
    CompetenceCreate,
    CompetenceGroupCreate,
    CompetenceGroupUpdate,
    CompetenceUpdate,
    IndicatorCreate,
    IndicatorUpdate,
    MaterialCreate,
    MaterialUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestCompetenceGroups:
    async def test_create_group(self, db: AsyncSession, tenant):
        data = CompetenceGroupCreate(title="Technical Skills", description="Tech")
        group = await service.create_group(db, tenant.id, data)
        assert group.title == "Technical Skills"
        assert group.tenant_id == tenant.id

    async def test_create_child_group(self, db: AsyncSession, tenant):
        parent = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Parent")
        )
        child = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Child", parent_id=parent.id)
        )
        assert child.parent_id == parent.id

    async def test_get_competence_tree(self, db: AsyncSession, tenant):
        parent = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root Group")
        )
        await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Sub Group", parent_id=parent.id)
        )

        tree = await service.get_competence_tree(db, tenant.id)
        assert len(tree) >= 1

    async def test_update_group(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Old")
        )
        updated = await service.update_group(
            db, tenant.id, group.id, CompetenceGroupUpdate(title="New")
        )
        assert updated.title == "New"

    async def test_delete_group(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Delete Me")
        )
        await service.delete_group(db, tenant.id, group.id)

    async def test_child_inherits_inactive_parent(
        self, db: AsyncSession, tenant
    ):
        # HRP-118: a new child under an inactive parent stays inactive even
        # if the create-payload defaults `is_active=True`.
        parent = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Hidden", is_active=False)
        )
        child = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="Child", parent_id=parent.id),
        )
        assert child.is_active is False
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=parent.id)
        )
        assert comp.is_active is False


class TestCompetences:
    async def test_create_competence(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Group")
        )
        data = CompetenceCreate(
            title="Python", group_id=group.id, description="Python dev"
        )
        comp = await service.create_competence(db, tenant.id, data)
        assert comp.title == "Python"
        assert comp.group_id == group.id

    async def test_get_competence_detail(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="Go", group_id=group.id)
        )

        detail = await service.get_competence_detail(db, tenant.id, comp.id)
        assert detail["title"] == "Go"
        assert "indicators" in detail

    async def test_update_competence(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="Old", group_id=group.id)
        )
        updated = await service.update_competence(
            db, tenant.id, comp.id, CompetenceUpdate(title="New")
        )
        assert updated.title == "New"

    async def test_delete_competence(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="Del", group_id=group.id)
        )
        await service.delete_competence(db, tenant.id, comp.id)

    async def test_bulk_create_competences(
        self, db: AsyncSession, tenant
    ):
        # HRP-108: a single bulk call persists every row atomically and
        # stamps tenant + group on each new competence.
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Bulk")
        )
        payload = CompetenceBulkCreate(
            items=[
                CompetenceBulkCreateItem(title="Python", description="PY"),
                CompetenceBulkCreateItem(title="Go"),
                CompetenceBulkCreateItem(title="Rust"),
            ]
        )
        created = await service.bulk_create_competences(
            db, tenant.id, group.id, payload
        )
        assert {c.title for c in created} == {"Python", "Go", "Rust"}
        assert all(c.group_id == group.id for c in created)
        assert all(c.tenant_id == tenant.id for c in created)

    async def test_bulk_create_competences_invalid_group(
        self, db: AsyncSession, tenant
    ):
        payload = CompetenceBulkCreate(
            items=[CompetenceBulkCreateItem(title="X")]
        )
        with pytest.raises(HTTPException) as exc:
            await service.bulk_create_competences(
                db, tenant.id, uuid.uuid4(), payload
            )
        assert exc.value.status_code == 400


class TestIndicators:
    async def test_create_indicator(self, db: AsyncSession, tenant):
        from app.modules.competence.models import SkillLevel
        from sqlalchemy import select

        # Ensure a skill level exists
        result = await db.execute(select(SkillLevel).limit(1))
        sl = result.scalar_one_or_none()
        if not sl:
            sl = SkillLevel(title="Junior", sort_index=0)
            db.add(sl)
            await db.commit()
            await db.refresh(sl)

        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )

        data = IndicatorCreate(
            title="Writes clean code", weight=1, sort_index=0, skill_level_id=sl.id
        )
        ind = await service.create_indicator(db, tenant.id, comp.id, data)
        assert ind.title == "Writes clean code"
        assert ind.competence_id == comp.id


# --- Helper to create a skill level ---


async def _ensure_skill_level(db) -> SkillLevel:
    from sqlalchemy import select

    result = await db.execute(select(SkillLevel).limit(1))
    sl = result.scalar_one_or_none()
    if not sl:
        sl = SkillLevel(title="Junior", sort_index=0)
        db.add(sl)
        await db.commit()
        await db.refresh(sl)
    return sl


# --- Origin protection: groups ---


class TestGroupOriginProtection:
    """Groups with tenant_id=None (origin) cannot be updated or deleted."""

    async def test_create_group_invalid_parent(self, db: AsyncSession, tenant):
        data = CompetenceGroupCreate(title="Bad Child", parent_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            await service.create_group(db, tenant.id, data)
        assert exc.value.status_code == 400

    async def test_update_group_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.update_group(
                db, tenant.id, uuid.uuid4(), CompetenceGroupUpdate(title="X")
            )
        assert exc.value.status_code == 404

    async def test_update_origin_group_forbidden(self, db: AsyncSession, tenant):
        origin = CompetenceGroup(title="Origin Group", tenant_id=None, sort_index=0)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)

        with pytest.raises(HTTPException) as exc:
            await service.update_group(
                db, tenant.id, origin.id, CompetenceGroupUpdate(title="Hacked")
            )
        assert exc.value.status_code == 403

    async def test_update_group_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="Other")
        )

        with pytest.raises(HTTPException) as exc:
            await service.update_group(
                db, tenant.id, group.id, CompetenceGroupUpdate(title="Stolen")
            )
        assert exc.value.status_code == 404

    async def test_delete_group_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_group(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_delete_origin_group_forbidden(self, db: AsyncSession, tenant):
        origin = CompetenceGroup(title="Origin Del", tenant_id=None, sort_index=0)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)

        with pytest.raises(HTTPException) as exc:
            await service.delete_group(db, tenant.id, origin.id)
        assert exc.value.status_code == 403

    async def test_delete_group_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other2", slug=f"oth2-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="Other2")
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_group(db, tenant.id, group.id)
        assert exc.value.status_code == 404


# --- Origin protection: competences ---


class TestCompetenceOriginProtection:
    async def test_create_competence_invalid_group(self, db: AsyncSession, tenant):
        data = CompetenceCreate(title="Bad", group_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            await service.create_competence(db, tenant.id, data)
        assert exc.value.status_code == 400

    async def test_update_competence_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.update_competence(
                db, tenant.id, uuid.uuid4(), CompetenceUpdate(title="X")
            )
        assert exc.value.status_code == 404

    async def test_update_origin_competence_forbidden(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        origin_comp = Competence(title="Origin Comp", group_id=group.id, tenant_id=None)
        db.add(origin_comp)
        await db.commit()
        await db.refresh(origin_comp)

        with pytest.raises(HTTPException) as exc:
            await service.update_competence(
                db, tenant.id, origin_comp.id, CompetenceUpdate(title="Hacked")
            )
        assert exc.value.status_code == 403

    async def test_update_competence_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherC", slug=f"othc-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OC", group_id=group.id)
        )

        with pytest.raises(HTTPException) as exc:
            await service.update_competence(
                db, tenant.id, comp.id, CompetenceUpdate(title="Stolen")
            )
        assert exc.value.status_code == 404

    async def test_delete_competence_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_competence(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_delete_origin_competence_forbidden(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="GD")
        )
        origin_comp = Competence(title="Origin Del", group_id=group.id, tenant_id=None)
        db.add(origin_comp)
        await db.commit()
        await db.refresh(origin_comp)

        with pytest.raises(HTTPException) as exc:
            await service.delete_competence(db, tenant.id, origin_comp.id)
        assert exc.value.status_code == 403

    async def test_delete_competence_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherD", slug=f"othd-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OGD")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OCD", group_id=group.id)
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_competence(db, tenant.id, comp.id)
        assert exc.value.status_code == 404


# --- Competence detail edge cases ---


class TestCompetenceDetailEdgeCases:
    async def test_detail_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_competence_detail(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_detail_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherDet", slug=f"othdet-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="DetG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="DetC", group_id=group.id)
        )

        with pytest.raises(HTTPException) as exc:
            await service.get_competence_detail(db, tenant.id, comp.id)
        assert exc.value.status_code == 404

    async def test_detail_origin_competence_visible(self, db: AsyncSession, tenant):
        """Origin competences (tenant_id=None) should be visible to any tenant."""
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="OrigVis")
        )
        origin_comp = Competence(
            title="Visible Origin", group_id=group.id, tenant_id=None
        )
        db.add(origin_comp)
        await db.commit()
        await db.refresh(origin_comp)

        detail = await service.get_competence_detail(db, tenant.id, origin_comp.id)
        assert detail["title"] == "Visible Origin"
        assert detail["tenant_id"] is None


# --- Competence tree with competences ---


class TestCompetenceTreeWithCompetences:
    async def test_tree_includes_competences(self, db: AsyncSession, tenant):
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title=f"TreeG-{uuid.uuid4().hex[:6]}")
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="TreeComp", group_id=group.id)
        )

        tree = await service.get_competence_tree(db, tenant.id)
        found = [n for n in tree if n.id == group.id]
        assert len(found) == 1
        assert len(found[0].competences) >= 1
        first_comp = found[0].competences[0]
        # May be dict or CompetenceRead depending on Pydantic parsing
        title = (
            first_comp["title"] if isinstance(first_comp, dict) else first_comp.title
        )
        assert title == "TreeComp"


# --- Skill levels ---


class TestSkillLevels:
    async def test_list_skill_levels(self, db: AsyncSession):
        await _ensure_skill_level(db)
        levels = await service.list_skill_levels(db)
        assert len(levels) >= 1
        assert levels[0].title is not None


# --- Indicator CRUD + origin protection ---


class TestIndicatorCRUD:
    async def test_create_indicator_invalid_competence(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        data = IndicatorCreate(
            title="Bad", weight=1, sort_index=0, skill_level_id=sl.id
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_indicator(db, tenant.id, uuid.uuid4(), data)
        assert exc.value.status_code == 404

    async def test_update_indicator_success(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="IG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="IC", group_id=group.id)
        )
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(
                title="Old Ind", weight=1, sort_index=0, skill_level_id=sl.id
            ),
        )

        updated = await service.update_indicator(
            db, tenant.id, ind.id, IndicatorUpdate(title="New Ind")
        )
        assert updated.title == "New Ind"

    async def test_update_indicator_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.update_indicator(
                db, tenant.id, uuid.uuid4(), IndicatorUpdate(title="X")
            )
        assert exc.value.status_code == 404

    async def test_update_origin_indicator_forbidden(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="OIG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="OIC", group_id=group.id)
        )
        origin_ind = Indicator(
            title="Origin Ind",
            weight=1,
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=None,
        )
        db.add(origin_ind)
        await db.commit()
        await db.refresh(origin_ind)

        with pytest.raises(HTTPException) as exc:
            await service.update_indicator(
                db, tenant.id, origin_ind.id, IndicatorUpdate(title="Hacked")
            )
        assert exc.value.status_code == 403

    async def test_update_indicator_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherInd", slug=f"othi-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OtherIG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OtherIC", group_id=group.id)
        )
        ind = await service.create_indicator(
            db,
            other.id,
            comp.id,
            IndicatorCreate(
                title="Other Ind", weight=1, sort_index=0, skill_level_id=sl.id
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await service.update_indicator(
                db, tenant.id, ind.id, IndicatorUpdate(title="Stolen")
            )
        assert exc.value.status_code == 404

    async def test_delete_indicator_success(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="DIG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="DIC", group_id=group.id)
        )
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(
                title="Del Ind", weight=1, sort_index=0, skill_level_id=sl.id
            ),
        )
        await service.delete_indicator(db, tenant.id, ind.id)

    async def test_delete_indicator_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_indicator(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_delete_origin_indicator_forbidden(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="DOIG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="DOIC", group_id=group.id)
        )
        origin_ind = Indicator(
            title="Origin Del Ind",
            weight=1,
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=None,
        )
        db.add(origin_ind)
        await db.commit()
        await db.refresh(origin_ind)

        with pytest.raises(HTTPException) as exc:
            await service.delete_indicator(db, tenant.id, origin_ind.id)
        assert exc.value.status_code == 403

    async def test_delete_indicator_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherDI", slug=f"othdi-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OtherDIG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OtherDIC", group_id=group.id)
        )
        ind = await service.create_indicator(
            db,
            other.id,
            comp.id,
            IndicatorCreate(
                title="Other DI", weight=1, sort_index=0, skill_level_id=sl.id
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_indicator(db, tenant.id, ind.id)
        assert exc.value.status_code == 404


# --- Material CRUD + origin protection ---


class TestMaterialCRUD:
    async def test_create_material_success(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="MG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="MC", group_id=group.id)
        )

        data = MaterialCreate(
            title="Python Book",
            format="book",
            link="https://example.com",
            study_time=120,
            sort_index=0,
            skill_level_id=sl.id,
        )
        mat = await service.create_material(db, tenant.id, comp.id, data)
        assert mat.title == "Python Book"
        assert mat.competence_id == comp.id
        assert mat.tenant_id == tenant.id

    async def test_create_material_invalid_competence(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        data = MaterialCreate(title="Bad Mat", sort_index=0, skill_level_id=sl.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_material(db, tenant.id, uuid.uuid4(), data)
        assert exc.value.status_code == 404

    async def test_update_material_success(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="UMG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="UMC", group_id=group.id)
        )
        mat = await service.create_material(
            db,
            tenant.id,
            comp.id,
            MaterialCreate(title="Old Mat", sort_index=0, skill_level_id=sl.id),
        )

        updated = await service.update_material(
            db,
            tenant.id,
            mat.id,
            MaterialUpdate(title="New Mat", link="https://new.com"),
        )
        assert updated.title == "New Mat"
        assert updated.link == "https://new.com"

    async def test_update_material_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.update_material(
                db, tenant.id, uuid.uuid4(), MaterialUpdate(title="X")
            )
        assert exc.value.status_code == 404

    async def test_update_material_with_uuid_field_serializes(
        self, db: AsyncSession, tenant
    ):
        # Regression: payload built from MaterialUpdate.model_dump() contains
        # raw UUID for skill_level_id, which crashed JSON encoder on the
        # JSONB audit column with "Object of type UUID is not JSON serializable".
        sl1 = await _ensure_skill_level(db)
        sl2 = SkillLevel(title="Advanced", sort_index=2, tenant_id=None)
        db.add(sl2)
        await db.commit()
        await db.refresh(sl2)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="UUMG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="UUMC", group_id=group.id)
        )
        mat = await service.create_material(
            db,
            tenant.id,
            comp.id,
            MaterialCreate(title="Mat", sort_index=0, skill_level_id=sl1.id),
        )

        updated = await service.update_material(
            db,
            tenant.id,
            mat.id,
            MaterialUpdate(skill_level_id=sl2.id),
        )
        assert updated.skill_level_id == sl2.id

        from app.modules.competence.models import CompetenceTreeAuditLog
        from sqlalchemy import select as _select

        rows = (
            await db.execute(
                _select(CompetenceTreeAuditLog).where(
                    CompetenceTreeAuditLog.action == "material.update",
                    CompetenceTreeAuditLog.element_id == mat.id,
                )
            )
        ).scalars().all()
        assert rows, "audit row was not written"
        assert rows[-1].payload["skill_level_id"] == str(sl2.id)

    async def test_update_origin_material_forbidden(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="OMG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="OMC", group_id=group.id)
        )
        origin_mat = Material(
            title="Origin Mat",
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=None,
        )
        db.add(origin_mat)
        await db.commit()
        await db.refresh(origin_mat)

        with pytest.raises(HTTPException) as exc:
            await service.update_material(
                db, tenant.id, origin_mat.id, MaterialUpdate(title="Hacked")
            )
        assert exc.value.status_code == 403

    async def test_update_material_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherMat", slug=f"othm-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OtherMG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OtherMC", group_id=group.id)
        )
        mat = await service.create_material(
            db,
            other.id,
            comp.id,
            MaterialCreate(title="Other Mat", sort_index=0, skill_level_id=sl.id),
        )

        with pytest.raises(HTTPException) as exc:
            await service.update_material(
                db, tenant.id, mat.id, MaterialUpdate(title="Stolen")
            )
        assert exc.value.status_code == 404

    async def test_delete_material_success(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="DMG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="DMC", group_id=group.id)
        )
        mat = await service.create_material(
            db,
            tenant.id,
            comp.id,
            MaterialCreate(title="Del Mat", sort_index=0, skill_level_id=sl.id),
        )
        await service.delete_material(db, tenant.id, mat.id)

    async def test_delete_material_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_material(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_delete_origin_material_forbidden(self, db: AsyncSession, tenant):
        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="DOMG")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="DOMC", group_id=group.id)
        )
        origin_mat = Material(
            title="Origin Del Mat",
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=None,
        )
        db.add(origin_mat)
        await db.commit()
        await db.refresh(origin_mat)

        with pytest.raises(HTTPException) as exc:
            await service.delete_material(db, tenant.id, origin_mat.id)
        assert exc.value.status_code == 403

    async def test_delete_material_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherDM", slug=f"othdm-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        sl = await _ensure_skill_level(db)
        group = await service.create_group(
            db, other.id, CompetenceGroupCreate(title="OtherDMG")
        )
        comp = await service.create_competence(
            db, other.id, CompetenceCreate(title="OtherDMC", group_id=group.id)
        )
        mat = await service.create_material(
            db,
            other.id,
            comp.id,
            MaterialCreate(title="Other DM", sort_index=0, skill_level_id=sl.id),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_material(db, tenant.id, mat.id)
        assert exc.value.status_code == 404
