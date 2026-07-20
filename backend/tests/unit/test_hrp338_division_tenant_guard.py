"""HRP-338: vacancy division_id must belong to the acting tenant.

position_id has been validated since HRP-180; division_id accepted any
UUID — a foreign tenant's division id was silently persisted.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import vacancy_service as service
from app.modules.recruitment.schemas import VacancyCreate, VacancyUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


def _vacancy_data(**overrides) -> VacancyCreate:
    defaults = {"title": f"V {uuid.uuid4().hex[:6]}"}
    defaults.update(overrides)
    return VacancyCreate(**defaults)


async def _division(db: AsyncSession, tenant_id: uuid.UUID):
    from app.modules.company.models import Division

    d = Division(tenant_id=tenant_id, name=f"Div {uuid.uuid4().hex[:6]}")
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def _other_tenant(db: AsyncSession):
    from app.modules.company.models import Tenant

    t = Tenant(
        name=f"Other Corp {uuid.uuid4().hex[:6]}",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


class TestCreateVacancyDivisionGuard:
    async def test_own_division_accepted(self, db: AsyncSession, tenant, user):
        div = await _division(db, tenant.id)
        v = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data(division_id=div.id)
        )
        assert v["division_id"] == div.id

    async def test_foreign_division_rejected(self, db: AsyncSession, tenant, user):
        other = await _other_tenant(db)
        foreign_div = await _division(db, other.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db, tenant.id, user.id, _vacancy_data(division_id=foreign_div.id)
            )
        assert exc.value.status_code == 422
        assert "division_id" in exc.value.detail

    async def test_unknown_division_rejected(self, db: AsyncSession, tenant, user):
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db, tenant.id, user.id, _vacancy_data(division_id=uuid.uuid4())
            )
        assert exc.value.status_code == 422


class TestUpdateVacancyDivisionGuard:
    async def test_update_to_foreign_division_rejected(
        self, db: AsyncSession, tenant, user
    ):
        other = await _other_tenant(db)
        foreign_div = await _division(db, other.id)
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        with pytest.raises(HTTPException) as exc:
            await service.update_vacancy(
                db,
                tenant.id,
                v["id"],
                VacancyUpdate(division_id=foreign_div.id),
            )
        assert exc.value.status_code == 422

    async def test_update_to_own_division_accepted(
        self, db: AsyncSession, tenant, user
    ):
        div = await _division(db, tenant.id)
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        updated = await service.update_vacancy(
            db, tenant.id, v["id"], VacancyUpdate(division_id=div.id)
        )
        assert updated["division_id"] == div.id
