"""Who may write an assessment or a development plan (HRP-638).

Reading was fenced long ago: the list and detail routes resolve
``get_visible_employee_ids`` and the service trims the payload row by row.
The mutating routes never asked. ``require_role("admin", "manager")``
answers "may you be on the assessment surface at all"; the assessee
arrives either in the request body or behind a path id that nobody
resolved back to an employee, so a division head could open, edit,
calibrate and re-plan anyone in the workspace — a neighbouring
department, or their own boss.

Same fence as ``app.core.access_scope``: admin / hr / platform_admin keep
the whole tenant, everyone else may only touch a row whose assessee sits
inside ``get_visible_employee_ids`` — their own employee record plus the
subtree they manage.

Written as request dependencies rather than an extra service argument
(the shape HRP-629 settled on for hiring). The mutating services here are
reached from this router and nowhere else, and a guard standing next to
``require_role`` in the signature is checkable: ``test_assessment_scope``
walks the route table and fails on a mutating assessment/PDP route that
carries none. That is the enforcement the "no default argument" rule was
after — a forgotten call site cannot go unnoticed.

Nested resources — plan items, item materials, participants, external
reviewers — are fenced through their parent. The parent's assessee is the
only owner they have, and each service already refuses a child whose
parent id does not match the path.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import Depends, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    ADMIN_ROLE_CODES,
    assert_authored,
    get_visible_employee_ids,
)
from app.core.errors import AppError
from app.core.sections import matrix_levels
from app.database import get_db
from app.modules.assessment.models import CPA, PDP, Assessment, AssessmentGroup
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User


def _refuse() -> None:
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def assert_assessee_in_scope(
    db: AsyncSession,
    current_user: User,
    employee_id: uuid.UUID,
) -> None:
    """403 unless ``current_user`` may write for this assessee.

    For the two routes that carry the assessee in the body — ``POST
    /assessments`` and ``POST /pdp`` — where a dependency would have to
    parse the body a second time to see it.
    """
    visible = await get_visible_employee_ids(db, current_user)
    if visible is None or employee_id in visible:
        return
    _refuse()


async def assert_assessees_in_scope(
    db: AsyncSession,
    current_user: User,
    employee_ids: Iterable[uuid.UUID],
) -> None:
    """403 unless every named assessee is inside the caller's subtree.

    ``POST /assessment-groups`` names its assessees in the body, exactly
    like ``POST /assessments``, and creates one assessment per name. All
    or nothing: silently dropping the names the caller may not touch
    would report a mass assessment it did not create.
    """
    visible = await get_visible_employee_ids(db, current_user)
    if visible is None or set(employee_ids) <= visible:
        return
    _refuse()


async def _assert_owner_visible(
    db: AsyncSession,
    visible: set[uuid.UUID] | None,
    stmt: Select,
) -> None:
    """403 unless ``stmt`` resolves to an assessee the caller may write.

    A row that does not exist is refused rather than reported missing —
    telling a division head that assessment X exists but is not theirs is
    itself a leak, and it is the rule HRP-629 already applies to hiring.
    """
    if visible is None:
        return
    employee_id = await db.scalar(stmt)
    if employee_id is None or employee_id not in visible:
        _refuse()


async def assert_assessment_in_scope(
    db: AsyncSession,
    current_user: User,
    assessment_id: uuid.UUID,
) -> None:
    """403 unless ``current_user`` may act on this assessment.

    For callers outside this router — ``POST /ai/suggest-pdp`` drafts a
    development plan for the assessment's assessee and spends tenant
    credits doing it.
    """
    await _assert_owner_visible(
        db,
        await get_visible_employee_ids(db, current_user),
        _assessment_owner(assessment_id, current_user.tenant_id),
    )


def _assessment_owner(assessment_id: uuid.UUID, tenant_id: uuid.UUID) -> Select:
    return select(Assessment.employee_id).where(
        Assessment.id == assessment_id,
        Assessment.tenant_id == tenant_id,
    )


async def assessment_visible_ids(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> set[uuid.UUID] | None:
    """``None`` = no restriction. Shared so a route carrying two guards
    walks the division tree once, via FastAPI's per-request cache."""
    return await get_visible_employee_ids(db, current_user)


async def assessment_scope(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    visible: set[uuid.UUID] | None = Depends(assessment_visible_ids),
) -> None:
    await _assert_owner_visible(
        db, visible, _assessment_owner(assessment_id, current_user.tenant_id)
    )


async def assessment_group_scope(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    visible: set[uuid.UUID] | None = Depends(assessment_visible_ids),
) -> None:
    """A mass assessment is the caller's when every assessment in it is.

    An ``AssessmentGroup`` carries no assessee and no division, only an
    author. This applies HRP-638's own rule to the children, which do
    carry an assessee: without it a
    division head could name anybody in the create body and then drive
    those assessments through the group's lifecycle routes, which is the
    same write the per-assessment routes refuse.

    An empty group is refused as well — nobody's subtree owns it.

    HRP-640 (Vladimir, 29.09): below the admin level the group's own
    actions are its author's too, so a head does not rename, re-criteria
    or bulk-move a run HR started over their team. Each assessment in it
    still follows the assessee rule on its own routes.
    """
    if visible is None:
        return
    await assert_authored(
        db,
        current_user,
        AssessmentGroup.initiator_id,
        (AssessmentGroup.id == group_id)
        & (AssessmentGroup.tenant_id == current_user.tenant_id),
    )
    row = (
        await db.execute(
            select(
                func.count(Assessment.id),
                func.count(Assessment.id).filter(
                    Assessment.employee_id.notin_(visible)
                ),
            ).where(
                Assessment.group_id == group_id,
                Assessment.tenant_id == current_user.tenant_id,
            )
        )
    ).one()
    total, outside = row
    if not total or outside:
        _refuse()


async def cpa_scope(
    cpa_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """HRP-640: below the admin level a CPA round is its author's alone."""
    await assert_authored(
        db,
        current_user,
        CPA.author_id,
        (CPA.id == cpa_id) & (CPA.tenant_id == current_user.tenant_id),
    )


async def pdp_scope(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    visible: set[uuid.UUID] | None = Depends(assessment_visible_ids),
) -> None:
    await _assert_owner_visible(
        db,
        visible,
        select(PDP.employee_id).where(
            PDP.id == pdp_id,
            PDP.tenant_id == current_user.tenant_id,
        ),
    )


async def pdp_status_scope(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    visible: set[uuid.UUID] | None = Depends(assessment_visible_ids),
) -> None:
    """``pdp_scope`` plus the named reviewer.

    The status route is the one place a plan is legitimately driven by
    somebody outside the assessee's division: ``PDP.reviewer_id`` may
    point at any user, and the review step is exactly what they were
    named for. The implicit reviewer — the assessee's division manager —
    passes the subtree check anyway.
    """
    if visible is None:
        return
    row = (
        await db.execute(
            select(PDP.employee_id, PDP.reviewer_id).where(
                PDP.id == pdp_id,
                PDP.tenant_id == current_user.tenant_id,
            )
        )
    ).first()
    if row is None:
        _refuse()
        return
    employee_id, reviewer_id = row
    if reviewer_id == current_user.id or employee_id in visible:
        return
    _refuse()


async def _admin_or_manage(db: AsyncSession, user: User, section: str) -> bool:
    if any(r.code in ADMIN_ROLE_CODES for r in user.roles):
        return True
    return (await matrix_levels(db, user))[section] == "manage"


async def runs_plans(db: AsyncSession, user: User) -> bool:
    """Sees other people's draft plans and walks the full status graph: an
    admin-level role or ``manage`` on ``development`` (HRP-825). Used to be
    "admin-level or manager" - the level replaced the manager role, the
    admin tier stays."""
    return await _admin_or_manage(db, user, "development")


async def runs_assessments(db: AsyncSession, user: User) -> bool:
    """Sees drafts and results of the assessments in the caller's read
    scope: an admin-level role or ``manage`` on ``assessments`` (HRP-826).
    Used to be ``not is_employee_only`` - "admin-level or manager" - and
    the level replaced the manager role the same way as ``runs_plans``.
    Anyone else reads active assessments they take part in, without
    results."""
    return await _admin_or_manage(db, user, "assessments")
