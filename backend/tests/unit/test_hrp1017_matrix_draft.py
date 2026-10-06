"""HRP-1017: a division head's personal competence draft goes into no grade
matrix - both matrix saves answer 422 with their own error code."""

import uuid

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary import service as dict_service
from app.modules.dictionary.schemas import DictionaryItemCreate
from app.modules.grade_system import service as grade_service
from app.modules.grade_system.schemas import GradeSpecializationCreate
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession, tenant, user):
    spec = await dict_service.create_item(
        db, tenant.id, "specialization", DictionaryItemCreate(title="Backend")
    )
    grade = await dict_service.create_item(
        db, tenant.id, "grade", DictionaryItemCreate(title="Junior")
    )
    await grade_service.create_chain(
        db,
        tenant.id,
        GradeSpecializationCreate(grade_id=grade["id"], specialization_id=spec["id"]),
    )
    group = CompetenceGroup(title=f"G {uuid.uuid4().hex[:6]}", tenant_id=tenant.id)
    db.add(group)
    await db.flush()
    draft = Competence(
        title="Draft", group_id=group.id, tenant_id=tenant.id, draft_owner_id=user.id
    )
    published = Competence(title="Published", group_id=group.id, tenant_id=tenant.id)
    level = SkillLevel(title="L", sort_index=0, tenant_id=tenant.id)
    db.add_all([draft, published, level])
    await db.commit()
    return spec["id"], grade["id"], draft.id, published.id, level.id


async def test_matrix_saves_reject_a_competence_draft(
    db: AsyncSession, auth_client: AsyncClient, tenant, user
) -> None:
    spec_id, grade_id, draft_id, published_id, level_id = await _setup(db, tenant, user)

    def links(*ids):
        return [{"competence_id": str(i), "skill_level_id": str(level_id)} for i in ids]

    single = f"/api/specializations/{spec_id}/matrix?grade_id={grade_id}"
    bulk = f"/api/specializations/{spec_id}/matrix-bulk"

    resp = await auth_client.put(single, json={"links": links(published_id, draft_id)})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "spec_matrix_draft_competence"

    resp = await auth_client.put(
        bulk,
        json={"grades": [{"grade_id": str(grade_id), "links": links(draft_id)}]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "spec_matrix_draft_competence"

    # A published competence still saves on both paths.
    resp = await auth_client.put(single, json={"links": links(published_id)})
    assert resp.status_code == 200, resp.text
    resp = await auth_client.put(
        bulk,
        json={"grades": [{"grade_id": str(grade_id), "links": links(published_id)}]},
    )
    assert resp.status_code == 200, resp.text
