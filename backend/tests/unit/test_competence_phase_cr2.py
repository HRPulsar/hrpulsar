"""Phase CR2 — usage checks, cascades, move, publish, audit log."""

import uuid

import pytest
from app.modules.competence import service
from app.modules.competence.cascade import (
    CompetenceCycleError,
    cascade_activate_group,
    cascade_activate_parents,
    validate_no_cycles,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    CompetenceTreeAuditLog,
    SkillLevel,
)
from app.modules.competence.schemas import (
    CompetenceCreate,
    CompetenceGroupCreate,
    IndicatorCreate,
)
from app.modules.competence.usage import (
    check_competence_usage,
    check_group_usage,
    check_published_descendants,
    check_skill_level_usage,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helpers ---


async def _seed_basic_skill_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(title="Basic", sort_index=0, i18n_key="basic", tenant_id=None)
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


async def _seed_skill_level(
    db: AsyncSession, *, title: str, tenant_id: uuid.UUID | None = None
) -> SkillLevel:
    level = SkillLevel(title=title, sort_index=0, tenant_id=tenant_id)
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


async def _make_grade_link(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    skill_level_id: uuid.UUID,
) -> None:
    """Create the minimum graph (grade dict items + grade_specialization)
    needed to drop a real GradeCompetenceLink in the test DB."""
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    grade = DictionaryItem(
        type="grade", title="Junior", tenant_id=tenant_id, sort_index=0
    )
    spec = DictionaryItem(
        type="specialization", title="Backend", tenant_id=tenant_id, sort_index=0
    )
    db.add_all([grade, spec])
    await db.commit()
    await db.refresh(grade)
    await db.refresh(spec)

    gs = GradeSpecialization(
        tenant_id=tenant_id, grade_id=grade.id, specialization_id=spec.id
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)

    link = GradeCompetenceLink(
        grade_specialization_id=gs.id,
        competence_id=competence_id,
        skill_level_id=skill_level_id,
    )
    db.add(link)
    await db.commit()


# --- Usage checks ---


class TestCompetenceUsage:
    async def test_unused_competence(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        usage = await check_competence_usage(db, comp.id)
        assert usage.is_used is False

    async def test_competence_used_in_matrix(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        level = await _seed_basic_skill_level(db)
        await _make_grade_link(db, tenant.id, comp.id, level.id)

        usage = await check_competence_usage(db, comp.id)
        assert usage.matrix is True
        assert usage.is_used is True


class TestSkillLevelUsage:
    async def test_unused_level(self, db: AsyncSession) -> None:
        level = await _seed_basic_skill_level(db)
        assert await check_skill_level_usage(db, level.id) is False

    async def test_level_used_by_indicator(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        level = await _seed_basic_skill_level(db)
        await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="Ind", skill_level_id=level.id),
        )
        assert await check_skill_level_usage(db, level.id) is True


class TestGroupUsage:
    async def test_subtree_aggregation(self, db: AsyncSession, tenant) -> None:
        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root")
        )
        sub = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Sub", parent_id=root.id)
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=sub.id)
        )
        usage = await check_group_usage(db, root.id)
        assert usage.is_used is False

        level = await _seed_basic_skill_level(db)
        await _make_grade_link(db, tenant.id, comp.id, level.id)
        usage_after = await check_group_usage(db, root.id)
        assert usage_after.matrix is True


# --- Cascades ---


class TestCascadeActivate:
    async def test_activates_inactive_parents(self, db: AsyncSession, tenant) -> None:
        root = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="Root", is_active=False),
        )
        sub = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="Sub", parent_id=root.id, is_active=False),
        )
        await cascade_activate_parents(db, sub, tenant.id)
        await db.commit()
        await db.refresh(root)
        await db.refresh(sub)
        assert root.is_active is True
        assert sub.is_active is True

    async def test_does_not_touch_siblings(self, db: AsyncSession, tenant) -> None:
        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root")
        )
        a = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="A", parent_id=root.id, is_active=False),
        )
        b = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="B", parent_id=root.id, is_active=False),
        )
        await cascade_activate_parents(db, a, tenant.id)
        await db.commit()
        await db.refresh(b)
        assert b.is_active is False

    async def test_cascade_activate_group_lights_descendants(
        self, db: AsyncSession, tenant
    ) -> None:
        # HRP-118: activating a group cascades up *and* down so the whole
        # visible branch wakes up in one click. Sibling branches stay as-is.
        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root", is_active=False)
        )
        target = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="Target", parent_id=root.id, is_active=False),
        )
        deep_child = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(
                title="DeepChild", parent_id=target.id, is_active=False
            ),
        )
        unrelated = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(
                title="Unrelated", parent_id=root.id, is_active=False
            ),
        )
        await cascade_activate_group(db, target, tenant.id)
        await db.commit()
        for g in (root, target, deep_child):
            await db.refresh(g)
            assert g.is_active is True
        await db.refresh(unrelated)
        assert unrelated.is_active is False

    async def test_cascade_ignores_foreign_tenant_descendant(
        self, db: AsyncSession, tenant
    ) -> None:
        # HRP-140: defence-in-depth. A stray cross-tenant child must not be
        # silently activated by a cascade walker, even if move_group invariants
        # ever slip and the tree picks up a foreign edge.
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root", is_active=False)
        )
        same_tenant_child = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(
                title="SameChild", parent_id=root.id, is_active=False
            ),
        )
        # Foreign-tenant node injected by hand — bypassing service.create_group
        # because the public API rejects cross-tenant parents.
        foreign = CompetenceGroup(
            title="ForeignChild",
            parent_id=root.id,
            tenant_id=other.id,
            is_active=False,
        )
        db.add(foreign)
        await db.commit()
        await db.refresh(foreign)

        await cascade_activate_group(db, root, tenant.id)
        await db.commit()
        await db.refresh(root)
        await db.refresh(same_tenant_child)
        await db.refresh(foreign)
        assert root.is_active is True
        assert same_tenant_child.is_active is True
        assert foreign.is_active is False

    async def test_activate_parents_stops_at_foreign_tenant_ancestor(
        self, db: AsyncSession, tenant
    ) -> None:
        # HRP-140: upward walk must not flip an ancestor owned by another
        # tenant. We splice a foreign parent into the chain directly.
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        foreign_root = CompetenceGroup(
            title="ForeignRoot", tenant_id=other.id, is_active=False
        )
        db.add(foreign_root)
        await db.commit()
        await db.refresh(foreign_root)

        leaf = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(
                title="Leaf", parent_id=foreign_root.id, is_active=False
            ),
        )
        await cascade_activate_parents(db, leaf, tenant.id)
        await db.commit()
        await db.refresh(leaf)
        await db.refresh(foreign_root)
        assert leaf.is_active is True
        assert foreign_root.is_active is False


class TestCascadeDeactivate:
    async def test_blocked_when_published_descendant(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        await service.publish_competence(db, tenant.id, comp.id)

        with pytest.raises(HTTPException) as exc:
            await service.deactivate_group(db, tenant.id, group.id)
        assert exc.value.status_code == 409

    async def test_blocked_when_used_in_matrix(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        level = await _seed_basic_skill_level(db)
        await _make_grade_link(db, tenant.id, comp.id, level.id)

        with pytest.raises(HTTPException) as exc:
            await service.deactivate_group(db, tenant.id, group.id)
        assert exc.value.status_code == 409

    async def test_succeeds_for_empty_group(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        await service.deactivate_group(db, tenant.id, group.id)
        await db.refresh(group)
        assert group.is_active is False


class TestCycleValidation:
    async def test_self_parent_blocked(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        with pytest.raises(CompetenceCycleError):
            await validate_no_cycles(db, group.id, group.id)

    async def test_descendant_as_parent_blocked(self, db: AsyncSession, tenant) -> None:
        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root")
        )
        sub = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Sub", parent_id=root.id)
        )
        with pytest.raises(CompetenceCycleError):
            await validate_no_cycles(db, root.id, sub.id)

    async def test_unrelated_parent_allowed(self, db: AsyncSession, tenant) -> None:
        a = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="A"))
        b = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="B"))
        await validate_no_cycles(db, a.id, b.id)


# --- Move ---


class TestMove:
    async def test_move_group_to_new_parent(self, db: AsyncSession, tenant) -> None:
        a = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="A"))
        b = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="B"))
        await service.move_group(db, tenant.id, a.id, b.id, 0)
        await db.refresh(a)
        assert a.parent_id == b.id

    async def test_move_origin_group_blocked(self, db: AsyncSession, tenant) -> None:
        origin = CompetenceGroup(title="Origin", tenant_id=None, parent_id=None)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)
        with pytest.raises(HTTPException) as exc:
            await service.move_group(db, tenant.id, origin.id, None, 0)
        assert exc.value.status_code == 403

    async def test_move_competence_to_new_group(self, db: AsyncSession, tenant) -> None:
        g1 = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G1")
        )
        g2 = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G2")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=g1.id)
        )
        await service.move_competence(db, tenant.id, comp.id, g2.id, 0)
        await db.refresh(comp)
        assert comp.group_id == g2.id

    async def test_move_indicator_to_new_skill_level(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        l1 = await _seed_skill_level(db, title="L1")
        l2 = await _seed_skill_level(db, title="L2")
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="I", skill_level_id=l1.id),
        )
        await service.move_indicator(db, tenant.id, ind.id, l2.id, 0)
        await db.refresh(ind)
        assert ind.skill_level_id == l2.id


# --- Publish workflow ---


class TestPublish:
    async def test_publish_activates_parent_chain(
        self, db: AsyncSession, tenant
    ) -> None:
        root = await service.create_group(
            db,
            tenant.id,
            CompetenceGroupCreate(title="Root", is_active=False),
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=root.id)
        )
        # competence is created active by default in this codebase
        comp.is_active = False
        await db.commit()

        await service.publish_competence(db, tenant.id, comp.id)
        await db.refresh(root)
        await db.refresh(comp)
        assert comp.is_published is True
        assert comp.is_active is True
        assert root.is_active is True

    async def test_unpublish_blocked_when_used(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        await service.publish_competence(db, tenant.id, comp.id)
        level = await _seed_basic_skill_level(db)
        await _make_grade_link(db, tenant.id, comp.id, level.id)

        with pytest.raises(HTTPException) as exc:
            await service.unpublish_competence(db, tenant.id, comp.id)
        assert exc.value.status_code == 409

    async def test_publish_origin_competence_blocked(
        self, db: AsyncSession, tenant
    ) -> None:
        origin_group = CompetenceGroup(title="Origin", tenant_id=None)
        db.add(origin_group)
        await db.commit()
        await db.refresh(origin_group)
        origin_comp = Competence(
            title="OriginC", group_id=origin_group.id, tenant_id=None
        )
        db.add(origin_comp)
        await db.commit()
        await db.refresh(origin_comp)

        with pytest.raises(HTTPException) as exc:
            await service.publish_competence(db, tenant.id, origin_comp.id)
        assert exc.value.status_code == 403


# --- Origin protection ---


class TestOriginProtection:
    async def test_cannot_deactivate_locked_origin_group(
        self, db: AsyncSession, tenant
    ) -> None:
        origin = CompetenceGroup(title="Origin", tenant_id=None, can_deactivate=False)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)
        with pytest.raises(HTTPException) as exc:
            await service.deactivate_group(db, tenant.id, origin.id)
        assert exc.value.status_code == 403

    async def test_can_deactivate_unlocked_origin_group(
        self, db: AsyncSession, tenant
    ) -> None:
        origin = CompetenceGroup(title="Origin", tenant_id=None, can_deactivate=True)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)
        await service.deactivate_group(db, tenant.id, origin.id)
        await db.refresh(origin)
        assert origin.is_active is False


class TestPlatformLockPropagation:
    async def test_lock_propagates_up(self, db: AsyncSession) -> None:
        a = CompetenceGroup(title="A", tenant_id=None, can_deactivate=True)
        db.add(a)
        await db.commit()
        await db.refresh(a)
        b = CompetenceGroup(
            title="B", tenant_id=None, parent_id=a.id, can_deactivate=True
        )
        db.add(b)
        await db.commit()
        await db.refresh(b)

        affected = await service.set_group_can_deactivate(db, b.id, False)
        await db.refresh(a)
        assert a.can_deactivate is False
        assert {g.id for g in affected} == {a.id, b.id}

    async def test_unlock_propagates_down(self, db: AsyncSession) -> None:
        a = CompetenceGroup(title="A", tenant_id=None, can_deactivate=False)
        db.add(a)
        await db.commit()
        await db.refresh(a)
        b = CompetenceGroup(
            title="B", tenant_id=None, parent_id=a.id, can_deactivate=False
        )
        db.add(b)
        await db.commit()
        await db.refresh(b)

        affected = await service.set_group_can_deactivate(db, a.id, True)
        await db.refresh(b)
        assert b.can_deactivate is True
        assert {g.id for g in affected} == {a.id, b.id}


# --- Audit log writes ---


class TestAuditLogWrites:
    async def test_create_group_writes_audit(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Audited")
        )
        result = await db.execute(
            select(CompetenceTreeAuditLog).where(
                CompetenceTreeAuditLog.element_id == group.id
            )
        )
        rows = list(result.scalars().all())
        assert any(r.action == "competence_group.create" for r in rows)

    async def test_publish_competence_writes_audit(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        await service.publish_competence(db, tenant.id, comp.id)
        result = await db.execute(
            select(CompetenceTreeAuditLog).where(
                CompetenceTreeAuditLog.element_id == comp.id,
                CompetenceTreeAuditLog.action == "competence.publish",
            )
        )
        assert result.scalar_one_or_none() is not None


# --- Tree enrichment ---


class TestTreeEnrichment:
    async def test_competences_count_rolls_up(self, db: AsyncSession, tenant) -> None:
        root = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Root")
        )
        sub = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Sub", parent_id=root.id)
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="A", group_id=root.id)
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="B", group_id=sub.id)
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=sub.id)
        )

        tree = await service.get_competence_tree(db, tenant.id)
        root_node = next(n for n in tree if n.title == "Root")
        assert root_node.competences_count == 3

    async def test_competence_node_carries_is_origin(
        self, db: AsyncSession, tenant
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="Client", group_id=group.id)
        )
        tree = await service.get_competence_tree(db, tenant.id)
        node = next(n for n in tree if n.title == "G")
        client_comp = next(c for c in node.competences if c.title == "Client")
        assert client_comp.is_origin is False

    async def test_alphabetic_sort(self, db: AsyncSession, tenant) -> None:
        for title in ("Charlie", "alpha", "Bravo"):
            await service.create_group(
                db, tenant.id, CompetenceGroupCreate(title=title)
            )
        tree = await service.get_competence_tree(db, tenant.id)
        titles = [n.title for n in tree]
        # Postgres lower() sort is case-insensitive — so "alpha" comes first
        # regardless of the original casing.
        assert titles.index("alpha") < titles.index("Bravo")
        assert titles.index("Bravo") < titles.index("Charlie")


class TestPublishedDescendants:
    async def test_no_published(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        assert await check_published_descendants(db, group.id) is False

    async def test_with_published(self, db: AsyncSession, tenant) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=group.id)
        )
        await service.publish_competence(db, tenant.id, comp.id)
        assert await check_published_descendants(db, group.id) is True
