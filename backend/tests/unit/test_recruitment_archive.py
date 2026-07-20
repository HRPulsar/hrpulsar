"""HRP-177: vacancy archive / restore / delete + ETag tests."""

import uuid

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.models import AssessmentInvite
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    InviteCreate,
    VacancyCreate,
    VacancyUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


def _vacancy_data() -> VacancyCreate:
    return VacancyCreate(title=f"V {uuid.uuid4().hex[:6]}")


class TestArchiveRestore:
    async def test_archive_hides_from_default_list(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.archive_vacancy(db, tenant.id, user.id, v["id"])

        active, _ = await service.list_vacancies(db, tenant.id)
        assert all(item["id"] != v["id"] for item in active)

        archived, total = await service.list_vacancies(
            db, tenant.id, archived_only=True
        )
        assert total >= 1
        assert any(item["id"] == v["id"] for item in archived)
        assert all(item["archived_at"] is not None for item in archived)

    async def test_archive_idempotency_blocked(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.archive_vacancy(db, tenant.id, user.id, v["id"])
        with pytest.raises(HTTPException) as exc_info:
            await service.archive_vacancy(db, tenant.id, user.id, v["id"])
        assert exc_info.value.status_code == 409

    async def test_archive_deactivates_pending_invites(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(first_name="A", last_name="B", email="ab@example.com"),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=v["id"]),
        )
        invite = await service.create_assessment_invite(
            db, tenant.id, cv["id"], InviteCreate(email="x@example.com")
        )

        await service.archive_vacancy(db, tenant.id, user.id, v["id"])
        await db.refresh(await db.get(AssessmentInvite, invite["id"]))
        from sqlalchemy import select

        row = (
            await db.execute(
                select(AssessmentInvite).where(
                    AssessmentInvite.id == invite["id"]
                )
            )
        ).scalar_one()
        assert row.status == "inactive"

    async def test_restore_brings_back_into_list(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.archive_vacancy(db, tenant.id, user.id, v["id"])
        restored = await service.restore_vacancy(db, tenant.id, v["id"])
        assert restored["archived_at"] is None

        active, _ = await service.list_vacancies(db, tenant.id)
        assert any(item["id"] == v["id"] for item in active)

    async def test_restore_rejects_active(self, db: AsyncSession, tenant, user):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        with pytest.raises(HTTPException) as exc_info:
            await service.restore_vacancy(db, tenant.id, v["id"])
        assert exc_info.value.status_code == 409


class TestDeletePermanent:
    async def test_delete_clean_draft(self, db: AsyncSession, tenant, user):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.delete_vacancy(db, tenant.id, v["id"])
        with pytest.raises(HTTPException) as exc_info:
            await service.get_vacancy(db, tenant.id, v["id"])
        assert exc_info.value.status_code == 404

    async def test_delete_blocks_when_status_not_draft(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.update_vacancy(
            db, tenant.id, v["id"], VacancyUpdate(status="open")
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_vacancy(db, tenant.id, v["id"])
        assert exc_info.value.status_code == 409

    async def test_delete_blocks_with_candidates(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(first_name="C", last_name="D", email="cd@example.com"),
        )
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=v["id"]),
        )
        # refresh ORM relationship cache
        from app.modules.recruitment.models import Vacancy
        from sqlalchemy import select
        await db.execute(
            select(Vacancy).where(Vacancy.id == v["id"])
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_vacancy(db, tenant.id, v["id"])
        assert exc_info.value.status_code == 409


class TestEtagFlow:
    async def test_update_with_matching_etag_succeeds(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        etag = service.vacancy_etag(v)
        updated = await service.update_vacancy(
            db,
            tenant.id,
            v["id"],
            VacancyUpdate(title="Renamed"),
            if_match=etag,
        )
        assert updated["title"] == "Renamed"
        assert updated["version"] == v["version"] + 1

    async def test_update_with_stale_etag_412(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        with pytest.raises(HTTPException) as exc_info:
            await service.update_vacancy(
                db,
                tenant.id,
                v["id"],
                VacancyUpdate(title="Renamed"),
                if_match='W/"999"',
            )
        assert exc_info.value.status_code == 412

    async def test_update_archived_rejected(
        self, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.archive_vacancy(db, tenant.id, user.id, v["id"])
        with pytest.raises(HTTPException) as exc_info:
            await service.update_vacancy(
                db, tenant.id, v["id"], VacancyUpdate(title="x")
            )
        assert exc_info.value.status_code == 409


class TestArchiveEndpoints:
    async def test_get_returns_etag_header(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        res = await auth_client.get(f"/api/recruitment/vacancies/{v['id']}")
        assert res.status_code == 200
        assert res.headers["ETag"] == service.vacancy_etag(v)

    async def test_patch_requires_if_match(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        res = await auth_client.patch(
            f"/api/recruitment/vacancies/{v['id']}", json={"title": "x"}
        )
        assert res.status_code == 428

    async def test_patch_with_stale_if_match_412(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        res = await auth_client.patch(
            f"/api/recruitment/vacancies/{v['id']}",
            json={"title": "x"},
            headers={"If-Match": 'W/"999"'},
        )
        assert res.status_code == 412

    async def test_archive_then_restore_endpoint(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        res = await auth_client.post(
            f"/api/recruitment/vacancies/{v['id']}/archive"
        )
        assert res.status_code == 200
        assert res.json()["archived_at"] is not None

        res = await auth_client.post(
            f"/api/recruitment/vacancies/{v['id']}/restore"
        )
        assert res.status_code == 200
        assert res.json()["archived_at"] is None

    async def test_delete_endpoint(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        res = await auth_client.delete(
            f"/api/recruitment/vacancies/{v['id']}"
        )
        assert res.status_code == 204

        # Subsequent GET returns 404
        res = await auth_client.get(f"/api/recruitment/vacancies/{v['id']}")
        assert res.status_code == 404
