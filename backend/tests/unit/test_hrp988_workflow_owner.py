"""HRP-988: a workflow's owner is handed to another employee at work, never
cleared - not by a null, not by deleting the employee - and every hand-over
is in the audit log."""

from __future__ import annotations

import uuid

from app.modules.ai_workforce import service
from app.modules.ai_workforce.models import AIWorkforceAuditLog
from app.modules.ai_workforce.schemas import AssignmentCreate
from sqlalchemy import select

from tests.unit.test_ai_workforce_service import _agent, _employee, _setup


async def test_workflow_owner_is_replaced_never_cleared_and_logged(
    db, tenant, user, employee, auth_client
):
    gone = await _employee(db, tenant.id)
    gone.status = "terminated"
    await db.commit()
    body = {"name": "Triage", "human_role": "reviewer", "owner_id": str(gone.id)}
    refused = await auth_client.post("/api/ai-workforce/workflows", json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "ai_workforce_owner_inactive"
    created = await auth_client.post(
        "/api/ai-workforce/workflows", json={**body, "owner_id": str(employee.id)}
    )
    assert created.status_code == 201, created.text
    url = f"/api/ai-workforce/workflows/{created.json()['id']}"

    cleared = await auth_client.patch(url, json={"owner_id": None})
    assert cleared.status_code == 422, cleared.text
    to_gone = await auth_client.patch(url, json={"owner_id": str(gone.id)})
    assert to_gone.status_code == 422, to_gone.text
    assert to_gone.json()["code"] == "ai_workforce_owner_inactive"

    successor = await _employee(db, tenant.id)
    moved = await auth_client.patch(url, json={"owner_id": str(successor.id)})
    assert moved.status_code == 200, moved.text
    assert moved.json()["owner_id"] == str(successor.id)
    row = (
        await db.execute(
            select(AIWorkforceAuditLog).where(
                AIWorkforceAuditLog.target_id == uuid.UUID(created.json()["id"]),
                AIWorkforceAuditLog.action == "workflow.updated",
            )
        )
    ).scalar_one()
    assert row.actor_id == user.id
    assert row.payload == {
        "before": {"owner_id": str(employee.id)},
        "after": {"owner_id": str(successor.id)},
    }


async def test_an_ai_agent_owner_is_deleted_only_after_handing_over(
    db, tenant, user, employee, auth_client
):
    """Both owner FKs are ON DELETE SET NULL: deleting the employee would
    leave the workflow or the open grant with nobody behind it (HRP-984)."""
    await _setup(db)
    wf_owner = await _employee(db, tenant.id)
    grant_owner = await _employee(db, tenant.id)
    wf_owner_id, grant_owner_id = wf_owner.id, grant_owner.id
    workflow = await auth_client.post(
        "/api/ai-workforce/workflows",
        json={"name": "Triage", "human_role": "reviewer", "owner_id": str(wf_owner_id)},
    )
    assert workflow.status_code == 201, workflow.text
    holder = await _employee(db, tenant.id)
    grant = await service.create_assignment(
        db,
        tenant.id,
        AssignmentCreate(
            employee_id=holder.id,
            agent_id=(await _agent(db, tenant.id, user.id))["id"],
            allowed_use_cases="x",
            accountability_owner_id=grant_owner_id,
        ),
        user_id=user.id,
    )

    for owner_id in (wf_owner_id, grant_owner_id):
        blocked = await auth_client.delete(f"/api/employees/{owner_id}")
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["code"] == "ai_workforce_owner_delete_blocked"

    handed = await auth_client.patch(
        f"/api/ai-workforce/workflows/{workflow.json()['id']}",
        json={"owner_id": str(employee.id)},
    )
    assert handed.status_code == 200, handed.text
    handed = await auth_client.patch(
        f"/api/ai-workforce/assignments/{grant['id']}",
        json={"accountability_owner_id": str(employee.id)},
    )
    assert handed.status_code == 200, handed.text
    for owner_id in (wf_owner_id, grant_owner_id):
        deleted = await auth_client.delete(f"/api/employees/{owner_id}")
        assert deleted.status_code == 200, deleted.text
