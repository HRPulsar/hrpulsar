"""AI workforce registry REST (AR3), headless: no dashboard UI in the MVP.

Rights: admin and hr manage the registry, manager reads it, any signed-in
user may request an agent for themselves. ``require_role`` rather than
``require_admin``: this is tenant data, not a platform surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.database import get_db
from app.modules.ai_workforce import service
from app.modules.ai_workforce.schemas import (
    AgentCategory,
    AgentCreate,
    AgentList,
    AgentPackRead,
    AgentPrimitivesUpdate,
    AgentRead,
    AgentUpdate,
    AssignmentApprove,
    AssignmentCreate,
    AssignmentDecision,
    AssignmentList,
    AssignmentRead,
    AssignmentRequest,
    AssignmentStatus,
    AssignmentUpdate,
    AuditList,
    AuditTargetType,
    HumanRole,
    SupervisionChange,
    WorkflowCreate,
    WorkflowList,
    WorkflowRead,
    WorkflowUpdate,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User

router = APIRouter(prefix="/ai-workforce", tags=["ai-workforce"])

_READ_ROLES = frozenset({"admin", "hr", "manager"})
_manage = require_role("admin", "hr")
_read = require_role(*sorted(_READ_ROLES))


def _audit_meta(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


# --- Packs ------------------------------------------------------------------


@router.get("/packs", response_model=list[AgentPackRead])
async def list_packs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agent packs visible to the workspace: the built-in nine plus the
    tenant's own. Reference data — readable under every role."""
    return await service.list_packs(db, current_user.tenant_id)


# --- Agents -----------------------------------------------------------------


@router.get("/agents", response_model=AgentList)
async def list_agents(
    is_active: bool | None = None,
    category: AgentCategory | None = None,
    pack_id: uuid.UUID | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    items, total = await service.list_agents(
        db,
        current_user.tenant_id,
        is_active=is_active,
        category=category,
        pack_id=pack_id,
        search=search,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.post("/agents", response_model=AgentRead, status_code=201)
async def create_agent(
    data: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.create_agent(
        db,
        current_user.tenant_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.get("/agents/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    return await service.get_agent(db, current_user.tenant_id, agent_id)


@router.patch("/agents/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.update_agent(
        db,
        current_user.tenant_id,
        agent_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.delete("/agents/{agent_id}", response_model=AgentRead)
async def delete_agent(
    agent_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    """Soft delete: deactivates the agent and revokes its open assignments."""
    return await service.delete_agent(
        db,
        current_user.tenant_id,
        agent_id,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.put("/agents/{agent_id}/primitives", response_model=AgentRead)
async def set_agent_primitives(
    agent_id: uuid.UUID,
    data: AgentPrimitivesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.set_agent_primitives(
        db,
        current_user.tenant_id,
        agent_id,
        data.primitives,
        user_id=current_user.id,
        **_audit_meta(request),
    )


# --- Usage assignments ------------------------------------------------------


@router.get("/assignments", response_model=AssignmentList)
async def list_assignments(
    employee_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    status: AssignmentStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    items, total = await service.list_assignments(
        db,
        current_user.tenant_id,
        employee_id=employee_id,
        agent_id=agent_id,
        owner_id=owner_id,
        status=status,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.get("/assignments/expiring", response_model=list[AssignmentRead])
async def list_expiring_assignments(
    days: int = Query(service.EXPIRY_WINDOW_DAYS, ge=0, le=366),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    return await service.list_expiring_assignments(
        db, current_user.tenant_id, days_ahead=days
    )


@router.post("/assignments", response_model=AssignmentRead, status_code=201)
async def create_assignment(
    data: AssignmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.create_assignment(
        db,
        current_user.tenant_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.post("/assignments/request", response_model=AssignmentRead, status_code=201)
async def request_assignment(
    data: AssignmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-service: ask for an agent for yourself; lands in ``pending``."""
    return await service.request_assignment(
        db,
        current_user.tenant_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentRead)
async def get_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registry roles read any row; anyone else only what they requested
    for themselves."""
    roles = {r.code for r in current_user.roles}
    return await service.get_assignment(
        db,
        current_user.tenant_id,
        assignment_id,
        requester_user_id=None if roles & _READ_ROLES else current_user.id,
    )


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead)
async def update_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.update_assignment(
        db,
        current_user.tenant_id,
        assignment_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.post("/assignments/{assignment_id}/approve", response_model=AssignmentRead)
async def approve_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentApprove,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.approve_assignment(
        db,
        current_user.tenant_id,
        assignment_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.post("/assignments/{assignment_id}/reject", response_model=AssignmentRead)
async def reject_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.reject_assignment(
        db,
        current_user.tenant_id,
        assignment_id,
        user_id=current_user.id,
        reason=data.reason,
        **_audit_meta(request),
    )


@router.post("/assignments/{assignment_id}/revoke", response_model=AssignmentRead)
async def revoke_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.revoke_assignment(
        db,
        current_user.tenant_id,
        assignment_id,
        user_id=current_user.id,
        reason=data.reason,
        **_audit_meta(request),
    )


@router.post(
    "/assignments/{assignment_id}/change-supervision", response_model=AssignmentRead
)
async def change_supervision(
    assignment_id: uuid.UUID,
    data: SupervisionChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.change_supervision_level(
        db,
        current_user.tenant_id,
        assignment_id,
        data.supervision_level,
        user_id=current_user.id,
        **_audit_meta(request),
    )


# --- Workflows --------------------------------------------------------------


@router.get("/workflows", response_model=WorkflowList)
async def list_workflows(
    is_active: bool | None = None,
    owner_id: uuid.UUID | None = None,
    human_role: HumanRole | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    items, total = await service.list_workflows(
        db,
        current_user.tenant_id,
        is_active=is_active,
        owner_id=owner_id,
        human_role=human_role,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.post("/workflows", response_model=WorkflowRead, status_code=201)
async def create_workflow(
    data: WorkflowCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.create_workflow(
        db,
        current_user.tenant_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_read),
):
    return await service.get_workflow(db, current_user.tenant_id, workflow_id)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.update_workflow(
        db,
        current_user.tenant_id,
        workflow_id,
        data,
        user_id=current_user.id,
        **_audit_meta(request),
    )


@router.delete("/workflows/{workflow_id}", response_model=WorkflowRead)
async def delete_workflow(
    workflow_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.delete_workflow(
        db,
        current_user.tenant_id,
        workflow_id,
        user_id=current_user.id,
        **_audit_meta(request),
    )


# --- Audit ------------------------------------------------------------------


@router.get("/audit", response_model=AuditList)
async def list_audit(
    target_type: AuditTargetType | None = None,
    target_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    items, total = await service.list_audit(
        db,
        current_user.tenant_id,
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}
