"""EMP3 — One-shot CLI to reconcile manager roles with division assignments.

For each tenant, finds users referenced as `Division.manager_id` or
`deputy_manager_id` (resolved via Employee.user_id) who do **not** already
hold a manager-or-higher role. Adds the system `manager` role to those users.

Skips users with `admin`, `hr`, or `platform_admin` — they are independent
of division assignments and are never auto-modified.

Idempotent: re-running on a clean state is a no-op.

Usage:
    python -m backend.scripts.emp3_role_consistency [--dry-run]

A summary log is printed to stdout. Capture it with `> log.md` to archive
under `docs/ops/migrations/EMP3_role_consistency_<date>.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from app.database import async_session
from app.modules.auth.models import Role, user_roles
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_NON_DOWNGRADABLE = frozenset({"admin", "hr", "platform_admin"})
_MANAGER_OR_HIGHER = frozenset({"manager", "admin", "hr", "platform_admin"})


async def _user_role_codes(db: AsyncSession, user_id) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == user_id)
    )
    return {code for (code,) in rows.all()}


async def reconcile(dry_run: bool = False) -> int:
    upgraded = 0
    skipped_admin = 0
    already_manager = 0

    async with async_session() as db:
        manager_role = (
            await db.execute(
                select(Role).where(
                    Role.code == "manager", Role.is_system == True  # noqa: E712
                )
            )
        ).scalar_one()

        tenants = (await db.execute(select(Tenant))).scalars().all()
        print(f"# EMP3 role consistency — {datetime.now(timezone.utc).isoformat()}")
        print(f"# tenants: {len(tenants)}, dry_run={dry_run}")
        print()

        for tenant in tenants:
            divisions = (
                (
                    await db.execute(
                        select(Division).where(Division.tenant_id == tenant.id)
                    )
                )
                .scalars()
                .all()
            )
            employee_ids: set = set()
            for d in divisions:
                if d.manager_id is not None:
                    employee_ids.add(d.manager_id)
                if d.deputy_manager_id is not None:
                    employee_ids.add(d.deputy_manager_id)
            if not employee_ids:
                continue

            user_ids: set = set()
            for emp_id in employee_ids:
                emp = await db.get(Employee, emp_id)
                if emp is not None:
                    user_ids.add(emp.user_id)

            for uid in user_ids:
                codes = await _user_role_codes(db, uid)
                if codes & _NON_DOWNGRADABLE:
                    skipped_admin += 1
                    continue
                if codes & _MANAGER_OR_HIGHER:
                    already_manager += 1
                    continue
                if dry_run:
                    print(
                        f"[dry-run] would upgrade user_id={uid} "
                        f"tenant_id={tenant.id} ({tenant.slug})"
                    )
                else:
                    await db.execute(
                        user_roles.insert().values(user_id=uid, role_id=manager_role.id)
                    )
                    print(
                        f"Upgraded user_id={uid} tenant_id={tenant.id} "
                        f"({tenant.slug})"
                    )
                upgraded += 1

        if not dry_run:
            await db.commit()

    print()
    print(f"# upgraded: {upgraded}")
    print(f"# skipped (admin/hr/platform_admin): {skipped_admin}")
    print(f"# already manager: {already_manager}")
    return upgraded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(reconcile(dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
