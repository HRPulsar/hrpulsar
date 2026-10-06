"""HRP-984: the accountable owner of an AI agent usage grant is an employee
at work. A dismissed employee is named owner nowhere; dismissing one suspends the
grants in force they own (``needs_owner``) with one notification to the
tenant's admins, and a new owner at work puts each back in force."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from app.config import settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.ai_workforce import service
from app.modules.ai_workforce.models import AIUsageAssignment, AIWorkforceAuditLog
from app.modules.ai_workforce.schemas import (
    AssignmentApprove,
    AssignmentCreate,
    AssignmentRequest,
    AssignmentUpdate,
)
from app.modules.auth.models import User, user_roles
from app.modules.employee.models import Employee
from app.modules.notification import service as notification_service
from app.modules.notification.models import Notification, NotificationTemplate
from app.modules.public_api.schemas import EmployeeBatchUpdateItem
from app.modules.public_api.service import batch_update_employees
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_ai_workforce_service import _agent, _employee, _setup

CODE = service.OWNER_NEEDED_TEMPLATE


async def _terminated(db: AsyncSession, tenant_id: uuid.UUID) -> Employee:
    emp = await _employee(db, tenant_id)
    emp.status = "terminated"
    await db.commit()
    return emp


async def _grant(
    db: AsyncSession, tenant, user, owner: Employee, name: str, **extra
) -> dict:
    agent = await _agent(db, tenant.id, user.id, name=name)
    holder = await _employee(db, tenant.id)
    return await service.create_assignment(
        db,
        tenant.id,
        AssignmentCreate(
            employee_id=holder.id,
            agent_id=agent["id"],
            allowed_use_cases="x",
            accountability_owner_id=owner.id,
            **extra,
        ),
        user_id=user.id,
    )


async def _status(db: AsyncSession, assignment_id: uuid.UUID) -> str:
    # A column select reads the row, not the session's cached object.
    return await db.scalar(
        select(AIUsageAssignment.status).where(AIUsageAssignment.id == assignment_id)
    )


async def _templates(db: AsyncSession) -> list[uuid.UUID]:
    """The en/de rows of the migration; the unit DB is built by create_all."""
    rows = [
        NotificationTemplate(
            code=CODE,
            locale=locale,
            subject_template=subject,
            body_template="<p>{{ employee_name }}: {{ count }}</p>",
            notification_type="email",
        )
        for locale, subject in (
            ("en", "{{ count }} AI agent assignments need a new owner"),
            ("de", "{{ count }} KI-Agenten-Zuweisungen brauchen eine neue Person"),
        )
    ]
    db.add_all(rows)
    await db.commit()
    return [r.id for r in rows]


async def _drop_templates(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    await db.execute(delete(Notification).where(Notification.template_id.in_(ids)))
    await db.execute(
        delete(NotificationTemplate).where(NotificationTemplate.id.in_(ids))
    )
    await db.commit()


async def test_a_dismissed_employee_is_named_owner_nowhere(db, tenant, user, employee):
    await _setup(db)
    gone = await _terminated(db, tenant.id)
    agent = await _agent(db, tenant.id, user.id)
    for call in (
        service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=employee.id,
                agent_id=agent["id"],
                allowed_use_cases="x",
                accountability_owner_id=gone.id,
            ),
            user_id=user.id,
        ),
        service.request_assignment(
            db,
            tenant.id,
            AssignmentRequest(
                agent_id=agent["id"],
                allowed_use_cases="x",
                accountability_owner_id=gone.id,
            ),
            user_id=employee.user_id,
        ),
    ):
        with pytest.raises(AppError) as err:
            await call
        assert (err.value.code, err.value.status_code) == (
            "ai_workforce_owner_inactive",
            422,
        )
    requested = await service.request_assignment(
        db,
        tenant.id,
        AssignmentRequest(agent_id=agent["id"], allowed_use_cases="x"),
        user_id=employee.user_id,
    )
    with pytest.raises(AppError) as err:
        await service.approve_assignment(
            db,
            tenant.id,
            requested["id"],
            AssignmentApprove(accountability_owner_id=gone.id),
            user_id=user.id,
        )
    assert err.value.code == "ai_workforce_owner_inactive"
    assert await _status(db, requested["id"]) == "pending"


async def test_dismissal_suspends_the_grants_and_tells_each_admin_once(
    db, tenant, user, admin_role, auth_client, monkeypatch
):
    await _setup(db)
    monkeypatch.setattr(settings, "available_locales", "de,en")
    letters: list[tuple[str, str]] = []
    monkeypatch.setattr(
        notification_service,
        "enqueue_email",
        lambda to, subject, body, **_: letters.append((to, subject)),
    )
    owner = await _employee(db, tenant.id)
    first = await _grant(db, tenant, user, owner, "A")
    second = await _grant(db, tenant, user, owner, "B")
    requester = await _employee(db, tenant.id)
    pending = await service.request_assignment(
        db,
        tenant.id,
        AssignmentRequest(
            agent_id=(await _agent(db, tenant.id, user.id, name="C"))["id"],
            allowed_use_cases="x",
            accountability_owner_id=owner.id,
        ),
        user_id=requester.user_id,
    )
    # A second admin reads German: the letter follows the recipient.
    de_admin = User(
        email=f"de-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Zweite",
        last_name="Admin",
        tenant_id=tenant.id,
        language="de",
        email_verified_at=datetime.now(UTC),
    )
    db.add(de_admin)
    await db.flush()
    await db.execute(
        user_roles.insert().values(user_id=de_admin.id, role_id=admin_role.id)
    )
    await db.commit()
    template_ids = await _templates(db)
    try:
        resp = await auth_client.put(
            f"/api/employees/{owner.id}", json={"status": "terminated"}
        )
        assert resp.status_code == 200, resp.text
        assert await _status(db, first["id"]) == "needs_owner"
        assert await _status(db, second["id"]) == "needs_owner"
        assert await _status(db, pending["id"]) == "pending"

        notes = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.template_id.in_(template_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(n.recipient_id for n in notes) == sorted([user.id, de_admin.id])
        assert {n.context["count"] for n in notes} == {2}
        assert {n.context["link"] for n in notes} == {"/coverage"}
        assert sorted(letters) == sorted(
            [
                (user.email, "2 AI agent assignments need a new owner"),
                (de_admin.email, "2 KI-Agenten-Zuweisungen brauchen eine neue Person"),
            ]
        )
        logged = (
            (
                await db.execute(
                    select(AIWorkforceAuditLog).where(
                        AIWorkforceAuditLog.tenant_id == tenant.id,
                        AIWorkforceAuditLog.action == "assignment.needs_owner",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.target_id for r in logged} == {first["id"], second["id"]}
        assert {r.actor_id for r in logged} == {user.id}
        assert logged[0].payload == {
            "before": {"status": "active"},
            "after": {"status": "needs_owner"},
            "accountability_owner_id": str(owner.id),
        }

        # Saving the same status again finds nothing in force: no second round.
        resp = await auth_client.put(
            f"/api/employees/{owner.id}", json={"status": "terminated"}
        )
        assert resp.status_code == 200, resp.text
        assert len(letters) == 2
    finally:
        await _drop_templates(db, template_ids)


async def test_the_public_api_dismissal_suspends_too(db, tenant, user):
    await _setup(db)
    owner = await _employee(db, tenant.id)
    created = await _grant(db, tenant, user, owner, "A")
    result = await batch_update_employees(
        db, tenant.id, [EmployeeBatchUpdateItem(id=owner.id, status="terminated")]
    )
    assert result["errors"] == 0, result
    assert await _status(db, created["id"]) == "needs_owner"


async def test_needs_owner_grants_nothing_and_a_new_owner_restores_it(db, tenant, user):
    await _setup(db)
    owner = await _employee(db, tenant.id)
    soon = date.today() + timedelta(days=5)
    kept = await _grant(db, tenant, user, owner, "A", valid_until=soon)
    dropped = await _grant(db, tenant, user, owner, "B")
    owner.status = "terminated"
    assert await service.release_dismissed_owner(db, owner, user_id=user.id) == 2
    await db.commit()

    # Not a grant: the active listing, the expiring list and the one-grant
    # rule all read it as not in force - and it is not stacked under a new one.
    active, _ = await service.list_assignments(db, tenant.id, status="active")
    assert {a["id"] for a in active}.isdisjoint({kept["id"], dropped["id"]})
    waiting, _ = await service.list_assignments(db, tenant.id, status="needs_owner")
    assert {a["id"] for a in waiting} == {kept["id"], dropped["id"]}
    expiring = await service.list_expiring_assignments(db, tenant.id)
    assert kept["id"] not in {a["id"] for a in expiring}
    successor = await _employee(db, tenant.id)
    with pytest.raises(AppError) as err:
        await service.create_assignment(
            db,
            tenant.id,
            AssignmentCreate(
                employee_id=kept["employee_id"],
                agent_id=kept["agent_id"],
                allowed_use_cases="x",
                accountability_owner_id=successor.id,
            ),
            user_id=user.id,
        )
    assert err.value.code == "ai_assignment_already_active"

    # The dismissed owner cannot be named again; a successor at work can.
    with pytest.raises(AppError) as err:
        await service.update_assignment(
            db,
            tenant.id,
            kept["id"],
            AssignmentUpdate(accountability_owner_id=owner.id),
            user_id=user.id,
        )
    assert err.value.code == "ai_workforce_owner_inactive"
    restored = await service.update_assignment(
        db,
        tenant.id,
        kept["id"],
        AssignmentUpdate(accountability_owner_id=successor.id),
        user_id=user.id,
    )
    assert restored["status"] == "active"
    assert restored["accountability_owner_id"] == successor.id
    row = (
        await db.execute(
            select(AIWorkforceAuditLog).where(
                AIWorkforceAuditLog.target_id == kept["id"],
                AIWorkforceAuditLog.action == "assignment.updated",
            )
        )
    ).scalar_one()
    assert row.payload == {
        "before": {"accountability_owner_id": str(owner.id), "status": "needs_owner"},
        "after": {"accountability_owner_id": str(successor.id), "status": "active"},
    }

    # A grant waiting for an owner may be withdrawn instead.
    revoked = await service.revoke_assignment(
        db, tenant.id, dropped["id"], user_id=user.id
    )
    assert revoked["status"] == "revoked"
