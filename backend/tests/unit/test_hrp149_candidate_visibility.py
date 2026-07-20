"""HRP-149: per-viewer profile-link gating on Talent Market candidates.

The card detail endpoint now stamps `can_view_profile` on each candidate
based on the caller's role + division scope:

* admin / hr / platform_admin → True for every candidate
* manager → True for own division subtree (managed roots + descendants)
* employee → True only for their own employee row
"""

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.talent_market import service
from app.modules.talent_market.schemas import CandidateAdd, TalentCardCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession):
    res = await db.execute(select(Role).where(Role.code == "manager"))
    role = res.scalar_one_or_none()
    if not role:
        role = Role(name="Manager", code="manager", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user(db: AsyncSession, tenant_id: uuid.UUID, role: Role) -> User:
    u = User(
        tenant_id=tenant_id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="U",
        last_name="X",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    # Refetch with roles eager-loaded — mirrors production get_current_user.
    res = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return res.scalar_one()


async def _make_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    user: User | None = None,
    division_id: uuid.UUID | None = None,
) -> Employee:
    if user is None:
        # Fresh user with the admin role just to satisfy NOT NULL — irrelevant
        # to the visibility computation (driven off the *viewer*, not the
        # candidate's user).
        from app.modules.auth.models import Role

        admin = (
            await db.execute(select(Role).where(Role.code == "admin"))
        ).scalar_one()
        user = await _make_user(db, tenant_id, admin)
    emp = Employee(
        tenant_id=tenant_id,
        user_id=user.id,
        division_id=division_id,
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestCanViewProfile:
    async def test_admin_sees_every_link(
        self, db: AsyncSession, tenant, user
    ):
        # `user` fixture comes pre-mounted with the admin role.
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        emp_a = await _make_employee(db, tenant.id)
        emp_b = await _make_employee(db, tenant.id)
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp_a.id)
        )
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp_b.id)
        )

        detail = await service.get_card_detail(
            db, tenant.id, card["id"], current_user=user
        )
        assert {c["can_view_profile"] for c in detail["candidates"]} == {True}

    async def test_manager_sees_own_division_subtree(
        self, db: AsyncSession, tenant, user, manager_role
    ):
        # Build a tiny division tree:  root → child.
        root = Division(tenant_id=tenant.id, name="Root")
        db.add(root)
        await db.flush()
        child = Division(tenant_id=tenant.id, name="Child", parent_id=root.id)
        outside = Division(tenant_id=tenant.id, name="Outside")
        db.add_all([child, outside])
        await db.commit()

        # Manager owns `root` (so `child` falls under their scope).
        mgr_user = await _make_user(db, tenant.id, manager_role)
        mgr_emp = await _make_employee(
            db, tenant.id, user=mgr_user, division_id=root.id
        )
        root.manager_id = mgr_emp.id
        await db.commit()

        # Candidate A in the subtree (child division), B outside.
        emp_in = await _make_employee(db, tenant.id, division_id=child.id)
        emp_out = await _make_employee(db, tenant.id, division_id=outside.id)
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp_in.id)
        )
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp_out.id)
        )

        detail = await service.get_card_detail(
            db, tenant.id, card["id"], current_user=mgr_user
        )
        by_emp = {c["employee_id"]: c["can_view_profile"] for c in detail["candidates"]}
        assert by_emp[emp_in.id] is True
        assert by_emp[emp_out.id] is False

    async def test_employee_sees_only_self(
        self, db: AsyncSession, tenant, user
    ):
        # Plain employee role (no admin / manager). Other tests in the
        # suite may have seeded this row already; get-or-create.
        res = await db.execute(select(Role).where(Role.code == "employee"))
        employee_role = res.scalar_one_or_none()
        if employee_role is None:
            employee_role = Role(name="Employee", code="employee", is_system=True)
            db.add(employee_role)
            await db.commit()
            await db.refresh(employee_role)

        emp_user = await _make_user(db, tenant.id, employee_role)
        self_emp = await _make_employee(db, tenant.id, user=emp_user)
        other_emp = await _make_employee(db, tenant.id)

        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="C", card_type="vacancy"),
        )
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=self_emp.id)
        )
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=other_emp.id)
        )
        # HRP-209: Employees can only open Draft cards when they're
        # appointed, so flip the card to Published for this test — what
        # we're really pinning is the can_view_profile gating (HRP-149),
        # not the Draft-visibility rules.
        from app.modules.talent_market.models import TalentCard as _TC

        db_card = await db.get(_TC, card["id"])
        assert db_card is not None
        db_card.status = "published"
        db_card.is_published = True
        await db.commit()

        detail = await service.get_card_detail(
            db, tenant.id, card["id"], current_user=emp_user
        )
        by_emp = {c["employee_id"]: c["can_view_profile"] for c in detail["candidates"]}
        assert by_emp[self_emp.id] is True
        assert by_emp[other_emp.id] is False
