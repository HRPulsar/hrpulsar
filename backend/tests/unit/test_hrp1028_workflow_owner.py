"""HRP-1028: dismissing the owner of an agent workflow flags the workflow
``needs_owner`` (the HRP-984 letter to the admins counts it), and naming an
owner at work clears the flag - both in the audit log with before / after."""

from __future__ import annotations

import pytest
from app.config import settings
from app.core.errors import AppError
from app.modules.ai_workforce import service
from app.modules.ai_workforce.models import AgentWorkflow, AIWorkforceAuditLog
from app.modules.ai_workforce.schemas import WorkflowCreate, WorkflowUpdate
from app.modules.notification import service as notification_service
from app.modules.notification.models import Notification
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_ai_workforce_service import _employee, _setup
from tests.unit.test_hrp984_ai_owner import _drop_templates, _grant, _templates


async def _workflow(db: AsyncSession, tenant, user, owner, name: str) -> AgentWorkflow:
    return await service.create_workflow(
        db,
        tenant.id,
        WorkflowCreate(name=name, owner_id=owner.id, human_role="executor"),
        user_id=user.id,
    )


async def _flag(db: AsyncSession, workflow_id) -> bool:
    return await db.scalar(
        select(AgentWorkflow.needs_owner).where(AgentWorkflow.id == workflow_id)
    )


async def _audit(db: AsyncSession, tenant_id, action: str) -> list[AIWorkforceAuditLog]:
    return list(
        (
            await db.execute(
                select(AIWorkforceAuditLog).where(
                    AIWorkforceAuditLog.tenant_id == tenant_id,
                    AIWorkforceAuditLog.action == action,
                )
            )
        )
        .scalars()
        .all()
    )


async def test_dismissal_flags_the_workflows_in_the_same_letter(
    db, tenant, user, auth_client, monkeypatch
):
    await _setup(db)
    monkeypatch.setattr(settings, "available_locales", "en")
    letters: list[str] = []
    monkeypatch.setattr(
        notification_service,
        "enqueue_email",
        lambda to, subject, body, **_: letters.append(to),
    )
    owner = await _employee(db, tenant.id)
    first = await _workflow(db, tenant, user, owner, "Invoices")
    second = await _workflow(db, tenant, user, owner, "Payroll")
    retired = await _workflow(db, tenant, user, owner, "Retired")
    await service.delete_workflow(db, tenant.id, retired.id, user_id=user.id)
    grant = await _grant(db, tenant, user, owner, "A")
    template_ids = await _templates(db)
    try:
        resp = await auth_client.put(
            f"/api/employees/{owner.id}", json={"status": "inactive"}
        )
        assert resp.status_code == 200, resp.text
        assert await _flag(db, first.id) and await _flag(db, second.id)
        # A deactivated workflow runs nothing - nobody to answer for.
        assert not await _flag(db, retired.id)

        # One letter for the grant and the workflows together.
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
        assert [n.recipient_id for n in notes] == [user.id]
        assert notes[0].context["count"] == 1
        assert notes[0].context["workflow_count"] == 2
        assert letters == [user.email]

        logged = await _audit(db, tenant.id, "workflow.needs_owner")
        assert {r.target_id for r in logged} == {first.id, second.id}
        assert logged[0].payload == {
            "before": {"needs_owner": False},
            "after": {"needs_owner": True},
            "owner_id": str(owner.id),
        }
        assert grant["id"]

        # Listed for the admin.
        listed = await auth_client.get("/api/ai-workforce/workflows?needs_owner=true")
        assert listed.status_code == 200, listed.text
        assert {w["id"] for w in listed.json()["items"]} == {
            str(first.id),
            str(second.id),
        }
        assert all(w["needs_owner"] for w in listed.json()["items"])

        # Saving the same status again finds nothing new: no second letter.
        resp = await auth_client.put(
            f"/api/employees/{owner.id}", json={"status": "inactive"}
        )
        assert resp.status_code == 200, resp.text
        assert letters == [user.email]
    finally:
        await _drop_templates(db, template_ids)


async def test_workflows_alone_still_send_the_letter(db, tenant, user, monkeypatch):
    await _setup(db)
    sent: list[dict] = []

    async def capture(db_, emp, count, workflow_count=0):
        sent.append({"count": count, "workflow_count": workflow_count})

    monkeypatch.setattr(service, "_notify_owner_needed", capture)
    owner = await _employee(db, tenant.id)
    wf = await _workflow(db, tenant, user, owner, "Only one")
    owner.status = "terminated"
    assert await service.release_dismissed_owner(db, owner, user_id=user.id) == 1
    await db.commit()
    assert await _flag(db, wf.id)
    assert sent == [{"count": 0, "workflow_count": 1}]


async def test_an_owner_at_work_clears_the_flag(db, tenant, user):
    await _setup(db)
    owner = await _employee(db, tenant.id)
    wf = await _workflow(db, tenant, user, owner, "Hand-over")
    owner.status = "terminated"
    await service.release_dismissed_owner(db, owner, user_id=user.id)
    await db.commit()
    assert await _flag(db, wf.id)

    # The dismissed owner cannot be named again while out of work.
    with pytest.raises(AppError) as err:
        await service.update_workflow(
            db, tenant.id, wf.id, WorkflowUpdate(owner_id=owner.id), user_id=user.id
        )
    assert err.value.code == "ai_workforce_owner_inactive"
    assert await _flag(db, wf.id)

    successor = await _employee(db, tenant.id)
    await service.update_workflow(
        db, tenant.id, wf.id, WorkflowUpdate(owner_id=successor.id), user_id=user.id
    )
    assert not await _flag(db, wf.id)
    [updated] = await _audit(db, tenant.id, "workflow.updated")
    assert updated.payload["before"] == {
        "owner_id": str(owner.id),
        "needs_owner": True,
    }
    assert updated.payload["after"] == {
        "owner_id": str(successor.id),
        "needs_owner": False,
    }
