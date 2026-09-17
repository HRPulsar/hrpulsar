"""HRP-753: AI workforce registry service — agents, usage assignments,
workflows and the audit trail (AR2), plus the effective capability set
``pack ∪ add − remove`` that Coverage (§5.1) reads for a registered agent."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.ai_workforce import service
from app.modules.ai_workforce.models import (
    AIAgent,
    AIAgentPack,
    AIUsageAssignment,
    AIWorkforceAuditLog,
)
from app.modules.ai_workforce.schemas import (
    AgentCreate,
    AgentUpdate,
    AssignmentApprove,
    AssignmentCreate,
    AssignmentRequest,
    AssignmentUpdate,
    PrimitiveOverride,
    WorkflowCreate,
    WorkflowStep,
    WorkflowUpdate,
)
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.competence.models import Competence, CompetenceGroup
from app.modules.employee.models import Employee
from app.modules.primitives import catalog_data
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession) -> dict[str, uuid.UUID]:
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await service.seed_packs(db)
    rows = await db.execute(
        select(AIAgentPack.code, AIAgentPack.id).where(AIAgentPack.tenant_id.is_(None))
    )
    return dict(rows.all())


async def _other_tenant(db: AsyncSession) -> Tenant:
    suffix = uuid.uuid4().hex[:8]
    t = Tenant(name=f"Other {suffix}", slug=f"other-{suffix}")
    db.add(t)
    await db.commit()
    return t


async def _employee(db: AsyncSession, tenant_id: uuid.UUID) -> Employee:
    u = User(
        email=f"e-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Some",
        last_name="Employee",
        tenant_id=tenant_id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.flush()
    emp = Employee(user_id=u.id, tenant_id=tenant_id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    return emp


async def _competence(db: AsyncSession, tenant_id: uuid.UUID) -> Competence:
    group = CompetenceGroup(title=f"G {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(title="Contract review", group_id=group.id, tenant_id=tenant_id)
    db.add(comp)
    await db.commit()
    return comp


async def _agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    name: str = "Cursor",
    pack_id: uuid.UUID | None = None,
    primitives: list[PrimitiveOverride] | None = None,
) -> dict:
    return await service.create_agent(
        db,
        tenant_id,
        AgentCreate(
            name=name, category="code", pack_id=pack_id, primitives=primitives or []
        ),
        user_id=user_id,
    )


async def _audit_actions(db: AsyncSession, tenant_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(AIWorkforceAuditLog.action)
        .where(AIWorkforceAuditLog.tenant_id == tenant_id)
        .order_by(AIWorkforceAuditLog.created_at, AIWorkforceAuditLog.id)
    )
    return list(rows.scalars().all())


class TestAgents:
    async def test_effective_set_is_pack_plus_add_minus_remove(self, db, tenant, user):
        packs = await _setup(db)
        agent = await _agent(
            db,
            tenant.id,
            user.id,
            pack_id=packs["compliance_check"],
            primitives=[
                PrimitiveOverride(code="P4", mode="add"),
                PrimitiveOverride(code="P2", mode="remove"),
            ],
        )
        assert agent["pack_code"] == "compliance_check"
        assert agent["effective_primitive_codes"] == ["P1", "P4"]
        assert {(o["code"], o["mode"]) for o in agent["primitive_overrides"]} == {
            ("P4", "add"),
            ("P2", "remove"),
        }
        assert agent["cost_currency"]
        assert await _audit_actions(db, tenant.id) == ["agent.created"]

    async def test_agent_without_pack_has_only_its_adds(self, db, tenant, user):
        await _setup(db)
        agent = await _agent(
            db,
            tenant.id,
            user.id,
            primitives=[PrimitiveOverride(code="P5", mode="add")],
        )
        assert agent["pack_id"] is None
        assert agent["effective_primitive_codes"] == ["P5"]

    async def test_set_primitives_replaces_and_validates(self, db, tenant, user):
        packs = await _setup(db)
        agent = await _agent(db, tenant.id, user.id, pack_id=packs["extraction"])

        updated = await service.set_agent_primitives(
            db,
            tenant.id,
            agent["id"],
            [PrimitiveOverride(code="P3", mode="add")],
            user_id=user.id,
        )
        assert updated["effective_primitive_codes"] == ["P1", "P3"]

        with pytest.raises(AppError) as err:
            await service.set_agent_primitives(
                db,
                tenant.id,
                agent["id"],
                [
                    PrimitiveOverride(code="P3", mode="add"),
                    PrimitiveOverride(code="P3", mode="remove"),
                ],
                user_id=user.id,
            )
        assert (err.value.code, err.value.status_code) == (
            "ai_agent_primitive_mode_conflict",
            400,
        )
        with pytest.raises(AppError) as err:
            await service.set_agent_primitives(
                db,
                tenant.id,
                agent["id"],
                [PrimitiveOverride(code="P99", mode="add")],
                user_id=user.id,
            )
        assert err.value.code == "primitive_not_found"
        # The failed calls left the previous delta in place.
        assert (await service.get_agent(db, tenant.id, agent["id"]))[
            "effective_primitive_codes"
        ] == ["P1", "P3"]
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "agent.primitives_set",
        ]

    async def test_name_is_unique_per_tenant(self, db, tenant, user):
        await _setup(db)
        await _agent(db, tenant.id, user.id, name="Claude")
        with pytest.raises(AppError) as err:
            await _agent(db, tenant.id, user.id, name="Claude")
        assert (err.value.code, err.value.status_code) == ("ai_agent_name_taken", 409)
        other = await _other_tenant(db)
        assert (await _agent(db, other.id, user.id, name="Claude"))["name"] == "Claude"

    async def test_tenant_isolation(self, db, tenant, user):
        packs = await _setup(db)
        other = await _other_tenant(db)
        theirs = await _agent(db, other.id, user.id, name="Theirs")
        mine = await _agent(db, tenant.id, user.id, name="Mine")

        items, total = await service.list_agents(db, tenant.id)
        assert [a["id"] for a in items] == [mine["id"]]
        assert total == 1
        for call in (
            service.get_agent(db, tenant.id, theirs["id"]),
            service.update_agent(
                db, tenant.id, theirs["id"], AgentUpdate(vendor="x"), user_id=user.id
            ),
            service.delete_agent(db, tenant.id, theirs["id"], user_id=user.id),
        ):
            with pytest.raises(AppError) as err:
                await call
            assert (err.value.code, err.value.status_code) == (
                "ai_agent_not_found",
                404,
            )

        # A custom pack of another tenant is not visible here.
        custom = AIAgentPack(
            code="custom", title_en="Custom", i18n_key="custom", tenant_id=other.id
        )
        db.add(custom)
        await db.commit()
        with pytest.raises(AppError) as err:
            await _agent(db, tenant.id, user.id, name="With pack", pack_id=custom.id)
        assert err.value.code == "ai_agent_pack_not_found"
        assert (
            await _agent(db, other.id, user.id, name="With pack", pack_id=custom.id)
        )["pack_code"] == "custom"
        assert packs["extraction"] != custom.id

    async def test_update_logs_a_diff(self, db, tenant, user):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        updated = await service.update_agent(
            db,
            tenant.id,
            agent["id"],
            AgentUpdate(vendor="Anysphere", monthly_cost=Decimal("40.00")),
            user_id=user.id,
        )
        assert updated["vendor"] == "Anysphere"
        assert updated["monthly_cost"] == Decimal("40.00")
        row = (
            await db.execute(
                select(AIWorkforceAuditLog).where(
                    AIWorkforceAuditLog.action == "agent.updated",
                    AIWorkforceAuditLog.target_id == agent["id"],
                )
            )
        ).scalar_one()
        assert row.target_type == "ai_agent"
        assert row.actor_id == user.id
        assert row.payload["before"] == {"vendor": None, "monthly_cost": None}
        assert row.payload["after"] == {"vendor": "Anysphere", "monthly_cost": "40.00"}

    async def test_delete_deactivates_and_revokes_assignments(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        owner = await _employee(db, tenant.id)
        active = await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="Code review",
                accountability_owner_id=owner.id,
            ),
            user_id=user.id,
        )
        pending = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="Drafts"),
            user_id=owner.user_id,
        )
        assert (active["status"], pending["status"]) == ("active", "pending")

        gone = await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)
        assert gone["is_active"] is False
        assert gone["deactivated_at"] is not None
        for a_id in (active["id"], pending["id"]):
            assert (await service.get_assignment(db, tenant.id, a_id))[
                "status"
            ] == "revoked"
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "assignment.created",
            "assignment.requested",
            "assignment.revoked",
            "assignment.revoked",
            "agent.deactivated",
        ]
        # Idempotent: a second delete changes nothing and logs nothing.
        await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)
        assert len(await _audit_actions(db, tenant.id)) == 6
        with pytest.raises(AppError) as err:
            await service.create_assignment(
                db,
                tenant.id,
                AssignmentCreate(
                    employee_id=employee.id,
                    agent_id=agent["id"],
                    allowed_use_cases="x",
                    accountability_owner_id=owner.id,
                ),
                user_id=user.id,
            )
        assert (err.value.code, err.value.status_code) == ("ai_agent_inactive", 409)
        listed, _ = await service.list_agents(db, tenant.id, is_active=True)
        assert listed == []

    async def test_delete_cascade_stays_inside_the_tenant(
        self, db, tenant, user, employee
    ):
        """The cascade revokes and audits under ``tenant_id``, so it must
        not reach a row that carries another one."""
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        other = await _other_tenant(db)
        stray = AIUsageAssignment(
            tenant_id=other.id,
            employee_id=employee.id,
            agent_id=agent["id"],
            allowed_use_cases="Belongs to another tenant",
            accountability_owner_id=employee.id,
            status="active",
        )
        db.add(stray)
        await db.commit()

        await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)

        await db.refresh(stray)
        assert stray.status == "active"
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "agent.deactivated",
        ]

    async def test_a_deactivated_agent_is_not_edited(self, db, tenant, user):
        """Deactivation is final — there is no route back — so contract and
        capability edits stop there instead of dressing up a dead tool."""
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)

        for call in (
            service.update_agent(
                db, tenant.id, agent["id"], AgentUpdate(vendor="x"), user_id=user.id
            ),
            service.set_agent_primitives(
                db,
                tenant.id,
                agent["id"],
                [PrimitiveOverride(code="P1", mode="add")],
                user_id=user.id,
            ),
        ):
            with pytest.raises(AppError) as err:
                await call
            assert (err.value.code, err.value.status_code) == ("ai_agent_inactive", 409)


class TestAssignments:
    async def test_create_active_with_competence_scope(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        comp = await _competence(db, tenant.id)
        created = await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="Summarise contracts",
                accountability_owner_id=employee.id,
                supervision_level="human_approval_gate",
                valid_until=date.today() + timedelta(days=90),
                competence_ids=[comp.id],
            ),
            user_id=user.id,
        )
        assert created["status"] == "active"
        assert created["approved_by_id"] == user.id
        assert created["approved_at"] is not None
        assert created["valid_from"] == date.today()
        assert created["competence_ids"] == [comp.id]
        assert created["agent_name"] == "Cursor"
        items, total = await service.list_assignments(
            db, tenant.id, employee_id=employee.id
        )
        assert total == 1 and items[0]["id"] == created["id"]
        assert (await service.list_assignments(db, tenant.id, status="pending"))[1] == 0

    async def test_period_and_foreign_rows_are_validated(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        other = await _other_tenant(db)
        stranger = await _employee(db, other.id)
        foreign_comp = await _competence(db, other.id)
        base = {
            "employee_id": employee.id,
            "agent_id": agent["id"],
            "allowed_use_cases": "x",
            "accountability_owner_id": employee.id,
        }
        cases = [
            (
                AssignmentCreate(
                    **base,
                    valid_from=date(2026, 9, 10),
                    valid_until=date(2026, 9, 9),
                ),
                "ai_assignment_invalid_period",
                400,
            ),
            (
                AssignmentCreate(**{**base, "employee_id": stranger.id}),
                "employee_not_found",
                404,
            ),
            (
                AssignmentCreate(**{**base, "accountability_owner_id": stranger.id}),
                "employee_not_found",
                404,
            ),
            (
                AssignmentCreate(**base, competence_ids=[foreign_comp.id]),
                "competence_not_found",
                404,
            ),
            (
                AssignmentCreate(**{**base, "agent_id": uuid.uuid4()}),
                "ai_agent_not_found",
                404,
            ),
        ]
        for data, code, status in cases:
            with pytest.raises(AppError) as err:
                await service.create_assignment(db, tenant.id, data, user_id=user.id)
            assert (err.value.code, err.value.status_code) == (code, status)
        assert await _audit_actions(db, tenant.id) == ["agent.created"]

    async def test_request_then_approve(self, db, tenant, user, employee):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        requested = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="Emails"),
            user_id=employee.user_id,
        )
        assert requested["status"] == "pending"
        assert requested["employee_id"] == employee.id
        assert requested["requested_at"] is not None
        assert requested["approved_at"] is None

        approved = await service.approve_assignment(
            db,
            tenant.id,
            requested["id"],
            AssignmentApprove(
                accountability_owner_id=employee.id, supervision_level="autonomous"
            ),
            user_id=user.id,
        )
        assert approved["status"] == "active"
        assert approved["approved_by_id"] == user.id
        assert approved["supervision_level"] == "autonomous"
        assert approved["accountability_owner_id"] == employee.id

        for call in (
            service.approve_assignment(
                db, tenant.id, requested["id"], AssignmentApprove(), user_id=user.id
            ),
            service.reject_assignment(db, tenant.id, requested["id"], user_id=user.id),
        ):
            with pytest.raises(AppError) as err:
                await call
            assert (err.value.code, err.value.status_code) == (
                "ai_assignment_not_pending",
                409,
            )
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "assignment.requested",
            "approval.granted",
        ]

    async def test_approve_requires_an_owner(self, db, tenant, user, employee):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        requested = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="Emails"),
            user_id=employee.user_id,
        )
        with pytest.raises(AppError) as err:
            await service.approve_assignment(
                db, tenant.id, requested["id"], AssignmentApprove(), user_id=user.id
            )
        assert (err.value.code, err.value.status_code) == (
            "ai_assignment_owner_required",
            400,
        )

    async def test_request_needs_an_employee_record(self, db, tenant, user):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        with pytest.raises(AppError) as err:
            await service.request_assignment(
                db,
                tenant.id,
                AssignmentRequest(agent_id=agent["id"], allowed_use_cases="x"),
                user_id=user.id,
            )
        assert (err.value.code, err.value.status_code) == ("employee_not_found", 404)

    async def test_reject_closes_the_row(self, db, tenant, user, employee):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        requested = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="x"),
            user_id=employee.user_id,
        )
        rejected = await service.reject_assignment(
            db, tenant.id, requested["id"], user_id=user.id, reason="No budget"
        )
        assert rejected["status"] == "rejected"
        with pytest.raises(AppError) as err:
            await service.update_assignment(
                db,
                tenant.id,
                requested["id"],
                AssignmentUpdate(allowed_use_cases="y"),
                user_id=user.id,
            )
        assert (err.value.code, err.value.status_code) == ("ai_assignment_closed", 409)
        with pytest.raises(AppError) as err:
            await service.revoke_assignment(
                db, tenant.id, requested["id"], user_id=user.id
            )
        assert (err.value.code, err.value.status_code) == (
            "ai_assignment_not_active",
            409,
        )
        row = (
            await db.execute(
                select(AIWorkforceAuditLog).where(
                    AIWorkforceAuditLog.tenant_id == tenant.id,
                    AIWorkforceAuditLog.action == "assignment.rejected",
                )
            )
        ).scalar_one()
        assert row.payload == {"reason": "No budget"}

    async def test_update_revoke_and_supervision_change(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        comp = await _competence(db, tenant.id)
        created = await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="x",
                accountability_owner_id=employee.id,
            ),
            user_id=user.id,
        )
        updated = await service.update_assignment(
            db,
            tenant.id,
            created["id"],
            AssignmentUpdate(
                allowed_use_cases="y",
                valid_until=date.today() + timedelta(days=10),
                competence_ids=[comp.id],
            ),
            user_id=user.id,
        )
        assert updated["allowed_use_cases"] == "y"
        assert updated["competence_ids"] == [comp.id]
        changed = await service.change_supervision_level(
            db, tenant.id, created["id"], "human_approval_gate", user_id=user.id
        )
        assert changed["supervision_level"] == "human_approval_gate"
        revoked = await service.revoke_assignment(
            db, tenant.id, created["id"], user_id=user.id
        )
        assert revoked["status"] == "revoked"
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "assignment.created",
            "assignment.updated",
            "supervision.changed",
            "assignment.revoked",
        ]
        row = (
            await db.execute(
                select(AIWorkforceAuditLog).where(
                    AIWorkforceAuditLog.tenant_id == tenant.id,
                    AIWorkforceAuditLog.action == "supervision.changed",
                )
            )
        ).scalar_one()
        assert row.payload == {
            "before": "human_review_required",
            "after": "human_approval_gate",
        }

    async def test_expiring_window(self, db, tenant, user, employee):
        await _setup(db)
        today = date.today()

        async def make(until: date | None, *, valid_from: date | None = None) -> dict:
            # One agent each: a pair may hold only one active grant.
            agent = await _agent(
                db, tenant.id, user.id, name=f"Cursor {uuid.uuid4().hex[:6]}"
            )
            return await service.create_assignment(
                db,
                tenant.id,
                AssignmentCreate(
                    employee_id=employee.id,
                    agent_id=agent["id"],
                    allowed_use_cases="x",
                    accountability_owner_id=employee.id,
                    valid_from=valid_from,
                    valid_until=until,
                ),
                user_id=user.id,
            )

        soon = await make(today + timedelta(days=5))
        later = await make(today + timedelta(days=60))
        revoked = await make(today + timedelta(days=5))
        await service.revoke_assignment(db, tenant.id, revoked["id"], user_id=user.id)
        await make(None)
        # Lapsed yesterday and still active: nothing flips it, so it must
        # stay visible until a person revokes it (decision 2026-09-09).
        overdue = await make(
            today - timedelta(days=1), valid_from=today - timedelta(days=30)
        )

        listed = await service.list_expiring_assignments(db, tenant.id)
        assert [a["id"] for a in listed] == [overdue["id"], soon["id"]]
        ids = {
            a["id"]
            for a in await service.list_expiring_assignments(
                db, tenant.id, days_ahead=90
            )
        }
        assert ids == {overdue["id"], soon["id"], later["id"]}

    async def test_assignment_tenant_isolation(self, db, tenant, user, employee):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        created = await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="x",
                accountability_owner_id=employee.id,
                valid_until=date.today() + timedelta(days=3),
            ),
            user_id=user.id,
        )
        other = await _other_tenant(db)
        for call in (
            service.get_assignment(db, other.id, created["id"]),
            service.update_assignment(
                db,
                other.id,
                created["id"],
                AssignmentUpdate(allowed_use_cases="y"),
                user_id=user.id,
            ),
            service.approve_assignment(
                db, other.id, created["id"], AssignmentApprove(), user_id=user.id
            ),
            service.reject_assignment(db, other.id, created["id"], user_id=user.id),
            service.revoke_assignment(db, other.id, created["id"], user_id=user.id),
            service.change_supervision_level(
                db, other.id, created["id"], "autonomous", user_id=user.id
            ),
        ):
            with pytest.raises(AppError) as err:
                await call
            assert (err.value.code, err.value.status_code) == (
                "ai_assignment_not_found",
                404,
            )
        assert await service.list_expiring_assignments(db, other.id) == []
        assert (await service.list_assignments(db, other.id))[1] == 0
        assert (await service.get_assignment(db, tenant.id, created["id"]))[
            "status"
        ] == "active"

    async def test_own_request_is_readable_by_the_requester_only(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        colleague = await _employee(db, tenant.id)
        requested = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="x"),
            user_id=employee.user_id,
        )
        mine = await service.get_assignment(
            db, tenant.id, requested["id"], requester_user_id=employee.user_id
        )
        assert mine["id"] == requested["id"]
        with pytest.raises(AppError) as err:
            await service.get_assignment(
                db, tenant.id, requested["id"], requester_user_id=colleague.user_id
            )
        assert (err.value.code, err.value.status_code) == (
            "ai_assignment_not_found",
            404,
        )
        # A second request for the same agent while one is pending is refused.
        with pytest.raises(AppError) as err:
            await service.request_assignment(
                db,
                tenant.id,
                AssignmentRequest(agent_id=agent["id"], allowed_use_cases="y"),
                user_id=employee.user_id,
            )
        assert (err.value.code, err.value.status_code) == (
            "ai_assignment_already_requested",
            409,
        )
        # Once decided, a new request is allowed again.
        await service.reject_assignment(db, tenant.id, requested["id"], user_id=user.id)
        again = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="y"),
            user_id=employee.user_id,
        )
        assert again["status"] == "pending"

    async def test_a_second_active_grant_for_one_pair_is_refused(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        body = AssignmentCreate(
            employee_id=employee.id,
            agent_id=agent["id"],
            allowed_use_cases="x",
            accountability_owner_id=employee.id,
        )
        first = await service.create_assignment(db, tenant.id, body, user_id=user.id)
        with pytest.raises(AppError) as err:
            await service.create_assignment(db, tenant.id, body, user_id=user.id)
        assert (err.value.code, err.value.status_code) == (
            "ai_assignment_already_active",
            409,
        )
        # Approving is the other route to an active row and takes the rule.
        requested = await service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(agent_id=agent["id"], allowed_use_cases="y"),
            user_id=employee.user_id,
        )
        with pytest.raises(AppError) as err:
            await service.approve_assignment(
                db,
                tenant.id,
                requested["id"],
                AssignmentApprove(accountability_owner_id=employee.id),
                user_id=user.id,
            )
        assert err.value.code == "ai_assignment_already_active"
        # The grant is re-issuable once the first one is closed.
        await service.revoke_assignment(db, tenant.id, first["id"], user_id=user.id)
        await service.create_assignment(db, tenant.id, body, user_id=user.id)

    async def test_a_grant_without_an_owner_is_not_active(
        self, db, tenant, user, employee
    ):
        """``accountability_owner_id`` is ON DELETE SET NULL: losing the
        owner employee leaves a row saying ``active`` with nobody answering
        for the agent's use, which is not a grant AR2 recognises."""
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        owner = await _employee(db, tenant.id)
        created = await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="x",
                accountability_owner_id=owner.id,
                valid_until=date.today() + timedelta(days=5),
            ),
            user_id=user.id,
        )
        assert (await service.list_assignments(db, tenant.id, status="active"))[1] == 1
        assert len(await service.list_expiring_assignments(db, tenant.id)) == 1

        await db.execute(delete(Employee).where(Employee.id == owner.id))
        await db.commit()

        assert (await service.list_assignments(db, tenant.id, status="active"))[1] == 0
        assert await service.list_expiring_assignments(db, tenant.id) == []
        # Still listed unfiltered, so it can be repaired rather than lost.
        items, total = await service.list_assignments(db, tenant.id)
        assert total == 1 and items[0]["id"] == created["id"]


class TestWorkflows:
    async def test_lifecycle_with_audit(self, db, tenant, user, employee):
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        wf = await service.create_workflow(
            db,
            tenant.id,
            WorkflowCreate(
                name="Invoice intake",
                owner_id=employee.id,
                human_role="reviewer",
                steps=[
                    WorkflowStep(
                        type="ai", title="Extract fields", agent_id=agent["id"]
                    ),
                    WorkflowStep(
                        type="human", title="Approve", escalation_to=employee.id
                    ),
                ],
                monthly_volume_estimate=400,
                error_rate_estimate=0.02,
                monthly_cost_estimate=Decimal("120"),
            ),
            user_id=user.id,
        )
        assert wf.is_active is True
        assert wf.cost_currency
        assert [s["type"] for s in wf.steps] == ["ai", "human"]

        updated = await service.update_workflow(
            db,
            tenant.id,
            wf.id,
            WorkflowUpdate(
                human_role="orchestrator",
                steps=[WorkflowStep(type="hybrid", title="All in one")],
            ),
            user_id=user.id,
        )
        assert updated.human_role == "orchestrator"
        assert len(updated.steps) == 1

        gone = await service.delete_workflow(db, tenant.id, wf.id, user_id=user.id)
        assert gone.is_active is False and gone.deactivated_at is not None
        items, total = await service.list_workflows(db, tenant.id, is_active=True)
        assert (items, total) == ([], 0)
        assert await _audit_actions(db, tenant.id) == [
            "agent.created",
            "workflow.created",
            "workflow.updated",
            "workflow.deactivated",
        ]

    async def test_owner_and_step_agents_must_be_in_tenant(
        self, db, tenant, user, employee
    ):
        await _setup(db)
        other = await _other_tenant(db)
        stranger = await _employee(db, other.id)
        theirs = await _agent(db, other.id, user.id, name="Theirs")
        with pytest.raises(AppError) as err:
            await service.create_workflow(
                db,
                tenant.id,
                WorkflowCreate(name="x", owner_id=stranger.id, human_role="executor"),
                user_id=user.id,
            )
        assert err.value.code == "employee_not_found"
        with pytest.raises(AppError) as err:
            await service.create_workflow(
                db,
                tenant.id,
                WorkflowCreate(
                    name="x",
                    owner_id=employee.id,
                    human_role="executor",
                    steps=[WorkflowStep(type="ai", title="s", agent_id=theirs["id"])],
                ),
                user_id=user.id,
            )
        assert err.value.code == "ai_agent_not_found"
        with pytest.raises(AppError) as err:
            await service.create_workflow(
                db,
                tenant.id,
                WorkflowCreate(
                    name="x",
                    owner_id=employee.id,
                    human_role="executor",
                    steps=[
                        WorkflowStep(type="human", title="s", escalation_to=employee.id),
                        WorkflowStep(
                            type="human", title="s2", escalation_to=stranger.id
                        ),
                    ],
                ),
                user_id=user.id,
            )
        assert err.value.code == "employee_not_found"
        with pytest.raises(AppError) as err:
            await service.get_workflow(db, tenant.id, uuid.uuid4())
        assert (err.value.code, err.value.status_code) == (
            "agent_workflow_not_found",
            404,
        )

    async def test_an_agent_a_workflow_runs_cannot_be_deactivated(
        self, db, tenant, user, employee
    ):
        """Step validation only checks that the agent exists, so a
        deactivated one would stay in ``steps`` and the process would keep
        pointing at an agent nobody may use."""
        await _setup(db)
        agent = await _agent(db, tenant.id, user.id)
        wf = await service.create_workflow(
            db,
            tenant.id,
            WorkflowCreate(
                name="Email triage",
                owner_id=employee.id,
                human_role="reviewer",
                steps=[
                    WorkflowStep(type="ai", title="Classify", agent_id=agent["id"]),
                    WorkflowStep(type="human", title="Answer"),
                ],
            ),
            user_id=user.id,
        )
        with pytest.raises(AppError) as err:
            await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)
        assert (err.value.code, err.value.status_code) == ("ai_agent_in_workflow", 409)

        await service.delete_workflow(db, tenant.id, wf.id, user_id=user.id)
        gone = await service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)
        assert gone["is_active"] is False


class TestAudit:
    async def test_list_filters(self, db, tenant, user, employee):
        await _setup(db)
        other = await _other_tenant(db)
        await _agent(db, other.id, user.id, name="Theirs")
        agent = await _agent(
            db,
            tenant.id,
            user.id,
            primitives=[PrimitiveOverride(code="P5", mode="add")],
        )
        await service.update_agent(
            db, tenant.id, agent["id"], AgentUpdate(vendor="v"), user_id=user.id
        )
        wf = await service.create_workflow(
            db,
            tenant.id,
            WorkflowCreate(name="w", owner_id=employee.id, human_role="observer"),
            user_id=user.id,
        )

        items, total = await service.list_audit(db, tenant.id)
        assert total == 3
        assert [e.action for e in items] == [
            "workflow.created",
            "agent.updated",
            "agent.created",
        ]
        items, total = await service.list_audit(
            db, tenant.id, target_type="ai_agent", target_id=agent["id"]
        )
        assert total == 2
        items, total = await service.list_audit(
            db, tenant.id, action="workflow.created"
        )
        assert [e.target_id for e in items] == [wf.id]
        items, total = await service.list_audit(db, tenant.id, actor_id=uuid.uuid4())
        assert total == 0
        # The other tenant's row never shows up.
        rows = (
            (
                await db.execute(
                    select(AIWorkforceAuditLog).where(
                        AIWorkforceAuditLog.tenant_id == other.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        agents_in_db = (
            (await db.execute(select(AIAgent).where(AIAgent.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        assert len(agents_in_db) == 1
        assert (
            await db.execute(
                select(AIUsageAssignment).where(
                    AIUsageAssignment.tenant_id == tenant.id
                )
            )
        ).scalars().all() == []


def test_schema_literals_match_model_check_tuples():
    """The API Literals and the DB CHECK tuples are two copies of one
    vocabulary; a value added on one side only would 422 or 500."""
    from typing import get_args

    from app.modules.ai_workforce import models, schemas

    pairs = [
        (schemas.AgentCategory, models.AGENT_CATEGORIES),
        (schemas.DataClassification, models.DATA_CLASSIFICATIONS),
        (schemas.SecurityReviewStatus, models.SECURITY_REVIEW_STATUSES),
        (schemas.RiskLevel, models.EU_AI_ACT_RISK_LEVELS),
        (schemas.OverrideMode, models.PRIMITIVE_OVERRIDE_MODES),
        (schemas.SupervisionLevel, models.SUPERVISION_LEVELS),
        (schemas.AssignmentStatus, models.ASSIGNMENT_STATUSES),
        (schemas.HumanRole, models.HUMAN_ROLE_KINDS),
        (schemas.AuditTargetType, models.AUDIT_TARGET_TYPES),
    ]
    for literal, tup in pairs:
        assert set(get_args(literal)) == set(tup), tup


def test_assignment_update_refuses_a_null_owner():
    from app.modules.ai_workforce.schemas import AssignmentUpdate
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AssignmentUpdate.model_validate({"accountability_owner_id": None})
    assert AssignmentUpdate.model_validate({}).accountability_owner_id is None
