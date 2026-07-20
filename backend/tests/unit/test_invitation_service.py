"""Tests for GF3: User Invitations."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.auth import service
from app.modules.auth.models import Invitation
from app.modules.auth.schemas import AcceptInvitationRequest, InvitationCreate
from app.modules.company.models import Division
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


class TestCreateInvitation:
    async def test_create_invitation(self, db: AsyncSession, user, tenant, admin_role):
        data = InvitationCreate(
            email="newguy@test.com", name="New Guy", role_code="admin"
        )
        result = await service.create_invitation(db, tenant.id, user.id, data)
        assert result["email"] == "newguy@test.com"
        assert result["name"] == "New Guy"
        assert result["role_code"] == "admin"
        assert result["status"] == "pending"
        assert result["invited_by"] == user.id

    async def test_create_with_division_and_position(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        data = InvitationCreate(
            email="dev@test.com",
            name="Dev Person",
            role_code="admin",
            position_id=position.id,
        )
        result = await service.create_invitation(db, tenant.id, user.id, data)
        assert result["position_title"] == position.title

    async def test_create_persists_name_in_db(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        data = InvitationCreate(
            email=f"persist-{uuid.uuid4().hex[:6]}@test.com",
            name="Persisted Name",
            role_code="admin",
        )
        result = await service.create_invitation(db, tenant.id, user.id, data)
        db_inv = await db.get(Invitation, result["id"])
        assert db_inv is not None
        assert db_inv.name == "Persisted Name"

    async def test_create_without_name_rejected(self):
        with pytest.raises(ValidationError):
            InvitationCreate(email="noname@test.com", role_code="admin")

    async def test_create_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            InvitationCreate(email="blank@test.com", name="", role_code="admin")

    async def test_bulk_create_inherits_required_name(self):
        from app.modules.auth.schemas import InvitationBulkCreate

        # Each bulk item is an InvitationCreate, so name is required per row.
        with pytest.raises(ValidationError):
            InvitationBulkCreate(
                invitations=[
                    {"email": "a@test.com", "role_code": "admin"},
                ]
            )

    async def test_duplicate_pending_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        email = f"dup-{uuid.uuid4().hex[:6]}@test.com"
        data = InvitationCreate(email=email, name="Dup", role_code="admin")
        await service.create_invitation(db, tenant.id, user.id, data)

        with pytest.raises(HTTPException) as exc:
            await service.create_invitation(db, tenant.id, user.id, data)
        assert exc.value.status_code == 409

    async def test_existing_user_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        # user.email is already a user in this tenant
        data = InvitationCreate(email=user.email, name="Existing", role_code="admin")
        with pytest.raises(HTTPException) as exc:
            await service.create_invitation(db, tenant.id, user.id, data)
        assert exc.value.status_code == 409

    async def test_invalid_role_rejected(self, db: AsyncSession, user, tenant):
        data = InvitationCreate(
            email="nobody@test.com", name="Nobody", role_code="nonexistent_role"
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_invitation(db, tenant.id, user.id, data)
        assert exc.value.status_code == 400


class TestListInvitations:
    async def test_list(self, db: AsyncSession, user, tenant, admin_role):
        for i in range(3):
            await service.create_invitation(
                db,
                tenant.id,
                user.id,
                InvitationCreate(
                    email=f"list-{i}-{uuid.uuid4().hex[:4]}@test.com",
                    name=f"Member {i}",
                    role_code="admin",
                ),
            )
        items, total = await service.list_invitations(db, tenant.id)
        assert total >= 3
        assert all("name" in item and "division_name" in item for item in items)

    async def test_list_resolves_division_name(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        division = Division(name="Engineering", tenant_id=tenant.id)
        db.add(division)
        await db.commit()
        await db.refresh(division)

        with_div = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"with-div-{uuid.uuid4().hex[:4]}@test.com",
                name="With Division",
                role_code="admin",
                division_id=division.id,
            ),
        )
        without_div = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"no-div-{uuid.uuid4().hex[:4]}@test.com",
                name="Without Division",
                role_code="admin",
            ),
        )

        items, _ = await service.list_invitations(db, tenant.id)
        by_id = {item["id"]: item for item in items}
        assert by_id[with_div["id"]]["division_name"] == "Engineering"
        assert by_id[with_div["id"]]["name"] == "With Division"
        assert by_id[without_div["id"]]["division_name"] is None

    async def test_list_filter_by_status(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"filter-{uuid.uuid4().hex[:6]}@test.com",
                name="Filter",
                role_code="admin",
            ),
        )
        await service.cancel_invitation(db, tenant.id, inv["id"])

        items, total = await service.list_invitations(
            db, tenant.id, status_filter="cancelled"
        )
        assert total >= 1
        assert all(i["status"] == "cancelled" for i in items)


class TestCancelInvitation:
    async def test_cancel(self, db: AsyncSession, user, tenant, admin_role):
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"cancel-{uuid.uuid4().hex[:6]}@test.com",
                name="Cancel Me",
                role_code="admin",
            ),
        )
        result = await service.cancel_invitation(db, tenant.id, inv["id"])
        assert result["status"] == "cancelled"

    async def test_cancel_not_pending_fails(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"cancel2-{uuid.uuid4().hex[:6]}@test.com",
                name="Cancel Twice",
                role_code="admin",
            ),
        )
        await service.cancel_invitation(db, tenant.id, inv["id"])

        with pytest.raises(HTTPException) as exc:
            await service.cancel_invitation(db, tenant.id, inv["id"])
        assert exc.value.status_code == 400

    async def test_cancel_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.cancel_invitation(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404


class TestResendInvitation:
    async def test_resend_extends_expiry(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"resend-{uuid.uuid4().hex[:6]}@test.com",
                name="Resend Target",
                role_code="admin",
            ),
        )
        original_expiry = inv["expires_at"]
        result = await service.resend_invitation(db, tenant.id, inv["id"])
        assert result["expires_at"] >= original_expiry


class TestAcceptInvitation:
    async def _create_pending(self, db, user, tenant, position):
        email = f"accept-{uuid.uuid4().hex[:6]}@test.com"
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=email,
                name="Accept Candidate",
                role_code="admin",
                position_id=position.id,
            ),
        )
        # Get the token from DB
        db_inv = await db.get(Invitation, inv["id"])
        return db_inv

    async def test_accept(self, db: AsyncSession, user, tenant, admin_role, position):
        inv = await self._create_pending(db, user, tenant, position)
        data = AcceptInvitationRequest(
            token=inv.token,
            password="securepass123",
            first_name="New",
            last_name="User",
        )
        result = await service.accept_invitation(db, data)
        assert result["user"]["email"] == inv.email
        assert result["user"]["first_name"] == "New"
        assert "access_token" in result
        assert "refresh_token" in result

    async def test_accept_creates_employee(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        inv = await self._create_pending(db, user, tenant, position)
        data = AcceptInvitationRequest(
            token=inv.token,
            password="securepass123",
            first_name="Emp",
            last_name="Person",
        )
        result = await service.accept_invitation(db, data)

        # Verify employee was created
        from app.modules.employee.models import Employee
        from sqlalchemy import select

        emp_result = await db.execute(
            select(Employee).where(Employee.user_id == result["user"]["id"])
        )
        emp = emp_result.scalar_one_or_none()
        assert emp is not None
        assert emp.position_title == "Software Engineer"

    async def test_accept_invalid_token(self, db: AsyncSession):
        data = AcceptInvitationRequest(
            token="nonexistent-token",
            password="securepass123",
            first_name="X",
            last_name="Y",
        )
        with pytest.raises(HTTPException) as exc:
            await service.accept_invitation(db, data)
        assert exc.value.status_code == 404

    async def test_accept_expired(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        inv = await self._create_pending(db, user, tenant, position)
        # Manually expire it
        inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

        data = AcceptInvitationRequest(
            token=inv.token,
            password="securepass123",
            first_name="X",
            last_name="Y",
        )
        with pytest.raises(HTTPException) as exc:
            await service.accept_invitation(db, data)
        assert exc.value.status_code == 400

    async def test_accept_cancelled(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        inv = await self._create_pending(db, user, tenant, position)
        await service.cancel_invitation(db, tenant.id, inv.id)

        data = AcceptInvitationRequest(
            token=inv.token,
            password="securepass123",
            first_name="X",
            last_name="Y",
        )
        with pytest.raises(HTTPException) as exc:
            await service.accept_invitation(db, data)
        assert exc.value.status_code == 400


class TestHrp195AcceptAsDivisionManager:
    """HRP-195: invitee accepts with role=manager + division_id pre-set →
    the new user becomes the actual Manager of that division, replacing
    whoever sat there before (with the same auto-downgrade path used by
    the division-edit flow)."""

    async def _ensure_role(self, db, code: str, name: str):
        from app.modules.auth.models import Role
        from sqlalchemy import select

        result = await db.execute(
            select(Role).where(Role.code == code, Role.is_system == True)  # noqa: E712
        )
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name=name, code=code, is_system=True)
            db.add(role)
            await db.commit()
            await db.refresh(role)
        return role

    async def test_manager_invite_assigns_user_as_division_manager(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        manager_role = await self._ensure_role(db, "manager", "Manager")
        await self._ensure_role(db, "employee", "Employee")

        # Pre-create the target division (no current manager).
        from app.modules.company import service as company_service
        from app.modules.company.schemas import DivisionCreate

        division = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Engineering")
        )

        # Issue the manager invitation with the division pre-selected.
        inv_dict = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"mgr-{uuid.uuid4().hex[:6]}@test.com",
                name="Manager Candidate",
                role_code="manager",
                division_id=division["id"],
                position_id=position.id,
            ),
        )
        inv = await db.get(Invitation, inv_dict["id"])

        # Accept.
        result = await service.accept_invitation(
            db,
            AcceptInvitationRequest(
                token=inv.token,
                password="securepass123",
                first_name="Mgr",
                last_name="Person",
            ),
        )

        # Division now points at the new user's Employee row.
        from app.modules.company.models import Division as DivisionModel
        from app.modules.employee.models import Employee
        from sqlalchemy import select

        emp_row = await db.execute(
            select(Employee).where(Employee.user_id == result["user"]["id"])
        )
        new_emp = emp_row.scalar_one()
        await db.refresh(new_emp)

        div_row = await db.execute(
            select(DivisionModel).where(DivisionModel.id == division["id"])
        )
        updated_div = div_row.scalar_one()
        assert updated_div.manager_id == new_emp.id

        # Role assignment happened during accept_invitation.
        assert "manager" in result["user"]["roles"]
        assert manager_role.code in result["user"]["roles"]

    async def test_manager_invite_downgrades_previous_manager(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        manager_role = await self._ensure_role(db, "manager", "Manager")
        employee_role = await self._ensure_role(db, "employee", "Employee")

        # Build the "previous manager": an Employee user already running
        # this division and no other one — exactly the spec §5 trigger
        # for auto-downgrade.
        from datetime import date, datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles
        from app.modules.employee.models import Employee

        prev_user = User(
            email=f"prev-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("x"),
            first_name="Prev",
            last_name="Manager",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(prev_user)
        await db.commit()
        await db.refresh(prev_user)
        await db.execute(
            user_roles.insert().values(
                user_id=prev_user.id, role_id=employee_role.id
            )
        )
        prev_emp = Employee(
            user_id=prev_user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(prev_emp)
        await db.commit()
        await db.refresh(prev_emp)

        from app.modules.company import service as company_service
        from app.modules.company.schemas import DivisionCreate

        division = await company_service.create_division(
            db,
            tenant.id,
            DivisionCreate(name="Operations", manager_id=prev_emp.id),
        )
        # Sanity: create_division upgraded the previous user to manager.
        from app.modules.auth.models import Role
        from sqlalchemy import select

        codes_pre = {
            c
            for (c,) in (
                await db.execute(
                    select(Role.code)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == prev_user.id)
                )
            ).all()
        }
        assert "manager" in codes_pre

        inv_dict = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"newmgr-{uuid.uuid4().hex[:6]}@test.com",
                name="New Manager",
                role_code="manager",
                division_id=division["id"],
                position_id=position.id,
            ),
        )
        inv = await db.get(Invitation, inv_dict["id"])
        result = await service.accept_invitation(
            db,
            AcceptInvitationRequest(
                token=inv.token,
                password="securepass123",
                first_name="New",
                last_name="Manager",
            ),
        )

        # Previous user no longer manages any division → auto-downgraded.
        codes_post = {
            c
            for (c,) in (
                await db.execute(
                    select(Role.code)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == prev_user.id)
                )
            ).all()
        }
        assert "manager" not in codes_post
        assert "employee" in codes_post
        # The new user is now the division's manager.
        from app.modules.company.models import Division as DivisionModel

        new_emp_row = await db.execute(
            select(Employee).where(Employee.user_id == result["user"]["id"])
        )
        new_emp = new_emp_row.scalar_one()
        div_row = await db.execute(
            select(DivisionModel).where(DivisionModel.id == division["id"])
        )
        updated_div = div_row.scalar_one()
        assert updated_div.manager_id == new_emp.id
        assert manager_role.code in result["user"]["roles"]

    async def test_non_manager_invite_does_not_touch_division_manager(
        self, db: AsyncSession, user, tenant, admin_role, position
    ):
        await self._ensure_role(db, "employee", "Employee")

        from app.modules.company import service as company_service
        from app.modules.company.schemas import DivisionCreate

        division = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="QA")
        )
        inv_dict = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"emp-{uuid.uuid4().hex[:6]}@test.com",
                name="Plain Employee",
                role_code="employee",
                division_id=division["id"],
                position_id=position.id,
            ),
        )
        inv = await db.get(Invitation, inv_dict["id"])
        await service.accept_invitation(
            db,
            AcceptInvitationRequest(
                token=inv.token,
                password="securepass123",
                first_name="Plain",
                last_name="Employee",
            ),
        )

        # Manager slot remains empty — role=employee does not promote.
        from app.modules.company.models import Division as DivisionModel
        from sqlalchemy import select

        div_row = await db.execute(
            select(DivisionModel).where(DivisionModel.id == division["id"])
        )
        updated_div = div_row.scalar_one()
        assert updated_div.manager_id is None
