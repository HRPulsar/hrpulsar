"""HRP-753: the headless registry REST — role gates, tenant scoping and the
happy paths of each surface."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from app.core.security import create_access_token, hash_password
from app.modules.ai_workforce import service
from app.modules.ai_workforce.models import AIAgentPack
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.employee.models import Employee
from app.modules.primitives import catalog_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession) -> dict[str, uuid.UUID]:
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await service.seed_packs(db)
    rows = await db.execute(
        select(AIAgentPack.code, AIAgentPack.id).where(AIAgentPack.tenant_id.is_(None))
    )
    return dict(rows.all())


async def _role(db: AsyncSession, code: str) -> Role:
    role = (await db.execute(select(Role).where(Role.code == code))).scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
    return role


async def _user_with_role(
    db: AsyncSession, tenant: Tenant, code: str, *, employee: bool = False
) -> tuple[User, str, Employee | None]:
    role = await _role(db, code)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=code.title(),
        last_name="User",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    emp = None
    if employee:
        emp = Employee(user_id=u.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
        db.add(emp)
    await db.commit()
    return u, create_access_token(str(u.id), str(tenant.id)), emp


@pytest.fixture
def agent_body(packs_fixture):
    return {
        "name": "Cursor",
        "vendor": "Anysphere",
        "category": "code",
        "pack_id": str(packs_fixture["artifact_builder"]),
        "monthly_cost": "40.00",
        "primitives": [{"code": "P4", "mode": "add"}],
    }


@pytest.fixture
async def packs_fixture(db):
    return await _setup(db)


class TestAgents:
    async def test_admin_crud_and_effective_set(self, auth_client, agent_body):
        created = await auth_client.post("/api/ai-workforce/agents", json=agent_body)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["pack_code"] == "artifact_builder"
        assert body["effective_primitive_codes"] == ["P1", "P4", "P9"]
        assert body["cost_currency"]
        # Money travels as a decimal string, never a float.
        assert body["monthly_cost"] == "40.00"
        agent_id = body["id"]

        listed = await auth_client.get("/api/ai-workforce/agents")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        # Enum query params are validated, not silently matched to nothing.
        assert (
            await auth_client.get(
                "/api/ai-workforce/agents", params={"category": "robot"}
            )
        ).status_code == 422
        assert (
            await auth_client.get(
                "/api/ai-workforce/assignments", params={"status": "activ"}
            )
        ).status_code == 422

        put = await auth_client.put(
            f"/api/ai-workforce/agents/{agent_id}/primitives",
            json={"primitives": [{"code": "P9", "mode": "remove"}]},
        )
        assert put.status_code == 200
        assert put.json()["effective_primitive_codes"] == ["P1"]

        patched = await auth_client.patch(
            f"/api/ai-workforce/agents/{agent_id}",
            json={"security_review_status": "approved"},
        )
        assert patched.status_code == 200
        assert patched.json()["security_review_status"] == "approved"

        bad = await auth_client.patch(
            f"/api/ai-workforce/agents/{agent_id}", json={"category": "robot"}
        )
        assert bad.status_code == 422

        deleted = await auth_client.delete(f"/api/ai-workforce/agents/{agent_id}")
        assert deleted.status_code == 200
        assert deleted.json()["is_active"] is False

        packs = await auth_client.get("/api/ai-workforce/packs")
        assert packs.status_code == 200
        assert len(packs.json()) == 9

    async def test_role_gates(self, client, auth_client, db, tenant, agent_body):
        _, employee_token, _ = await _user_with_role(db, tenant, "employee")
        _, manager_token, _ = await _user_with_role(db, tenant, "manager")
        _, hr_token, _ = await _user_with_role(db, tenant, "hr")

        client.headers["Authorization"] = f"Bearer {employee_token}"
        assert (
            await client.post("/api/ai-workforce/agents", json=agent_body)
        ).status_code == 403
        assert (await client.get("/api/ai-workforce/agents")).status_code == 403
        # Reference data stays open to every role.
        assert (await client.get("/api/ai-workforce/packs")).status_code == 200

        client.headers["Authorization"] = f"Bearer {manager_token}"
        assert (await client.get("/api/ai-workforce/agents")).status_code == 200
        assert (
            await client.post("/api/ai-workforce/agents", json=agent_body)
        ).status_code == 403
        assert (await client.get("/api/ai-workforce/audit")).status_code == 403

        client.headers["Authorization"] = f"Bearer {hr_token}"
        created = await client.post("/api/ai-workforce/agents", json=agent_body)
        assert created.status_code == 201
        assert (await client.get("/api/ai-workforce/audit")).status_code == 200

    async def test_other_tenant_cannot_see_the_agent(
        self, auth_client, client, db, agent_body
    ):
        created = await auth_client.post("/api/ai-workforce/agents", json=agent_body)
        agent_id = created.json()["id"]
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        _, token, _ = await _user_with_role(db, other, "admin")
        client.headers["Authorization"] = f"Bearer {token}"
        assert (
            await client.get(f"/api/ai-workforce/agents/{agent_id}")
        ).status_code == 404
        assert (await client.get("/api/ai-workforce/agents")).json()["total"] == 0
        assert (await client.get("/api/ai-workforce/audit")).json()["total"] == 0


class TestAssignmentsAndWorkflows:
    async def test_request_approve_expiring_and_audit(
        self, auth_client, client, db, tenant, employee, agent_body
    ):
        # auth_client is the same object as client: keep the admin token.
        admin_auth = auth_client.headers["Authorization"]
        agent_id = (
            await auth_client.post("/api/ai-workforce/agents", json=agent_body)
        ).json()["id"]
        requester, requester_token, requester_emp = await _user_with_role(
            db, tenant, "employee", employee=True
        )

        client.headers["Authorization"] = f"Bearer {requester_token}"
        requested = await client.post(
            "/api/ai-workforce/assignments/request",
            json={"agent_id": agent_id, "allowed_use_cases": "Drafting emails"},
        )
        assert requested.status_code == 201, requested.text
        assert requested.json()["status"] == "pending"
        assert requested.json()["employee_id"] == str(requester_emp.id)
        # The requester reads their own row; a colleague without a registry
        # role gets 404 for it; lists stay closed.
        own = await client.get(
            f"/api/ai-workforce/assignments/{requested.json()['id']}"
        )
        assert own.status_code == 200
        assert own.json()["status"] == "pending"
        assert (await client.get("/api/ai-workforce/assignments")).status_code == 403
        _, colleague_token, _ = await _user_with_role(
            db, tenant, "employee", employee=True
        )
        client.headers["Authorization"] = f"Bearer {colleague_token}"
        assert (
            await client.get(f"/api/ai-workforce/assignments/{requested.json()['id']}")
        ).status_code == 404

        client.headers["Authorization"] = admin_auth
        approved = await client.post(
            f"/api/ai-workforce/assignments/{requested.json()['id']}/approve",
            json={
                "accountability_owner_id": str(employee.id),
                "valid_until": (date.today() + timedelta(days=7)).isoformat(),
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "active"

        expiring = await client.get("/api/ai-workforce/assignments/expiring?days=30")
        assert [a["id"] for a in expiring.json()] == [requested.json()["id"]]
        assert (
            await client.get("/api/ai-workforce/assignments/expiring?days=3")
        ).json() == []

        changed = await client.post(
            f"/api/ai-workforce/assignments/{requested.json()['id']}/change-supervision",
            json={"supervision_level": "autonomous"},
        )
        assert changed.json()["supervision_level"] == "autonomous"

        revoked = await client.post(
            f"/api/ai-workforce/assignments/{requested.json()['id']}/revoke",
            json={"reason": "Contract ended"},
        )
        assert revoked.json()["status"] == "revoked"
        again = await client.post(
            f"/api/ai-workforce/assignments/{requested.json()['id']}/revoke", json={}
        )
        assert again.status_code == 409
        assert again.json()["detail"] == "Only an active assignment can be revoked"

        wf = await client.post(
            "/api/ai-workforce/workflows",
            json={
                "name": "Email triage",
                "owner_id": str(employee.id),
                "human_role": "reviewer",
                "steps": [
                    {"type": "ai", "title": "Classify", "agent_id": agent_id},
                    {"type": "human", "title": "Answer"},
                ],
            },
        )
        assert wf.status_code == 201, wf.text
        assert wf.json()["is_active"] is True
        listed = await client.get("/api/ai-workforce/workflows")
        assert listed.json()["total"] == 1
        gone = await client.delete(f"/api/ai-workforce/workflows/{wf.json()['id']}")
        assert gone.json()["is_active"] is False

        audit = await client.get("/api/ai-workforce/audit")
        assert audit.status_code == 200
        actions = [e["action"] for e in audit.json()["items"]]
        assert actions == [
            "workflow.deactivated",
            "workflow.created",
            "assignment.revoked",
            "supervision.changed",
            "approval.granted",
            "assignment.requested",
            "agent.created",
        ]
        requested_row = next(
            e for e in audit.json()["items"] if e["action"] == "assignment.requested"
        )
        assert requested_row["actor_id"] == str(requester.id)
        assert requested_row["target_type"] == "ai_usage_assignment"
        filtered = await client.get(
            "/api/ai-workforce/audit", params={"action": "approval.granted"}
        )
        assert filtered.json()["total"] == 1


class TestExplicitNulls:
    """A PATCH body may omit a field, but sending ``null`` for a NOT NULL
    column used to reach the flush: an AttributeError on ``name`` and an
    IntegrityError - reported as a name collision - on the rest. Every one
    of them is a 422 naming the field now."""

    async def test_null_on_a_not_null_agent_column_is_422(
        self, auth_client, agent_body
    ):
        agent_id = (
            await auth_client.post("/api/ai-workforce/agents", json=agent_body)
        ).json()["id"]
        for field in (
            "name",
            "category",
            "data_classification",
            "security_review_status",
            "eu_ai_act_risk_level",
        ):
            answer = await auth_client.patch(
                f"/api/ai-workforce/agents/{agent_id}", json={field: None}
            )
            assert answer.status_code == 422, (field, answer.text)
        # The nullable neighbours still clear.
        cleared = await auth_client.patch(
            f"/api/ai-workforce/agents/{agent_id}", json={"vendor": None}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["vendor"] is None

    async def test_null_on_a_not_null_assignment_or_workflow_column_is_422(
        self, auth_client, db, tenant, employee, agent_body
    ):
        agent_id = (
            await auth_client.post("/api/ai-workforce/agents", json=agent_body)
        ).json()["id"]
        assignment_id = (
            await auth_client.post(
                "/api/ai-workforce/assignments",
                json={
                    "employee_id": str(employee.id),
                    "agent_id": agent_id,
                    "allowed_use_cases": "Drafting emails",
                    "accountability_owner_id": str(employee.id),
                },
            )
        ).json()["id"]
        for field in ("allowed_use_cases", "valid_from"):
            answer = await auth_client.patch(
                f"/api/ai-workforce/assignments/{assignment_id}", json={field: None}
            )
            assert answer.status_code == 422, (field, answer.text)

        workflow_id = (
            await auth_client.post(
                "/api/ai-workforce/workflows",
                json={
                    "name": "Email triage",
                    "owner_id": str(employee.id),
                    "human_role": "reviewer",
                    "steps": [{"type": "human", "title": "Answer"}],
                },
            )
        ).json()["id"]
        for field in ("name", "human_role"):
            answer = await auth_client.patch(
                f"/api/ai-workforce/workflows/{workflow_id}", json={field: None}
            )
            assert answer.status_code == 422, (field, answer.text)
        # ``steps: null`` keeps its documented meaning: leave them alone.
        kept = await auth_client.patch(
            f"/api/ai-workforce/workflows/{workflow_id}", json={"steps": None}
        )
        assert kept.status_code == 200, kept.text
        assert len(kept.json()["steps"]) == 1
