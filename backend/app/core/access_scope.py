"""Access-scope helpers: who sees what across modules.

`None` from `get_visible_employee_ids` means "no scope restriction" (admin / hr) —
callers must NOT add an `employee_id IN (...)` filter in that case. An empty `set()`
means "the user is not linked to any employee" and lists should return nothing.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.employee.models import Employee

ADMIN_ROLE_CODES = frozenset({"admin", "hr", "platform_admin"})
MANAGER_ROLE_CODES = frozenset({"manager"})


def _is_admin(current_user: User) -> bool:
    return any(r.code in ADMIN_ROLE_CODES for r in current_user.roles)


def _is_manager(current_user: User) -> bool:
    return any(r.code in MANAGER_ROLE_CODES for r in current_user.roles)


def is_employee_only(current_user: User) -> bool:
    """True if the caller has neither admin nor manager privileges.

    Used to apply stricter visibility (e.g. hide Draft assessments — HRP-40).
    """
    return not _is_admin(current_user) and not _is_manager(current_user)


async def get_managed_division_ids(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return all division IDs in the subtree managed by this employee.

    Empty list means the employee is not a manager / deputy of any division.
    """
    result = await db.execute(select(Division).where(Division.tenant_id == tenant_id))
    all_divisions = result.scalars().all()

    managed_roots = [
        d
        for d in all_divisions
        if d.manager_id == employee_id or d.deputy_manager_id == employee_id
    ]
    if not managed_roots:
        return []

    children_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for d in all_divisions:
        if d.parent_id:
            children_map.setdefault(d.parent_id, []).append(d.id)

    subtree_ids: list[uuid.UUID] = []
    queue = [d.id for d in managed_roots]
    while queue:
        current = queue.pop(0)
        subtree_ids.append(current)
        queue.extend(children_map.get(current, []))
    return subtree_ids


async def get_current_employee(db: AsyncSession, current_user: User) -> Employee | None:
    result = await db.execute(
        select(Employee).where(
            Employee.user_id == current_user.id,
            Employee.tenant_id == current_user.tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_visible_division_ids(
    db: AsyncSession, current_user: User
) -> list[uuid.UUID] | None:
    """List of division ids the current user can see for filter pickers.

    - Admin / HR / platform_admin → ``None`` (no restriction; show all).
    - Division manager → the managed subtree.
    - Anyone else → empty list.
    """
    if _is_admin(current_user):
        return None

    emp = await get_current_employee(db, current_user)
    if emp is None:
        return []

    return await get_managed_division_ids(db, current_user.tenant_id, emp.id)


async def get_visible_employee_ids(
    db: AsyncSession, current_user: User
) -> set[uuid.UUID] | None:
    """Set of employee ids the current user can see.

    - Admin / HR / platform_admin → ``None`` (no restriction).
    - Division manager → own employee + all employees in managed subtree.
    - Regular employee → own employee only.
    - User without an Employee row → empty set (sees nothing).
    """
    if _is_admin(current_user):
        return None

    emp = await get_current_employee(db, current_user)
    if emp is None:
        return set()

    visible: set[uuid.UUID] = {emp.id}

    division_ids = await get_managed_division_ids(db, current_user.tenant_id, emp.id)
    if division_ids:
        result = await db.execute(
            select(Employee.id).where(
                Employee.tenant_id == current_user.tenant_id,
                Employee.division_id.in_(division_ids),
            )
        )
        visible.update(result.scalars().all())
    return visible


async def assert_employee_write_scope(
    db: AsyncSession, current_user: User, target: Employee
) -> None:
    """Raise 403 if `current_user` cannot perform a write on `target`.

    - admin / hr / platform_admin → pass.
    - manager → target must be within `get_visible_employee_ids` (own division
      subtree). Otherwise 403 ``outside_division_scope``.
    - any other role → 403 ``employee_write_forbidden`` (router-level guards
      already block this; the assert is defence in depth).
    """
    if _is_admin(current_user):
        return

    if _is_manager(current_user):
        visible = await get_visible_employee_ids(db, current_user)
        if visible is None or target.id in visible:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "outside_division_scope",
                "message": "Employee is outside your division scope",
            },
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "employee_write_forbidden",
            "message": "Insufficient permissions for employee write operations",
        },
    )


def assert_not_self_edit_via_employees(current_user: User, target: Employee) -> None:
    """Block manager from editing their own employee record via /employees.

    Admin / hr / platform_admin can edit themselves freely. Managers cannot
    self-demote (status), reassign their own position/division, or otherwise
    mutate their own card via this endpoint — profile self-edits are routed
    through ``/auth/me`` (EMP1 allowlist).
    """
    if _is_admin(current_user):
        return
    if not _is_manager(current_user):
        return
    if target.user_id != current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "cannot_edit_self_status",
            "message": (
                "Managers cannot edit their own employee record; "
                "profile self-edits go through /auth/me"
            ),
        },
    )
