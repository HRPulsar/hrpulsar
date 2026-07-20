"""HRP-49: bulk-create indicators endpoint + tenant guards."""

from __future__ import annotations

import pytest_asyncio
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    SkillLevel,
)
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def tenant_competence(db: AsyncSession, tenant) -> Competence:
    group = CompetenceGroup(
        title="Engineering", tenant_id=tenant.id, sort_index=0, is_active=True
    )
    db.add(group)
    await db.flush()
    comp = Competence(
        title="Code review",
        tenant_id=tenant.id,
        group_id=group.id,
        is_active=True,
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)
    return comp


@pytest_asyncio.fixture
async def basic_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(
        title="Basic", sort_index=0, i18n_key="basic", tenant_id=None
    )
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


class TestBulkCreateIndicatorsEndpoint:
    async def test_creates_every_row(
        self,
        auth_client,
        db: AsyncSession,
        tenant_competence,
        basic_level,
    ) -> None:
        resp = await auth_client.post(
            f"/api/competences/{tenant_competence.id}/indicators/bulk",
            json={
                "indicators": [
                    {
                        "title": "Reads diff carefully",
                        "skill_level_id": str(basic_level.id),
                        "sort_index": 0,
                    },
                    {
                        "title": "Flags hot spots",
                        "skill_level_id": str(basic_level.id),
                        "sort_index": 1,
                    },
                ]
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert {row["title"] for row in body} == {
            "Reads diff carefully",
            "Flags hot spots",
        }
        assert all(row["competence_id"] == str(tenant_competence.id) for row in body)

    async def test_refuses_foreign_competence(
        self,
        auth_client,
        db: AsyncSession,
        basic_level,
    ) -> None:
        from app.modules.company.models import Tenant as TenantModel

        other = TenantModel(name="Other Tenant", slug="other-co-bulk")
        db.add(other)
        await db.flush()
        other_group = CompetenceGroup(
            title="Other Engineering",
            tenant_id=other.id,
            sort_index=0,
            is_active=True,
        )
        db.add(other_group)
        await db.flush()
        other_comp = Competence(
            title="Other competence",
            tenant_id=other.id,
            group_id=other_group.id,
            is_active=True,
        )
        db.add(other_comp)
        await db.commit()

        resp = await auth_client.post(
            f"/api/competences/{other_comp.id}/indicators/bulk",
            json={
                "indicators": [
                    {
                        "title": "X",
                        "skill_level_id": str(basic_level.id),
                        "sort_index": 0,
                    }
                ]
            },
        )
        assert resp.status_code == 404, resp.text

    async def test_refuses_foreign_skill_level(
        self,
        auth_client,
        db: AsyncSession,
        tenant_competence,
    ) -> None:
        from app.modules.company.models import Tenant as TenantModel

        other = TenantModel(name="Other Tenant 2", slug="other-co-bulk-2")
        db.add(other)
        await db.flush()
        foreign_level = SkillLevel(
            title="Custom",
            sort_index=0,
            i18n_key="custom-bulk",
            tenant_id=other.id,
        )
        db.add(foreign_level)
        await db.commit()

        resp = await auth_client.post(
            f"/api/competences/{tenant_competence.id}/indicators/bulk",
            json={
                "indicators": [
                    {
                        "title": "X",
                        "skill_level_id": str(foreign_level.id),
                        "sort_index": 0,
                    }
                ]
            },
        )
        assert resp.status_code == 404, resp.text
