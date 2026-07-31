"""Phase CR3 — REST endpoints for competence library rework.

Covers happy-path + 403/404/409 for the new endpoints (usage, publish/unpublish,
activate/deactivate, move, skill-level CRUD, audit log).
"""

import pytest
from app.modules.competence import service
from app.modules.competence.models import CompetenceGroup, SkillLevel
from app.modules.competence.schemas import (
    CompetenceCreate,
    CompetenceGroupCreate,
    IndicatorCreate,
    MaterialCreate,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helpers ---


@pytest.fixture
async def basic_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(title="Basic", sort_index=0, i18n_key="basic", tenant_id=None)
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


@pytest.fixture
async def client_group(db: AsyncSession, tenant) -> CompetenceGroup:
    return await service.create_group(
        db, tenant.id, CompetenceGroupCreate(title="Branch")
    )


# --- Group endpoints ---


class TestGroupEndpoints:
    async def test_get_usage_unused(
        self,
        auth_client: AsyncClient,
        client_group: CompetenceGroup,
    ) -> None:
        resp = await auth_client.get(f"/api/competence-groups/{client_group.id}/usage")
        assert resp.status_code == 200
        assert resp.json()["is_used"] is False

    async def test_activate(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
    ) -> None:
        group = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="X", is_active=False)
        )
        resp = await auth_client.patch(f"/api/competence-groups/{group.id}/activate")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    async def test_deactivate_succeeds(
        self,
        auth_client: AsyncClient,
        client_group: CompetenceGroup,
    ) -> None:
        resp = await auth_client.patch(
            f"/api/competence-groups/{client_group.id}/deactivate"
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_move_to_new_parent(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
    ) -> None:
        a = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="A"))
        b = await service.create_group(db, tenant.id, CompetenceGroupCreate(title="B"))
        resp = await auth_client.post(
            f"/api/competence-groups/{a.id}/move",
            json={"new_parent_id": str(b.id), "new_sort_index": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["parent_id"] == str(b.id)


# --- Competence endpoints ---


class TestCompetenceEndpoints:
    async def test_publish_and_unpublish(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
    ) -> None:
        comp = await service.create_competence(
            db,
            tenant.id,
            CompetenceCreate(title="C", group_id=client_group.id),
        )
        publish = await auth_client.post(f"/api/competences/{comp.id}/publish")
        assert publish.status_code == 200
        assert publish.json()["is_published"] is True

        unpublish = await auth_client.post(f"/api/competences/{comp.id}/unpublish")
        assert unpublish.status_code == 200
        assert unpublish.json()["is_published"] is False

    async def test_publish_origin_blocked(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
    ) -> None:
        og = CompetenceGroup(title="Origin", tenant_id=None)
        db.add(og)
        await db.commit()
        await db.refresh(og)
        from app.modules.competence.models import Competence

        oc = Competence(title="OC", group_id=og.id, tenant_id=None)
        db.add(oc)
        await db.commit()
        await db.refresh(oc)

        resp = await auth_client.post(f"/api/competences/{oc.id}/publish")
        assert resp.status_code == 403

    async def test_get_usage(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
    ) -> None:
        comp = await service.create_competence(
            db,
            tenant.id,
            CompetenceCreate(title="C", group_id=client_group.id),
        )
        resp = await auth_client.get(f"/api/competences/{comp.id}/usage")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_used"] is False
        assert "matrix" in body

    async def test_move_to_new_group(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
    ) -> None:
        g1 = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G1")
        )
        g2 = await service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="G2")
        )
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=g1.id)
        )
        resp = await auth_client.post(
            f"/api/competences/{comp.id}/move",
            json={"new_group_id": str(g2.id), "new_sort_index": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["group_id"] == str(g2.id)


# --- Indicator endpoints ---


class TestIndicatorEndpoints:
    async def test_activate_deactivate(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
        basic_level: SkillLevel,
    ) -> None:
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="I", skill_level_id=basic_level.id),
        )
        deact = await auth_client.patch(f"/api/indicators/{ind.id}/deactivate")
        assert deact.status_code == 200
        assert deact.json()["is_active"] is False

        act = await auth_client.patch(f"/api/indicators/{ind.id}/activate")
        assert act.status_code == 200
        assert act.json()["is_active"] is True

    async def test_move_indicator(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
        basic_level: SkillLevel,
    ) -> None:
        l2 = SkillLevel(title="Advanced", sort_index=2, tenant_id=None)
        db.add(l2)
        await db.commit()
        await db.refresh(l2)
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="I", skill_level_id=basic_level.id),
        )
        resp = await auth_client.post(
            f"/api/indicators/{ind.id}/move",
            json={"new_skill_level_id": str(l2.id), "new_sort_index": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["skill_level_id"] == str(l2.id)

    async def test_get_indicator_usage(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
        basic_level: SkillLevel,
    ) -> None:
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        ind = await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="I", skill_level_id=basic_level.id),
        )
        resp = await auth_client.get(f"/api/indicators/{ind.id}/usage")
        assert resp.status_code == 200
        assert resp.json()["is_used"] is False


# --- Material endpoints ---


class TestMaterialEndpoints:
    async def test_create_with_comment_and_type(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
        basic_level: SkillLevel,
    ) -> None:
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        resp = await auth_client.post(
            f"/api/competences/{comp.id}/materials",
            json={
                "title": "Article",
                "format": "article",
                "skill_level_id": str(basic_level.id),
                "comment": "Read first",
                "material_type": "theoretical",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["comment"] == "Read first"
        assert body["material_type"] == "theoretical"

    async def test_move_material(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
        basic_level: SkillLevel,
    ) -> None:
        l2 = SkillLevel(title="Advanced", sort_index=2, tenant_id=None)
        db.add(l2)
        await db.commit()
        await db.refresh(l2)
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        mat = await service.create_material(
            db,
            tenant.id,
            comp.id,
            MaterialCreate(title="M", skill_level_id=basic_level.id),
        )
        resp = await auth_client.post(
            f"/api/materials/{mat.id}/move",
            json={"new_skill_level_id": str(l2.id), "new_sort_index": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["skill_level_id"] == str(l2.id)


# --- SkillLevel CRUD ---


class TestSkillLevelEndpoints:
    async def test_create_custom_level(
        self,
        auth_client: AsyncClient,
    ) -> None:
        resp = await auth_client.post(
            "/api/skill-levels",
            json={"title": "Master", "sort_index": 10, "i18n_key": "master"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Master"
        assert body["tenant_id"] is not None
        # HRP-479: i18n_key is system-owned — a client-supplied value is
        # ignored, otherwise a tenant admin could stamp a catalog key
        # onto a custom level and have the translation shadow its title.
        assert body["i18n_key"] is None

    async def test_update_custom_level(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
    ) -> None:
        level = SkillLevel(title="Expert", sort_index=10, tenant_id=tenant.id)
        db.add(level)
        await db.commit()
        await db.refresh(level)
        resp = await auth_client.patch(
            f"/api/skill-levels/{level.id}",
            json={"title": "Distinguished"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Distinguished"

    async def test_delete_origin_level_blocked(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
    ) -> None:
        origin = SkillLevel(title="Basic", sort_index=0, tenant_id=None)
        db.add(origin)
        await db.commit()
        await db.refresh(origin)
        resp = await auth_client.delete(f"/api/skill-levels/{origin.id}")
        assert resp.status_code == 403

    async def test_delete_custom_level_in_use_blocked(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
    ) -> None:
        level = SkillLevel(title="Mid", sort_index=5, tenant_id=tenant.id)
        db.add(level)
        await db.commit()
        await db.refresh(level)
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        await service.create_indicator(
            db,
            tenant.id,
            comp.id,
            IndicatorCreate(title="I", skill_level_id=level.id),
        )
        resp = await auth_client.delete(f"/api/skill-levels/{level.id}")
        assert resp.status_code == 409


# --- Audit log ---


class TestAuditLog:
    async def test_audit_log_endpoint(
        self,
        db: AsyncSession,
        auth_client: AsyncClient,
        tenant,
        client_group: CompetenceGroup,
    ) -> None:
        comp = await service.create_competence(
            db, tenant.id, CompetenceCreate(title="C", group_id=client_group.id)
        )
        await auth_client.post(f"/api/competences/{comp.id}/publish")
        resp = await auth_client.get(f"/api/competences/{comp.id}/audit-log")
        assert resp.status_code == 200
        actions = [r["action"] for r in resp.json()]
        assert "competence.publish" in actions
