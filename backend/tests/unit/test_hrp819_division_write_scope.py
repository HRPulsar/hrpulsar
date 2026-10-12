"""HRP-819: a division head writes only inside the subtree they manage.

``POST /divisions``, ``PUT /divisions/{id}`` and the specialization
mapping routes sat on ``require_role("admin", "manager")`` and nothing
below the gate asked which divisions the manager actually runs — any
manager could rename, re-parent, map or create departments anywhere in
the company. The rule is the one ``/divisions/scope`` already answers
with: admin-equivalent roles hold the whole tree, a manager (or deputy)
holds their managed subtree to any depth, and a write outside it is
``outside_division_scope``.

Re-parenting is judged by the destination: the parent a manager's own
division already has is not theirs to hold, so sending it back
unchanged (the edit form does) passes, while moving the division
elsewhere — under a foreign department or to the root — does not.
"""

import uuid

import pytest_asyncio
from app.modules.auth.models import Role
from app.modules.company.models import Division
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_pdp_manager_visibility import (
    _auth_headers,
    _get_or_create_role,
    _make_employee,
    _make_user_with_role,
)


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession) -> Role:
    return await _get_or_create_role(db, "manager", "Manager")


async def _division(
    db: AsyncSession, tenant_id: uuid.UUID, name: str, **kw
) -> Division:
    d = Division(tenant_id=tenant_id, name=name, **kw)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


class TestManagerDivisionWriteScope:
    async def test_writes_stay_inside_the_managed_subtree(
        self, client: AsyncClient, db: AsyncSession, tenant, manager_role
    ) -> None:
        # Company -> Mine -> Child -> Grandchild, with Other standing apart.
        # The manager and the deputy of Mine own the subtree below it.
        mgr_user = await _make_user_with_role(db, tenant.id, manager_role, prefix="mgr")
        mgr_emp = await _make_employee(db, tenant.id, mgr_user.id)
        deputy_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="deputy"
        )
        deputy_emp = await _make_employee(db, tenant.id, deputy_user.id)
        root = await _division(db, tenant.id, "Company")
        other = await _division(db, tenant.id, "Other")
        mine = await _division(
            db,
            tenant.id,
            "Mine",
            parent_id=root.id,
            manager_id=mgr_emp.id,
            deputy_manager_id=deputy_emp.id,
        )
        child = await _division(db, tenant.id, "Child", parent_id=mine.id)
        grandchild = await _division(db, tenant.id, "Grandchild", parent_id=child.id)
        h = _auth_headers(mgr_user, tenant.id)

        refused = [
            ("PUT", f"/api/divisions/{other.id}", {"name": "X"}),
            ("PUT", f"/api/divisions/{root.id}", {"name": "X"}),
            ("PUT", f"/api/divisions/{mine.id}", {"parent_id": str(other.id)}),
            ("PUT", f"/api/divisions/{mine.id}", {"parent_id": None}),
            ("POST", "/api/divisions", {"name": "Sub", "parent_id": str(other.id)}),
            ("POST", "/api/divisions", {"name": "Top"}),
            (
                "POST",
                f"/api/divisions/{other.id}/specializations",
                {"specialization_id": str(uuid.uuid4())},
            ),
            (
                "DELETE",
                f"/api/divisions/{other.id}/specializations/{uuid.uuid4()}",
                None,
            ),
        ]
        for method, url, body in refused:
            resp = await client.request(method, url, json=body, headers=h)
            assert resp.status_code == 403, (method, url, resp.text)
            assert resp.json()["detail"]["error_code"] == "outside_division_scope"

        allowed = [
            # The edit form sends the current parent back unchanged.
            (
                h,
                "PUT",
                f"/api/divisions/{mine.id}",
                {"name": "Mine v2", "parent_id": str(root.id)},
            ),
            # Any depth below the managed root, with or without a parent_id.
            (h, "PUT", f"/api/divisions/{grandchild.id}", {"name": "Deep"}),
            (
                h,
                "POST",
                "/api/divisions",
                {"name": "Sub", "parent_id": str(grandchild.id)},
            ),
            # The deputy holds the same subtree.
            (
                _auth_headers(deputy_user, tenant.id),
                "PUT",
                f"/api/divisions/{child.id}",
                {"name": "By deputy"},
            ),
        ]
        for headers, method, url, body in allowed:
            resp = await client.request(method, url, json=body, headers=headers)
            assert resp.status_code in (200, 201), (method, url, resp.text)

    async def test_admin_keeps_the_whole_tree(
        self, auth_client: AsyncClient, db: AsyncSession, tenant
    ) -> None:
        other = await _division(db, tenant.id, "Other")
        resp = await auth_client.put(f"/api/divisions/{other.id}", json={"name": "X"})
        assert resp.status_code == 200, resp.text
        resp = await auth_client.post("/api/divisions", json={"name": "Top"})
        assert resp.status_code == 201, resp.text


class TestHeadsFromOwnSubtree:
    """HRP-857: naming a head or deputy grants the manager role, so below
    the admin level it is someone of one's own subtree, or oneself - a
    person from elsewhere is the admin's to appoint (Vladimir, 29.09)."""

    async def test_a_head_comes_from_the_managed_subtree(
        self, client: AsyncClient, db: AsyncSession, tenant, manager_role
    ) -> None:
        employee_role = await _get_or_create_role(db, "employee", "Employee")
        mgr_user = await _make_user_with_role(db, tenant.id, manager_role, prefix="mgr")
        mgr_emp = await _make_employee(db, tenant.id, mgr_user.id)
        other = await _division(db, tenant.id, "Other")
        mine = await _division(db, tenant.id, "Mine", manager_id=mgr_emp.id)
        child = await _division(db, tenant.id, "Child", parent_id=mine.id)
        insider_user = await _make_user_with_role(db, tenant.id, employee_role, prefix="in")
        insider = await _make_employee(db, tenant.id, insider_user.id, child.id)
        outsider_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="out"
        )
        outsider = await _make_employee(db, tenant.id, outsider_user.id, other.id)
        h = _auth_headers(mgr_user, tenant.id)

        for method, url, body in [
            (
                "POST",
                "/api/divisions",
                {"name": "Sub", "parent_id": str(mine.id), "manager_id": str(outsider.id)},
            ),
            ("PUT", f"/api/divisions/{child.id}", {"deputy_manager_id": str(outsider.id)}),
        ]:
            resp = await client.request(method, url, json=body, headers=h)
            assert resp.status_code == 403, (method, url, resp.text)
            assert resp.json()["detail"]["error_code"] == "outside_division_scope"

        resp = await client.post(
            "/api/divisions",
            json={"name": "Sub", "parent_id": str(mine.id), "manager_id": str(insider.id)},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        resp = await client.put(
            f"/api/divisions/{child.id}", json={"manager_id": str(mgr_emp.id)}, headers=h
        )
        assert resp.status_code == 200, resp.text

        # A deputy an admin named from elsewhere comes back unchanged with
        # the edit form - not a new appointment, so the save goes through.
        child.deputy_manager_id = outsider.id
        await db.commit()
        resp = await client.put(
            f"/api/divisions/{child.id}",
            json={"name": "Child v2", "deputy_manager_id": str(outsider.id)},
            headers=h,
        )
        assert resp.status_code == 200, resp.text

        # Nor is taking that seat away theirs: leaving it may cost the
        # outsider the manager role, which is the admin's call too.
        for deputy in (None, str(insider.id)):
            resp = await client.put(
                f"/api/divisions/{child.id}",
                json={"deputy_manager_id": deputy},
                headers=h,
            )
            assert resp.status_code == 403, (deputy, resp.text)


class TestHeadDoesNotReplaceSelf:
    """HRP-819 (QA 09.10): below the admin level a head does not hand off
    a Manager / Deputy Manager seat they hold themselves — the change
    unseats the caller, so it is the admin's or HR's move."""

    async def test_manager_and_deputy_cannot_unseat_themselves(
        self, client: AsyncClient, db: AsyncSession, tenant, manager_role
    ) -> None:
        employee_role = await _get_or_create_role(db, "employee", "Employee")
        mgr_user = await _make_user_with_role(db, tenant.id, manager_role, prefix="mgr")
        deputy_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="dep"
        )
        insider_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="in"
        )
        mine = await _division(db, tenant.id, "Mine")
        mgr_emp = await _make_employee(db, tenant.id, mgr_user.id, mine.id)
        deputy_emp = await _make_employee(db, tenant.id, deputy_user.id, mine.id)
        insider = await _make_employee(db, tenant.id, insider_user.id, mine.id)
        mine.manager_id = mgr_emp.id
        mine.deputy_manager_id = deputy_emp.id
        await db.commit()

        # Replacing — or clearing — one's own seat is refused for both
        # fields, for the manager and for the deputy alike.
        refused = [
            (_auth_headers(mgr_user, tenant.id), {"manager_id": str(insider.id)}),
            (_auth_headers(mgr_user, tenant.id), {"manager_id": None}),
            (
                _auth_headers(deputy_user, tenant.id),
                {"deputy_manager_id": str(insider.id)},
            ),
            (_auth_headers(deputy_user, tenant.id), {"deputy_manager_id": None}),
        ]
        for headers, body in refused:
            resp = await client.put(
                f"/api/divisions/{mine.id}", json=body, headers=headers
            )
            assert resp.status_code == 403, (body, resp.text)
            assert (
                resp.json()["detail"]["error_code"] == "cannot_replace_self_as_head"
            )

        h = _auth_headers(mgr_user, tenant.id)
        # The edit form sending one's own seat back unchanged is not a
        # hand-off, and the seat someone else holds stays changeable.
        resp = await client.put(
            f"/api/divisions/{mine.id}",
            json={"name": "Mine v2", "manager_id": str(mgr_emp.id)},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        resp = await client.put(
            f"/api/divisions/{mine.id}",
            json={"deputy_manager_id": str(insider.id)},
            headers=h,
        )
        assert resp.status_code == 200, resp.text

    async def test_admin_replaces_their_own_seat(
        self, auth_client: AsyncClient, db: AsyncSession, tenant, employee
    ) -> None:
        mine = await _division(
            db, tenant.id, "Mine", manager_id=employee.id, deputy_manager_id=employee.id
        )
        other_user = await _make_user_with_role(
            db,
            tenant.id,
            await _get_or_create_role(db, "employee", "Employee"),
            prefix="next",
        )
        other = await _make_employee(db, tenant.id, other_user.id, mine.id)
        resp = await auth_client.put(
            f"/api/divisions/{mine.id}",
            json={"manager_id": str(other.id), "deputy_manager_id": None},
        )
        assert resp.status_code == 200, resp.text
