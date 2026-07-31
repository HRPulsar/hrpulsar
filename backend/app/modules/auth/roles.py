"""Shared helpers for system-role membership.

Deliberately separate from ``auth.service`` so the company / employee
services can reuse it without pulling in the whole auth service layer.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, user_roles

#: Every account falls back to this role — it carries no privileges beyond
#: "can see their own data", which is exactly what a downgraded manager keeps.
BASELINE_ROLE_CODE = "employee"


async def ensure_baseline_employee_role(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """HRP-196: guarantee the user still holds the baseline ``employee`` role.

    A downgrade removes ``manager``. A user who was invited straight as a
    manager holds that single role, so the removal left them with an empty
    role list — permissions still resolved correctly (everything falls back
    to "own data only"), but the UI had no role at all to display and the
    sidebar rendered a blank line instead of "Employee".

    Returns True when the role was actually inserted. The caller owns the
    surrounding transaction.
    """
    employee_role = (
        await db.execute(
            select(Role).where(
                Role.code == BASELINE_ROLE_CODE,
                Role.is_system == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if employee_role is None:
        # No `employee` role seeded in this installation — nothing to add.
        return False
    already_assigned = (
        await db.execute(
            select(user_roles.c.role_id).where(
                user_roles.c.user_id == user_id,
                user_roles.c.role_id == employee_role.id,
            )
        )
    ).first()
    if already_assigned is not None:
        return False
    await db.execute(
        user_roles.insert().values(user_id=user_id, role_id=employee_role.id)
    )
    return True
