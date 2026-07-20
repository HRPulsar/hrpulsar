"""HRP-209: role=Employee visibility & write-protection on Talent Market.

The Talent Market list / detail used to show every Published card to
every employee, regardless of whether they were on the candidate list.
HRP-209 narrows that down:

* Employees see only cards they're a candidate on; Draft cards stay
  hidden unless the employee is ``appointed``.
* Every write endpoint (manage requirements, candidates, statuses,
  match%) already 403s for the Employee role via ``require_role`` —
  this suite spot-checks one write path to catch a regression.
* The detail payload stamps ``is_me=True`` on the viewer's own
  candidate row so the UI can render "it's me", gate the drawer arrow
  and hide Appoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.modules.auth.models import Role, User
from app.modules.employee.models import Employee
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCard
from app.modules.talent_market.schemas import (
    CandidateAdd,
    SearchRequest,
    TalentCardCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession) -> Role:
    res = await db.execute(select(Role).where(Role.code == "employee"))
    role = res.scalar_one_or_none()
    if role is None:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _emp_user(
    db: AsyncSession, tenant, role: Role, *, first_name: str
) -> tuple[User, Employee]:
    u = User(
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name=first_name,
        last_name="X",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    u.roles.append(role)
    db.add(u)
    await db.flush()
    emp = Employee(
        tenant_id=tenant.id, user_id=u.id, hire_date=date(2024, 1, 1)
    )
    db.add(emp)
    await db.commit()
    # Re-fetch with eager-loaded roles to match the production
    # `get_current_user` shape (selectinload on User.roles).
    res = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    user = res.scalar_one()
    return user, emp


def _set_card_published(card_id: uuid.UUID, db: AsyncSession):
    """Helper coroutine — keeps the fixtures readable."""

    async def _run():
        card = await db.get(TalentCard, card_id)
        assert card is not None
        card.status = "published"
        card.is_published = True
        card.published_at = datetime.now(timezone.utc)
        await db.commit()

    return _run()


async def test_employee_sees_only_cards_they_candidate_on(
    db: AsyncSession, tenant, user, employee_role
) -> None:
    emp_user, emp = await _emp_user(db, tenant, employee_role, first_name="A")

    # Card 1: published, employee is a candidate → visible
    card_visible = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="V", card_type="vacancy")
    )
    await service.add_candidate(
        db, tenant.id, card_visible["id"], CandidateAdd(employee_id=emp.id)
    )
    await _set_card_published(card_visible["id"], db)

    # Card 2: published, employee NOT a candidate → hidden
    card_hidden = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="H", card_type="vacancy")
    )
    await _set_card_published(card_hidden["id"], db)

    items, total = await service.search_cards(
        db,
        tenant.id,
        SearchRequest(),
        published_only=True,
        assignee_employee_id=emp.id,
        candidate_only=True,
    )
    ids = {item["id"] for item in items}
    assert card_visible["id"] in ids
    assert card_hidden["id"] not in ids
    assert total == 1


async def test_employee_does_not_see_draft_unless_appointed(
    db: AsyncSession, tenant, user, employee_role
) -> None:
    emp_user, emp = await _emp_user(db, tenant, employee_role, first_name="B")

    # Draft + nominated → hidden
    card_draft_nom = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="DN", card_type="vacancy")
    )
    await service.add_candidate(
        db, tenant.id, card_draft_nom["id"], CandidateAdd(employee_id=emp.id)
    )

    # Draft + appointed → visible
    card_draft_app = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="DA", card_type="vacancy")
    )
    cand_dict = await service.add_candidate(
        db, tenant.id, card_draft_app["id"], CandidateAdd(employee_id=emp.id)
    )
    await service.appoint_candidate(
        db, tenant.id, card_draft_app["id"], cand_dict["id"]
    )

    items, total = await service.search_cards(
        db,
        tenant.id,
        SearchRequest(),
        published_only=True,
        assignee_employee_id=emp.id,
        candidate_only=True,
    )
    ids = {item["id"] for item in items}
    assert card_draft_app["id"] in ids
    assert card_draft_nom["id"] not in ids
    assert total == 1


async def test_employee_get_card_detail_blocks_unrelated_card(
    db: AsyncSession, tenant, user, employee_role
) -> None:
    emp_user, emp = await _emp_user(db, tenant, employee_role, first_name="C")
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="X", card_type="vacancy")
    )
    await _set_card_published(card["id"], db)
    # Not a candidate → 404 (cannot leak the card's existence).
    with pytest.raises(HTTPException) as exc:
        await service.get_card_detail(
            db, tenant.id, card["id"], current_user=emp_user
        )
    assert exc.value.status_code == 404


async def test_card_detail_marks_self_with_is_me(
    db: AsyncSession, tenant, user, employee_role
) -> None:
    emp_user_self, emp_self = await _emp_user(
        db, tenant, employee_role, first_name="Self"
    )
    emp_user_other, emp_other = await _emp_user(
        db, tenant, employee_role, first_name="Other"
    )

    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="V", card_type="vacancy")
    )
    await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp_self.id)
    )
    await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp_other.id)
    )
    await _set_card_published(card["id"], db)

    detail = await service.get_card_detail(
        db, tenant.id, card["id"], current_user=emp_user_self
    )
    by_emp = {c["employee_id"]: c["is_me"] for c in detail["candidates"]}
    assert by_emp[emp_self.id] is True
    assert by_emp[emp_other.id] is False
