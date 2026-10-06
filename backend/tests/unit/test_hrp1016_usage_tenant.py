"""HRP-1016: the four usage checks load the element through the card's tenant
loader - another tenant's id and an unknown id answer the card's 404, the
caller's own and an origin element answer 200."""

import uuid

from app.modules.company.models import Tenant
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
    SkillLevel,
)
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


async def _tree(
    db: AsyncSession, tenant_id: uuid.UUID | None, level_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    group = CompetenceGroup(title="G", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(title="C", group_id=group.id, tenant_id=tenant_id)
    db.add(comp)
    await db.flush()
    ind = Indicator(
        title="I", competence_id=comp.id, skill_level_id=level_id, tenant_id=tenant_id
    )
    mat = Material(
        title="M", competence_id=comp.id, skill_level_id=level_id, tenant_id=tenant_id
    )
    db.add_all([ind, mat])
    await db.commit()
    return {
        "competence-groups": group.id,
        "competences": comp.id,
        "indicators": ind.id,
        "materials": mat.id,
    }


_NOT_FOUND = {
    "competence-groups": "competence_group_not_found",
    "competences": "competence_not_found",
    "indicators": "indicator_not_found",
    "materials": "material_not_found",
}


async def test_usage_routes_answer_404_outside_the_tenant(
    db: AsyncSession, auth_client: AsyncClient, tenant
) -> None:
    other = Tenant(name=f"Other {uuid.uuid4().hex[:6]}", slug=f"o-{uuid.uuid4().hex}")
    db.add(other)
    level = SkillLevel(title="L", sort_index=0, tenant_id=tenant.id)
    db.add(level)
    await db.commit()

    own = await _tree(db, tenant.id, level.id)
    foreign = await _tree(db, other.id, level.id)
    origin = await _tree(db, None, level.id)
    try:
        for kind, code in _NOT_FOUND.items():
            for ok_id in (own[kind], origin[kind]):
                resp = await auth_client.get(f"/api/{kind}/{ok_id}/usage")
                assert resp.status_code == 200, (kind, resp.text)
                assert resp.json()["is_used"] is False
            for bad_id in (foreign[kind], uuid.uuid4()):
                resp = await auth_client.get(f"/api/{kind}/{bad_id}/usage")
                assert resp.status_code == 404, (kind, resp.text)
                assert resp.json()["code"] == code
    finally:
        await db.execute(delete(Material).where(Material.id == origin["materials"]))
        await db.execute(delete(Indicator).where(Indicator.id == origin["indicators"]))
        await db.execute(
            delete(Competence).where(Competence.id == origin["competences"])
        )
        await db.execute(
            delete(CompetenceGroup).where(
                CompetenceGroup.id == origin["competence-groups"]
            )
        )
        await db.commit()
