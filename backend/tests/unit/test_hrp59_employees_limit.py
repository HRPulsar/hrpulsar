"""HRP-59 / HRP-160: the /company and /company/divisions/{id} pages hit
`/api/employees?limit=500` (with and without a `division_id` filter) to
populate the Manager / Deputy picker and the Employees block. The
previous `le=100` cap silently produced a 422, the frontend's
`Promise.allSettled` swallowed it, and:

- the Employees block on the division page collapsed to "No employees
  in this division" (HRP-160);
- the Edit dialog's Manager / Deputy `<Select>` could not resolve the
  assignment label, so Base UI's `SelectValue` fell through to its
  serialized-value fallback and rendered the raw UUID (HRP-59).

This test pins the new ceiling (500) and keeps a regression guard on
the 501 case so we don't open the door wide enough to dump the whole
table at once.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession


class TestEmployeesListLimitCap:
    async def test_limit_500_is_accepted(self, auth_client):
        # The exact value the division detail page sends. Before HRP-59
        # / HRP-160 this 422'd and silently emptied the response.
        response = await auth_client.get("/api/employees?limit=500")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "items" in body
        assert "total" in body

    async def test_limit_500_with_division_filter_is_accepted(self, auth_client):
        # The exact shape used to populate the Employees block on
        # /company/divisions/{id}.
        response = await auth_client.get(
            "/api/employees?division_id=00000000-0000-0000-0000-000000000000&limit=500"
        )
        # Validates 200 (filter compiles even with a missing division)
        # rather than the prior 422 from the limit cap.
        assert response.status_code == 200, response.text

    async def test_limit_above_cap_is_rejected(self, auth_client):
        # `le=500` keeps the door from sliding open all the way.
        response = await auth_client.get("/api/employees?limit=501")
        assert response.status_code == 422


class TestEmployeeRolesDoNotAddQueriesPerRow:
    """HRP-621: the list carries each employee's role codes. ``User.roles``
    is a many-to-many, so a naive read is one SELECT per row — invisible on
    a seeded test tenant and a 100-query page in production."""

    async def test_role_codes_cost_one_query_for_the_whole_page(
        self, db: AsyncSession, tenant
    ):
        role = (
            (
                await db.execute(
                    select(Role).where(
                        Role.code == "employee",
                        Role.is_system.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )
        if role is None:
            role = Role(name="Employee", code="employee", is_system=True)
            db.add(role)
            await db.commit()
            await db.refresh(role)

        for _ in range(20):
            u = User(
                email=f"n1-{uuid.uuid4().hex[:8]}@test.com",
                password_hash=hash_password("x"),
                first_name="N",
                last_name="One",
                tenant_id=tenant.id,
                email_verified_at=datetime.now(timezone.utc),
            )
            db.add(u)
            await db.flush()
            await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
            db.add(
                Employee(user_id=u.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
            )
        await db.commit()
        db.expunge_all()

        role_queries: list[str] = []

        def _on_execute(conn, clauseelement, *args, **kwargs):  # noqa: ANN001
            text = str(clauseelement)
            if "FROM roles" in text:
                role_queries.append(text)

        bind = db.bind
        event.listen(bind.sync_engine, "before_execute", _on_execute)
        try:
            items, _ = await employee_service.list_employees(db, tenant.id, limit=100)
        finally:
            event.remove(bind.sync_engine, "before_execute", _on_execute)

        assert len(items) >= 20
        assert any(item["roles"] for item in items)
        # Exactly one: the batched selectin load for the whole page.
        assert len(role_queries) == 1, role_queries
