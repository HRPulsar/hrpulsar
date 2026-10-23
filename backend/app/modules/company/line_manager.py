"""The one rule for "who is this employee's manager" (HRP-1048, HRP-1049)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company.models import Division
from app.modules.employee.models import Employee


async def resolve_line_manager(db: AsyncSession, employee: Employee) -> Employee | None:
    """The head of the employee's division; when that seat is empty or held
    by the employee themselves, the nearest assigned head up the ``parent``
    chain. Never the employee, never another tenant's row; ``None`` when
    nobody is assigned up to the root.
    """
    seen: set[uuid.UUID] = set()
    division_id = employee.division_id
    while division_id is not None and division_id not in seen:
        seen.add(division_id)
        division = await db.get(Division, division_id)
        if division is None or division.tenant_id != employee.tenant_id:
            return None
        if division.manager_id is not None and division.manager_id != employee.id:
            manager = await db.get(Employee, division.manager_id)
            if manager is not None and manager.tenant_id == employee.tenant_id:
                return manager
        division_id = division.parent_id
    return None
