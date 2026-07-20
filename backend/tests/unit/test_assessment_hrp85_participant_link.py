"""HRP-85: each participant in `get_assessment_detail` carries an
`employee_id` + `can_view_profile` so the UI can render the participant
name as a link to /employees/{id} when the viewer has the right to
open that profile, and as plain text otherwise.

Visibility rules (mirroring `get_visible_employee_ids`):
  - admin / hr → can_view_profile=True for every participant that maps
    to an Employee row.
  - regular employee → True only for their own Employee row.
  - external reviewer (no user_id) → employee_id=None, can_view_profile=False.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.schemas import AssessmentCreate, ParticipantAdd
from app.modules.auth.models import User, user_roles
from app.modules.employee.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_user_and_employee(
    db: AsyncSession, tenant, position, *, first: str, last: str
) -> tuple[User, Employee]:
    u = User(
        email=f"hrp85-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=first,
        last_name=last,
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    e = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=position.id,
        position_title=position.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return u, e


class TestParticipantEmployeeIdAndVisibility:
    async def test_admin_view_marks_every_internal_participant_as_viewable(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        admin_role,
        position,
        assessment_statuses,
        assessment_types,
    ):
        peer_user, peer_emp = await _make_user_and_employee(
            db, tenant, position, first="Peer", last="One"
        )
        await db.execute(
            user_roles.insert().values(user_id=peer_user.id, role_id=admin_role.id)
        )
        await db.commit()

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Admin view", employee_id=employee.id, type_code="360"),
        )
        await service.add_participant(
            db,
            tenant.id,
            created["id"],
            ParticipantAdd(employee_id=peer_emp.id, role="peer"),
        )

        # Admin path: visible_employee_ids=None means no restriction.
        detail = await service.get_assessment_detail(
            db, tenant.id, created["id"], visible_employee_ids=None
        )
        assert {p["user_id"] for p in detail["participants"]} == {user.id, peer_user.id}
        for p in detail["participants"]:
            assert p["employee_id"] is not None, p
            assert p["can_view_profile"] is True, p

    async def test_employee_view_only_marks_self_as_viewable(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        admin_role,
        position,
        assessment_statuses,
        assessment_types,
    ):
        """A regular employee sees only their own profile link, others are
        plain text. The `visible_employee_ids` set passed in mirrors what
        `get_visible_employee_ids` returns for any non-admin viewer — so
        this also covers the manager case (manager subtree is just a
        wider set on the same code path)."""
        peer_user, peer_emp = await _make_user_and_employee(
            db, tenant, position, first="Peer", last="Two"
        )
        await db.execute(
            user_roles.insert().values(user_id=peer_user.id, role_id=admin_role.id)
        )
        await db.commit()

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Self link", employee_id=employee.id, type_code="360"),
        )
        await service.add_participant(
            db,
            tenant.id,
            created["id"],
            ParticipantAdd(employee_id=peer_emp.id, role="peer"),
        )

        # Restricted viewer scope — only the assessee's own employee id.
        detail = await service.get_assessment_detail(
            db,
            tenant.id,
            created["id"],
            visible_employee_ids={employee.id},
            participant_user_id=user.id,
        )
        by_user = {p["user_id"]: p for p in detail["participants"]}
        # Assessee (the viewer) is linkable.
        assert by_user[user.id]["employee_id"] == employee.id
        assert by_user[user.id]["can_view_profile"] is True
        # The peer participant is mapped to its employee row but not viewable.
        assert by_user[peer_user.id]["employee_id"] == peer_emp.id
        assert by_user[peer_user.id]["can_view_profile"] is False

    async def test_external_reviewer_participant_is_not_linkable(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Ext", employee_id=employee.id, type_code="360"),
        )

        # `create_external_reviewer` adds the AssessmentParticipant row +
        # generates the access token in one shot — same code path as the
        # /participants endpoint.
        er = await service.create_external_reviewer(
            db,
            tenant.id,
            created["id"],
            name="Outside Vendor",
            email="vendor@example.com",
        )

        detail = await service.get_assessment_detail(
            db, tenant.id, created["id"], visible_employee_ids=None
        )
        ext = next(
            p for p in detail["participants"] if p["external_reviewer_id"] == er["id"]
        )
        assert ext["user_id"] is None
        assert ext["employee_id"] is None
        assert ext["can_view_profile"] is False
