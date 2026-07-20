"""Phase CR1 — model field defaults, hybrid property, audit log shape."""

import uuid

from app.modules.competence import service
from app.modules.competence.models import (
    CompetenceGroup,
    CompetenceTreeAuditLog,
    SkillLevel,
)
from app.modules.competence.schemas import (
    CompetenceCreate,
    CompetenceGroupCreate,
    MaterialCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_basic_skill_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(
        title="Basic",
        sort_index=0,
        i18n_key="basic",
        tenant_id=None,
    )
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


class TestCompetenceFieldDefaults:
    async def test_new_competence_is_not_published(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        assert comp.is_published is False

    async def test_new_client_group_can_be_deactivated(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Client Group")
        )
        # Client groups are always tenant-controlled — admin can hide them.
        # Origin groups stay locked unless platform admin unlocks via CR2.set_group_can_deactivate.
        assert group.can_deactivate is True


class TestRootOriginHybrid:
    async def test_origin_root_group_is_root_origin(self, db: AsyncSession) -> None:
        group = CompetenceGroup(
            title="Origin Root",
            tenant_id=None,
            parent_id=None,
            can_deactivate=False,
        )
        db.add(group)
        await db.commit()
        await db.refresh(group)
        assert group.is_root_origin is True

    async def test_client_group_is_not_root_origin(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Client")
        )
        assert group.is_root_origin is False

    async def test_origin_subgroup_is_not_root_origin(self, db: AsyncSession) -> None:
        root = CompetenceGroup(title="Origin", tenant_id=None, parent_id=None)
        db.add(root)
        await db.commit()
        await db.refresh(root)
        sub = CompetenceGroup(title="Sub", tenant_id=None, parent_id=root.id)
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        assert sub.is_root_origin is False


class TestSkillLevelTenant:
    async def test_origin_skill_level_has_null_tenant(self, db: AsyncSession) -> None:
        level = await _seed_basic_skill_level(db)
        assert level.tenant_id is None
        assert level.i18n_key == "basic"
        assert level.is_active is True

    async def test_create_custom_skill_level_for_tenant(
        self, db: AsyncSession, tenant
    ) -> None:
        level = SkillLevel(
            title="Master",
            sort_index=10,
            i18n_key="master",
            tenant_id=tenant.id,
        )
        db.add(level)
        await db.commit()
        await db.refresh(level)
        assert level.tenant_id == tenant.id
        assert level.is_active is True

    async def test_custom_skill_level_can_be_deactivated(
        self, db: AsyncSession, tenant
    ) -> None:
        level = SkillLevel(
            title="Expert",
            sort_index=11,
            i18n_key="expert",
            tenant_id=tenant.id,
            is_active=False,
        )
        db.add(level)
        await db.commit()
        await db.refresh(level)
        assert level.is_active is False


class TestMaterialNewFields:
    async def test_create_material_with_comment_and_type(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        level = await _seed_basic_skill_level(db)

        mat = await service.create_material(
            db,
            tenant.id,
            comp.id,
            MaterialCreate(
                title="Article",
                format="article",
                skill_level_id=level.id,
                comment="See chapter 3",
                material_type="theoretical",
            ),
        )
        assert mat.comment == "See chapter 3"
        assert mat.material_type == "theoretical"


class TestAuditLog:
    async def test_audit_log_row_persists(self, db: AsyncSession, tenant) -> None:
        log = CompetenceTreeAuditLog(
            tenant_id=tenant.id,
            actor_id=None,
            action="cr1.smoke",
            element_type="group",
            element_id=uuid.uuid4(),
            payload={"note": "phase CR1 smoke"},
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        assert log.id is not None
        assert log.payload == {"note": "phase CR1 smoke"}


class TestTreeIncludesNewFields:
    async def test_tree_node_exposes_can_deactivate_and_root_origin(
        self, db: AsyncSession, tenant
    ) -> None:
        await service.create_group(db, tenant.id, CompetenceGroupCreate(title="Branch"))
        tree = await service.get_competence_tree(db, tenant.id)
        assert tree
        node = tree[0]
        assert hasattr(node, "can_deactivate")
        assert hasattr(node, "is_root_origin")

    async def test_tree_competence_node_exposes_is_published(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Branch")
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        tree = await service.get_competence_tree(db, tenant.id)
        for node in tree:
            if node.title == "Branch":
                assert node.competences, "expected competence in tree"
                assert node.competences[0].is_published is False
                return
        raise AssertionError("group not found in tree")
