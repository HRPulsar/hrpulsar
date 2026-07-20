import uuid

import pytest
from app.modules.dictionary import service as dict_service
from app.modules.dictionary.schemas import DictionaryItemCreate
from app.modules.grade_system import service
from app.modules.grade_system.models import GradeSpecialization
from app.modules.grade_system.schemas import (
    GradeCompetenceLinkCreate,
    GradeSpecializationCreate,
    GradeSpecializationUpdate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# --------------- helpers ---------------


async def _make_grade(db, tenant_id, suffix=None):
    s = suffix or uuid.uuid4().hex[:6]
    return await dict_service.create_item(
        db,
        tenant_id,
        "grade",
        DictionaryItemCreate(title=f"Grade {s}"),
    )


async def _make_spec(db, tenant_id, suffix=None):
    s = suffix or uuid.uuid4().hex[:6]
    return await dict_service.create_item(
        db,
        tenant_id,
        "specialization",
        DictionaryItemCreate(title=f"Spec {s}"),
    )


async def _make_competence_and_level(db, tenant_id):
    from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel

    group = CompetenceGroup(title=f"Group {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()

    comp = Competence(
        title=f"Comp {uuid.uuid4().hex[:6]}",
        group_id=group.id,
        tenant_id=tenant_id,
    )
    db.add(comp)

    level = SkillLevel(title=f"Level {uuid.uuid4().hex[:6]}")
    db.add(level)

    await db.commit()
    await db.refresh(comp)
    await db.refresh(level)
    return comp, level


async def _create_chain(db, tenant_id, grade_id=None, spec_id=None, **kwargs):
    if grade_id is None:
        g = await _make_grade(db, tenant_id)
        grade_id = g["id"]
    if spec_id is None:
        s = await _make_spec(db, tenant_id)
        spec_id = s["id"]

    data = GradeSpecializationCreate(
        grade_id=grade_id,
        specialization_id=spec_id,
        description=kwargs.get("description"),
        sort_index=kwargs.get("sort_index", 0),
        competence_links=kwargs.get("competence_links", []),
    )
    return await service.create_chain(db, tenant_id, data)


# --------------- create_chain ---------------


class TestCreateChain:
    async def test_create(self, db: AsyncSession, tenant):
        grade = await _make_grade(db, tenant.id)
        spec = await _make_spec(db, tenant.id)

        result = await service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"],
                specialization_id=spec["id"],
                description="Junior Backend",
                sort_index=1,
            ),
        )

        assert result["grade_id"] == grade["id"]
        assert result["specialization_id"] == spec["id"]
        assert result["description"] == "Junior Backend"
        assert result["sort_index"] == 1
        assert result["tenant_id"] == tenant.id
        assert result["competence_links"] == []
        assert "id" in result
        assert "created_at" in result

    async def test_create_with_competence_links(self, db: AsyncSession, tenant):
        grade = await _make_grade(db, tenant.id)
        spec = await _make_spec(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)

        result = await service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"],
                specialization_id=spec["id"],
                competence_links=[
                    GradeCompetenceLinkCreate(
                        competence_id=comp.id, skill_level_id=level.id
                    ),
                ],
            ),
        )

        assert len(result["competence_links"]) == 1
        link = result["competence_links"][0]
        assert link["competence_id"] == comp.id
        assert link["skill_level_id"] == level.id

    async def test_duplicate_conflict(self, db: AsyncSession, tenant):
        grade = await _make_grade(db, tenant.id)
        spec = await _make_spec(db, tenant.id)

        await service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"], specialization_id=spec["id"]
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_chain(
                db,
                tenant.id,
                GradeSpecializationCreate(
                    grade_id=grade["id"], specialization_id=spec["id"]
                ),
            )
        assert exc_info.value.status_code == 409

    async def test_default_values(self, db: AsyncSession, tenant):
        result = await _create_chain(db, tenant.id)
        assert result["description"] is None
        assert result["sort_index"] == 0


# --------------- list_by_specialization ---------------


class TestListBySpecialization:
    async def test_empty(self, db: AsyncSession, tenant):
        spec = await _make_spec(db, tenant.id)
        result = await service.list_by_specialization(db, tenant.id, spec["id"])
        assert result == []

    async def test_returns_chains(self, db: AsyncSession, tenant):
        spec = await _make_spec(db, tenant.id)
        grade1 = await _make_grade(db, tenant.id, "g1")
        grade2 = await _make_grade(db, tenant.id, "g2")

        await _create_chain(
            db, tenant.id, grade_id=grade1["id"], spec_id=spec["id"], sort_index=2
        )
        await _create_chain(
            db, tenant.id, grade_id=grade2["id"], spec_id=spec["id"], sort_index=1
        )

        chains = await service.list_by_specialization(db, tenant.id, spec["id"])
        assert len(chains) == 2
        # Ordered by sort_index
        assert chains[0]["sort_index"] <= chains[1]["sort_index"]

    async def test_tenant_isolation(self, db: AsyncSession, tenant):
        spec = await _make_spec(db, tenant.id)
        await _create_chain(db, tenant.id, spec_id=spec["id"])

        other_tenant_id = uuid.uuid4()
        result = await service.list_by_specialization(db, other_tenant_id, spec["id"])
        assert result == []

    async def test_filters_other_specs(self, db: AsyncSession, tenant):
        spec_a = await _make_spec(db, tenant.id, "a")
        spec_b = await _make_spec(db, tenant.id, "b")

        await _create_chain(db, tenant.id, spec_id=spec_a["id"])
        await _create_chain(db, tenant.id, spec_id=spec_b["id"])

        chains_a = await service.list_by_specialization(db, tenant.id, spec_a["id"])
        chains_b = await service.list_by_specialization(db, tenant.id, spec_b["id"])
        assert len(chains_a) == 1
        assert len(chains_b) == 1
        assert chains_a[0]["id"] != chains_b[0]["id"]


# --------------- update_chain ---------------


class TestUpdateChain:
    async def test_update(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id, description="Old", sort_index=0)

        updated = await service.update_chain(
            db,
            tenant.id,
            chain["id"],
            GradeSpecializationUpdate(description="New desc", sort_index=5),
        )
        assert updated["description"] == "New desc"
        assert updated["sort_index"] == 5
        assert updated["id"] == chain["id"]

    async def test_partial_update(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id, description="Keep me", sort_index=3)

        updated = await service.update_chain(
            db,
            tenant.id,
            chain["id"],
            GradeSpecializationUpdate(sort_index=10),
        )
        assert updated["sort_index"] == 10
        assert updated["description"] == "Keep me"

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.update_chain(
                db,
                tenant.id,
                uuid.uuid4(),
                GradeSpecializationUpdate(description="x"),
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_chain(
                db,
                uuid.uuid4(),
                chain["id"],
                GradeSpecializationUpdate(description="x"),
            )
        assert exc_info.value.status_code == 404


# --------------- delete_chain ---------------


class TestDeleteChain:
    async def test_delete(self, db: AsyncSession, tenant):
        spec = await _make_spec(db, tenant.id)
        chain = await _create_chain(db, tenant.id, spec_id=spec["id"])

        await service.delete_chain(db, tenant.id, chain["id"])

        chains = await service.list_by_specialization(db, tenant.id, spec["id"])
        assert all(c["id"] != chain["id"] for c in chains)

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_chain(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_chain(db, uuid.uuid4(), chain["id"])
        assert exc_info.value.status_code == 404


# --------------- add_competence_link ---------------


class TestAddCompetenceLink:
    async def test_add(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)

        link = await service.add_competence_link(
            db,
            tenant.id,
            chain["id"],
            GradeCompetenceLinkCreate(competence_id=comp.id, skill_level_id=level.id),
        )

        assert link["competence_id"] == comp.id
        assert link["skill_level_id"] == level.id
        assert "id" in link

    async def test_resolves_titles(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)

        link = await service.add_competence_link(
            db,
            tenant.id,
            chain["id"],
            GradeCompetenceLinkCreate(competence_id=comp.id, skill_level_id=level.id),
        )

        assert link["competence_title"] == comp.title
        assert link["skill_level_title"] == level.title

    async def test_chain_not_found(self, db: AsyncSession, tenant):
        comp, level = await _make_competence_and_level(db, tenant.id)
        with pytest.raises(HTTPException) as exc_info:
            await service.add_competence_link(
                db,
                tenant.id,
                uuid.uuid4(),
                GradeCompetenceLinkCreate(
                    competence_id=comp.id, skill_level_id=level.id
                ),
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)
        with pytest.raises(HTTPException) as exc_info:
            await service.add_competence_link(
                db,
                uuid.uuid4(),
                chain["id"],
                GradeCompetenceLinkCreate(
                    competence_id=comp.id, skill_level_id=level.id
                ),
            )
        assert exc_info.value.status_code == 404


# --------------- remove_competence_link ---------------


class TestRemoveCompetenceLink:
    async def test_remove(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)

        link = await service.add_competence_link(
            db,
            tenant.id,
            chain["id"],
            GradeCompetenceLinkCreate(competence_id=comp.id, skill_level_id=level.id),
        )

        await service.remove_competence_link(db, tenant.id, link["id"])

        result = await db.execute(
            select(GradeSpecialization)
            .options(selectinload(GradeSpecialization.competence_links))
            .where(GradeSpecialization.id == chain["id"])
        )
        gs = result.scalar_one()
        assert len(gs.competence_links) == 0

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.remove_competence_link(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        comp, level = await _make_competence_and_level(db, tenant.id)

        link = await service.add_competence_link(
            db,
            tenant.id,
            chain["id"],
            GradeCompetenceLinkCreate(competence_id=comp.id, skill_level_id=level.id),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_competence_link(db, uuid.uuid4(), link["id"])
        assert exc_info.value.status_code == 404


class TestSpecGradeAttributes:
    async def test_create_with_requirements_and_salary(self, db: AsyncSession, tenant):
        grade = await _make_grade(db, tenant.id)
        spec = await _make_spec(db, tenant.id)

        result = await service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"],
                specialization_id=spec["id"],
                description="Senior backend",
                requirements="5+ years Python; FastAPI; SQLAlchemy",
                salary_min=200_000,
                salary_max=350_000,
                salary_currency="RUB",
            ),
        )

        assert result["requirements"].startswith("5+ years")
        assert result["salary_min"] == 200_000
        assert result["salary_max"] == 350_000
        assert result["salary_currency"] == "RUB"

    async def test_salary_min_above_max_rejected(self, db: AsyncSession, tenant):
        grade = await _make_grade(db, tenant.id)
        spec = await _make_spec(db, tenant.id)

        with pytest.raises(HTTPException) as exc:
            await service.create_chain(
                db,
                tenant.id,
                GradeSpecializationCreate(
                    grade_id=grade["id"],
                    specialization_id=spec["id"],
                    salary_min=400_000,
                    salary_max=300_000,
                ),
            )
        assert exc.value.status_code == 400

    async def test_update_salary_range(self, db: AsyncSession, tenant):
        chain = await _create_chain(db, tenant.id)
        result = await service.update_chain(
            db,
            tenant.id,
            chain["id"],
            GradeSpecializationUpdate(
                salary_min=100_000,
                salary_max=180_000,
                salary_currency="USD",
                requirements="Strong fundamentals",
            ),
        )
        assert result["salary_min"] == 100_000
        assert result["salary_max"] == 180_000
        assert result["salary_currency"] == "USD"
        assert result["requirements"] == "Strong fundamentals"

    async def test_update_salary_min_above_existing_max_rejected(
        self, db: AsyncSession, tenant
    ):
        chain = await _create_chain(db, tenant.id)
        await service.update_chain(
            db,
            tenant.id,
            chain["id"],
            GradeSpecializationUpdate(salary_min=100_000, salary_max=200_000),
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_chain(
                db,
                tenant.id,
                chain["id"],
                GradeSpecializationUpdate(salary_min=300_000),
            )
        assert exc.value.status_code == 400
