"""HRP-95: Change-candidates picker flow.

The Change dialog opens with the existing candidates pre-checked. On Save
the UI ships two requests per diff entry:

* added employees → ``POST /talent-market/{id}/candidates/bulk``
* removed employees → ``DELETE /talent-market/{id}/candidates/{employee_id}``

The DELETE endpoint is what's tested here; the bulk-add path is covered
in test_hrp95_candidate_pool.py.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate
from app.modules.talent_market.schemas import (
    CandidateAdd,
    CandidateBulkAdd,
    TalentCardCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_employee(db: AsyncSession, tenant_id: uuid.UUID) -> Employee:
    u = User(
        tenant_id=tenant_id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="C",
        last_name="X",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        tenant_id=tenant_id,
        user_id=u.id,
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestDeleteCandidate:
    async def test_delete_by_employee_id(self, db: AsyncSession, tenant, user):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        emp_a = await _make_employee(db, tenant.id)
        emp_b = await _make_employee(db, tenant.id)
        await service.add_candidates_bulk(
            db,
            tenant.id,
            card["id"],
            CandidateBulkAdd(employee_ids=[emp_a.id, emp_b.id]),
        )

        await service.delete_candidate(db, tenant.id, card["id"], emp_a.id)

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.employee_id for r in rows} == {emp_b.id}

    async def test_delete_missing_employee_404(
        self, db: AsyncSession, tenant, user
    ):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        with pytest.raises(HTTPException) as exc:
            await service.delete_candidate(
                db, tenant.id, card["id"], uuid.uuid4()
            )
        assert exc.value.status_code == 404

    async def test_delete_wrong_tenant_404(self, db: AsyncSession, tenant, user):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        emp = await _make_employee(db, tenant.id)
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_candidate(
                db, uuid.uuid4(), card["id"], emp.id
            )
        assert exc.value.status_code == 404

    async def test_change_diff_full_round_trip(
        self, db: AsyncSession, tenant, user
    ):
        """End-to-end Change-flow: start with [A, B], save with [B, C] →
        A deleted, C added, B untouched."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        emp_a = await _make_employee(db, tenant.id)
        emp_b = await _make_employee(db, tenant.id)
        emp_c = await _make_employee(db, tenant.id)
        await service.add_candidates_bulk(
            db,
            tenant.id,
            card["id"],
            CandidateBulkAdd(employee_ids=[emp_a.id, emp_b.id]),
        )

        # Diff: remove A, add C.
        await service.delete_candidate(db, tenant.id, card["id"], emp_a.id)
        await service.add_candidates_bulk(
            db,
            tenant.id,
            card["id"],
            CandidateBulkAdd(employee_ids=[emp_c.id]),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.employee_id for r in rows} == {emp_b.id, emp_c.id}
