"""HRP-131/135/136 — vacancy pack-rec coverage.

Covers:
- HRP-131: library_refs storage + competence seeding from positions
  and specialization-grade pairs.
- HRP-135: requirements/responsibilities/conditions fields + attachment
  upload/list/delete with size + count guards.
- HRP-136: set_vacancy_competences as replace-set + PATCH endpoint.

The HRP-181 lite-candidate flow lived here too until Stage 5; the
canonical replacement has its own coverage in
``test_hrp181redo_stage2_endpoints.py``.
"""

import io
import uuid

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.schemas import (
    SpecializationGradePair,
    VacancyCompetenceSpec,
    VacancyCompetencesUpdate,
    VacancyCreate,
    VacancyLibraryRefs,
    VacancyUpdate,
)
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers


def _vacancy_data(**overrides) -> VacancyCreate:
    defaults = {"title": f"V {uuid.uuid4().hex[:6]}"}
    defaults.update(overrides)
    return VacancyCreate(**defaults)


# ---------------------------------------------------------------------------
# HRP-131 — library_refs
# ---------------------------------------------------------------------------


class TestVacancyLibraryRefs:
    async def test_library_refs_persisted(
        self, db: AsyncSession, tenant, user
    ):
        pos_id = uuid.uuid4()
        spec_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        div_id = uuid.uuid4()

        v = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                library_refs=VacancyLibraryRefs(
                    position_ids=[pos_id],
                    specialization_grade_pairs=[
                        SpecializationGradePair(
                            specialization_id=spec_id, grade_ids=[grade_id]
                        )
                    ],
                    division_ids=[div_id],
                )
            ),
        )

        from app.modules.recruitment.models import Vacancy

        row = await db.get(Vacancy, v["id"])
        assert row.library_refs is not None
        assert str(pos_id) in str(row.library_refs)
        assert str(div_id) in str(row.library_refs)

    async def test_library_refs_patch_serialises_uuids(
        self, db: AsyncSession, tenant, user
    ):
        """Prod incident 2026-06-01: PATCH /vacancies with library_refs
        crashed because ``model_dump`` left UUIDs in the JSONB payload
        and asyncpg's json.dumps cannot serialize them."""
        from app.modules.recruitment.models import Vacancy

        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        spec_id = uuid.uuid4()
        div_id = uuid.uuid4()
        await service.update_vacancy(
            db,
            tenant.id,
            vacancy["id"],
            VacancyUpdate(
                library_refs=VacancyLibraryRefs(
                    division_ids=[div_id],
                    specialization_grade_pairs=[
                        SpecializationGradePair(
                            specialization_id=spec_id, grade_ids=[]
                        )
                    ],
                )
            ),
            if_match=etag,
        )

        row = await db.get(Vacancy, vacancy["id"])
        assert row.library_refs is not None
        assert str(div_id) in str(row.library_refs)
        assert str(spec_id) in str(row.library_refs)

    async def test_library_refs_seed_competences_from_position(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            SkillLevel,
        )
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )
        from app.modules.position.models import Position

        spec = DictionaryItem(
            type="specialization", title="Backend", tenant_id=tenant.id
        )
        grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        group = CompetenceGroup(tenant_id=tenant.id, title="Eng")
        db.add(group)
        await db.commit()
        await db.refresh(group)

        comp = Competence(
            tenant_id=tenant.id,
            group_id=group.id,
            title="Python",
        )
        db.add(comp)
        skill = SkillLevel(tenant_id=tenant.id, title="Senior", sort_index=3)
        db.add(skill)
        await db.commit()
        await db.refresh(comp)
        await db.refresh(skill)

        gs = GradeSpecialization(
            tenant_id=tenant.id,
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(gs)
        await db.commit()
        await db.refresh(gs)

        link = GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=skill.id,
        )
        db.add(link)

        pos = Position(
            tenant_id=tenant.id,
            title="Senior Backend",
            specialization_id=spec.id,
            grade_id=grade.id,
            source="manual",
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        v = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                library_refs=VacancyLibraryRefs(position_ids=[pos.id]),
            ),
        )

        competences = await service.list_vacancy_competences(
            db, tenant.id, v["id"]
        )
        assert len(competences) == 1
        assert competences[0]["competence_id"] == comp.id
        assert competences[0]["source"] == "library"


# ---------------------------------------------------------------------------
# HRP-135 — manual params + attachments
# ---------------------------------------------------------------------------


class TestManualParamsAndAttachments:
    async def test_manual_text_fields_persisted(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                requirements="Python, FastAPI",
                responsibilities="Build APIs",
                conditions="Remote, flexible hours",
            ),
        )
        from app.modules.recruitment.models import Vacancy

        row = await db.get(Vacancy, v["id"])
        assert row.requirements == "Python, FastAPI"
        assert row.responsibilities == "Build APIs"
        assert row.conditions == "Remote, flexible hours"

    async def test_attachment_upload_and_list(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        f = UploadFile(
            file=io.BytesIO(b"hello world"),
            filename="brief.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        result = await service.upload_vacancy_attachment(
            db, tenant.id, user.id, v["id"], f
        )
        assert result["filename"] == "brief.txt"
        assert result["size_bytes"] == 11

        items = await service.list_vacancy_attachments(db, tenant.id, v["id"])
        assert len(items) == 1

    async def test_attachment_rejects_oversize(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        big = b"x" * (service.MAX_ATTACHMENT_BYTES + 1)
        f = UploadFile(
            file=io.BytesIO(big),
            filename="big.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_vacancy_attachment(
                db, tenant.id, user.id, v["id"], f
            )
        assert exc_info.value.status_code == 413

    async def test_attachment_rejects_bad_mime(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        # video/mp4 not in ALLOWED_ATTACHMENT_MIMES (vacancies are not media)
        f = UploadFile(
            file=io.BytesIO(b"\x00\x00\x00\x18ftypmp42"),
            filename="x.mp4",
            headers=Headers({"content-type": "video/mp4"}),
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_vacancy_attachment(
                db, tenant.id, user.id, v["id"], f
            )
        assert exc_info.value.status_code == 415

    async def test_attachment_delete(self, db: AsyncSession, tenant, user):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        f = UploadFile(
            file=io.BytesIO(b"hello"),
            filename="brief.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        att = await service.upload_vacancy_attachment(
            db, tenant.id, user.id, v["id"], f
        )
        await service.delete_vacancy_attachment(
            db, tenant.id, v["id"], att["id"]
        )
        items = await service.list_vacancy_attachments(db, tenant.id, v["id"])
        assert items == []


# ---------------------------------------------------------------------------
# HRP-136 — vacancy competences
# ---------------------------------------------------------------------------


class TestVacancyCompetences:
    async def test_set_competences_creates_and_deletes(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        comp_a = uuid.uuid4()
        comp_b = uuid.uuid4()
        sl = uuid.uuid4()

        rows = await service.set_vacancy_competences(
            db,
            tenant.id,
            v["id"],
            VacancyCompetencesUpdate(
                competences=[
                    VacancyCompetenceSpec(
                        competence_id=comp_a,
                        skill_level_ids=[sl],
                        source="manual",
                    ),
                    VacancyCompetenceSpec(
                        competence_id=comp_b,
                        skill_level_ids=[],
                        source="manual",
                    ),
                ]
            ),
        )
        assert len(rows) == 2

        # Replace-set semantics: drop comp_b, keep comp_a with new level
        sl2 = uuid.uuid4()
        rows = await service.set_vacancy_competences(
            db,
            tenant.id,
            v["id"],
            VacancyCompetencesUpdate(
                competences=[
                    VacancyCompetenceSpec(
                        competence_id=comp_a,
                        skill_level_ids=[sl, sl2],
                        source="ai",
                    )
                ]
            ),
        )
        assert len(rows) == 1
        assert rows[0]["competence_id"] == comp_a
        assert {uuid.UUID(s) for s in rows[0]["skill_level_ids"]} == {sl, sl2}
        assert rows[0]["source"] == "ai"

    async def test_patch_competences_endpoint(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        comp_id = uuid.uuid4()

        res = await auth_client.patch(
            f"/api/recruitment/vacancies/{v['id']}/competences",
            json={
                "competences": [
                    {
                        "competence_id": str(comp_id),
                        "skill_level_ids": [],
                        "source": "manual",
                    }
                ]
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body) == 1
        assert body[0]["competence_id"] == str(comp_id)


