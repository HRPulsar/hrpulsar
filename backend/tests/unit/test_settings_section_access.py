"""HRP-831: the admin block on the tenant's access matrix - import,
invitations, roles and AI settings.

``view`` reads (the import history, the AI settings, the role list, the
invitations in one's scope), ``manage`` writes. The four are admin-locked
and never hidden, so the admin keeps them whatever the tenant saves.
Invitations narrow by org structure below the admin level: a manager reads
and sends only into the divisions they head, on a seat of that subtree or
a workspace-wide one, and an invitation with no division is the admin
level's. Re-addressing an invitation is sending it, so a ``manage`` holder
edits, cancels and resends only what they could have sent (the inviter
hierarchy, with ``employee`` as the floor for a role the table has no row
for - Maxim, 26.09); changing the role of a sent invitation stays the admin
level's (the rbac seam).
"""

import uuid
from datetime import date

import pytest
from app.core import sections
from app.main import app
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from fastapi.routing import APIRoute

from tests.unit.test_catalogue_and_position_scope import _headers, _user
from tests.unit.test_section_gate import _save

GATE = "auth_insufficient_permissions"
FENCE = "outside_division_scope"
TIER = "role_above_inviter"
ADMIN_BLOCK = ("import", "invitations", "roles", "ai-settings")


def _refused(r, code=GATE):
    body = r.json()
    got = (
        body.get("code")
        or body.get("error_code")
        or body.get("detail", {}).get("error_code")
    )
    return r.status_code == 403 and got == code


def _invite(division_id=None, role="employee", **extra):
    return {
        "email": f"new-{uuid.uuid4().hex[:6]}@test.com",
        "name": "New Hire",
        "role_code": role,
        "division_id": str(division_id) if division_id else None,
        **extra,
    }


async def _headed(db, tenant, user) -> Division:
    emp = Employee(user_id=user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    division = Division(
        tenant_id=tenant.id, name=f"Headed {uuid.uuid4().hex[:4]}", manager_id=emp.id
    )
    db.add(division)
    await db.commit()
    await db.refresh(division)
    return division


def _level_of(route: APIRoute) -> str | None:
    """The level a route's ``require_section`` asks for, if it has one."""
    for dep in route.dependant.dependencies:
        fn = dep.call
        if getattr(fn, "__name__", "") == "section_checker":
            cells = dict(zip(fn.__code__.co_freevars, fn.__closure__, strict=True))
            return cells["level"].cell_contents
    return None


def test_every_route_of_the_admin_block_asks_for_its_level():
    # Reads ask for ``view``, writes for ``manage``; the one shared read
    # (``GET /roles``) answers for itself.
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        section = sections.section_for_path(route.path)
        if (
            section is None
            or section.code not in ADMIN_BLOCK
            or route.path.startswith("/api/auth/")
        ):
            continue
        reads = route.methods <= {"GET", "HEAD"}
        if route.path in sections.SHARED_READS and reads:
            assert _level_of(route) is None, route.path
            continue
        assert _level_of(route) == ("view" if reads else "manage"), (
            f"{sorted(route.methods)} {route.path}"
        )


async def test_the_default_matrix_keeps_todays_answers(client, db, tenant):
    hr, employee = (
        _headers(await _user(db, tenant, "hr")),
        _headers(await _user(db, tenant, "employee")),
    )
    for h in (hr, employee):
        assert _refused(await client.get("/api/import/jobs", headers=h))
        assert _refused(await client.get("/api/admin/ai-settings", headers=h))
        assert _refused(
            await client.post("/api/roles", json={"name": "X", "code": "x"}, headers=h)
        )
    # The role list is a shared read the invitation form is built on: it
    # answers whoever opens roles or invitations, and nobody else - it
    # carries how many people hold each role.
    assert (await client.get("/api/roles", headers=hr)).status_code == 200
    assert _refused(await client.get("/api/roles", headers=employee))
    assert _refused(await client.get("/api/invitations", headers=employee))
    assert (await client.get("/api/invitations", headers=hr)).status_code == 200


async def test_the_platform_role_reaches_the_admin_block(client, db, tenant):
    # ``require_role("admin")`` kept it out; the matrix never gates it.
    h = _headers(await _user(db, tenant, "platform_admin"))
    for path in (
        "/api/import/jobs",
        "/api/admin/ai-settings",
        "/api/roles",
        "/api/invitations",
    ):
        assert (await client.get(path, headers=h)).status_code == 200, path


async def test_view_reads_and_manage_writes(auth_client, client, db, tenant):
    hr, employee = (
        _headers(await _user(db, tenant, "hr")),
        _headers(await _user(db, tenant, "employee")),
    )
    await _save(
        auth_client,
        levels={
            "ai-settings": {"hr": "view"},
            "import": {"hr": "view"},
            "roles": {"hr": "view", "employee": "view"},
        },
    )
    assert (await client.get("/api/admin/ai-settings", headers=hr)).status_code == 200
    assert (await client.get("/api/import/jobs", headers=hr)).status_code == 200
    assert (await client.get("/api/roles", headers=employee)).status_code == 200
    assert _refused(await client.patch("/api/admin/ai-settings", json={}, headers=hr))
    assert _refused(
        await client.post(
            "/api/roles", json={"name": "Auditor", "code": "auditor"}, headers=hr
        )
    )
    assert _refused(
        await client.post(
            "/api/roles", json={"name": "Auditor", "code": "auditor"}, headers=employee
        )
    )

    await _save(
        auth_client, levels={"ai-settings": {"hr": "manage"}, "roles": {"hr": "manage"}}
    )
    assert (
        await client.patch("/api/admin/ai-settings", json={}, headers=hr)
    ).status_code == 200
    created = await client.post(
        "/api/roles",
        json={"name": "Auditor", "code": f"auditor-{uuid.uuid4().hex[:4]}"},
        headers=hr,
    )
    assert created.status_code == 201, created.text
    assert (
        await client.delete(f"/api/roles/{created.json()['id']}", headers=hr)
    ).status_code == 204


async def test_closing_a_section_closes_its_api_and_menu(
    auth_client, client, db, tenant
):
    hr = _headers(await _user(db, tenant, "hr"))
    await _save(auth_client, levels={"invitations": {"hr": "none"}})
    assert (
        "invitations"
        not in (await client.get("/api/auth/me", headers=hr)).json()["sections"]
    )
    assert _refused(await client.get("/api/invitations", headers=hr))
    assert _refused(await client.post("/api/invitations", json=_invite(), headers=hr))
    # The admin block never locks the admin out.
    matrix = (await auth_client.get("/api/settings/section-access")).json()
    for s in matrix["sections"]:
        if s["code"] in ADMIN_BLOCK:
            s["levels"]["admin"] = "none"
    r = await auth_client.put(
        "/api/settings/section-access",
        json={
            "sections": [
                {"code": s["code"], "hidden": s["hidden"], "levels": s["levels"]}
                for s in matrix["sections"]
            ]
        },
    )
    assert r.status_code == 400 and r.json()["code"] == "section_access_admin_locked"


async def test_invitations_narrow_to_the_subtree_below_the_admin_level(
    auth_client, client, db, tenant
):
    mgr_user = await _user(db, tenant, "manager")
    mine = await _headed(db, tenant, mgr_user)
    theirs = Division(tenant_id=tenant.id, name="Theirs")
    db.add(theirs)
    await db.commit()
    mgr, hr = _headers(mgr_user), _headers(await _user(db, tenant, "hr"))
    await _user(db, tenant, "employee")  # the role every invitation below hands out
    sent = await auth_client.post("/api/invitations", json=_invite(mine.id))
    assert sent.status_code == 201, sent.text
    inside = sent.json()
    outside = (
        await auth_client.post("/api/invitations", json=_invite(theirs.id))
    ).json()
    nowhere = (await auth_client.post("/api/invitations", json=_invite())).json()
    above = (
        await auth_client.post("/api/invitations", json=_invite(mine.id, "hr"))
    ).json()
    seat = (
        await auth_client.post(
            "/api/positions",
            json={"title": "Theirs seat", "division_id": str(theirs.id)},
        )
    ).json()

    # The manager reads and runs their subtree...
    listed = (await client.get("/api/invitations", headers=mgr)).json()
    assert {i["id"] for i in listed["items"]} == {inside["id"], above["id"]} and listed[
        "total"
    ] == 2
    assert (
        await client.post("/api/invitations", json=_invite(mine.id), headers=mgr)
    ).status_code == 201
    assert (
        await client.post(f"/api/invitations/{inside['id']}/resend", headers=mgr)
    ).status_code == 200
    # ...and nothing outside it - a division of someone else's, or none...
    for target in (theirs.id, None):
        assert _refused(
            await client.post("/api/invitations", json=_invite(target), headers=mgr),
            FENCE,
        )
    for inv in (outside, nowhere):
        assert _refused(
            await client.post(f"/api/invitations/{inv['id']}/cancel", headers=mgr),
            FENCE,
        )
        assert _refused(
            await client.patch(
                f"/api/invitations/{inv['id']}/email",
                json={"email": "x@test.com"},
                headers=mgr,
            ),
            FENCE,
        )
    assert _refused(
        await client.patch(
            f"/api/invitations/{inside['id']}",
            json={"division_id": str(theirs.id)},
            headers=mgr,
        ),
        FENCE,
    )
    assert _refused(
        await client.patch(
            f"/api/invitations/{inside['id']}", json={"division_id": None}, headers=mgr
        ),
        FENCE,
    )
    # ...nor a seat of another department (HRP-829), in any of the three ways.
    assert _refused(
        await client.post(
            "/api/invitations",
            json=_invite(mine.id, position_id=seat["id"]),
            headers=mgr,
        ),
        FENCE,
    )
    assert _refused(
        await client.patch(
            f"/api/invitations/{inside['id']}",
            json={"position_id": seat["id"]},
            headers=mgr,
        ),
        FENCE,
    )
    bulk = await client.post(
        "/api/invitations/bulk",
        json={
            "invitations": [
                _invite(mine.id),
                _invite(theirs.id),
                _invite(mine.id, position_id=seat["id"]),
            ]
        },
        headers=mgr,
    )
    assert bulk.status_code == 201 and len(bulk.json()["created"]) == 1
    assert [f["error_code"] for f in bulk.json()["failed"]] == [FENCE, FENCE]
    # Re-addressing is sending: an hr invitation in the subtree is seen, not touched.
    assert _refused(
        await client.patch(
            f"/api/invitations/{above['id']}/email",
            json={"email": "me@test.com"},
            headers=mgr,
        ),
        TIER,
    )
    assert _refused(
        await client.post(f"/api/invitations/{above['id']}/cancel", headers=mgr), TIER
    )
    assert (
        await client.post(f"/api/invitations/{uuid.uuid4()}/cancel", headers=mgr)
    ).status_code == 404

    # hr holds ``manage`` at the admin level: the whole registry, short of
    # the role change, which stays with the rbac seam.
    assert (await client.get("/api/invitations", headers=hr)).json()[
        "total"
    ] == 6  # four by the admin, two by the manager
    assert (
        await client.post(f"/api/invitations/{nowhere['id']}/cancel", headers=hr)
    ).status_code == 200
    assert _refused(
        await client.patch(
            f"/api/invitations/{outside['id']}",
            json={"role_code": "employee"},
            headers=hr,
        ),
        "only_admins_can_change_invitation_role",
    )

    # Lowered to ``view``, the manager still reads the subtree and sends nothing.
    await _save(auth_client, levels={"invitations": {"manager": "view"}})
    assert (await client.get("/api/invitations", headers=mgr)).json()["total"] == 4
    assert _refused(
        await client.post("/api/invitations", json=_invite(mine.id), headers=mgr)
    )
    assert _refused(
        await client.post(f"/api/invitations/{inside['id']}/cancel", headers=mgr)
    )


async def test_view_without_a_subtree_reads_an_empty_registry(
    auth_client, client, db, tenant
):
    # A raised role heading nothing reads nothing and sends nothing.
    h = _headers(await _user(db, tenant, "hiring_manager"))
    await _save(auth_client, levels={"invitations": {"hiring_manager": "view"}})
    listed = await client.get("/api/invitations", headers=h)
    assert listed.status_code == 200 and listed.json()["total"] == 0
    assert _refused(await client.post("/api/invitations", json=_invite(), headers=h))


async def test_a_raised_role_invites_employees_only(auth_client, client, db, tenant):
    recruiter = await _user(db, tenant, "recruiter")
    await _user(db, tenant, "employee")
    own = await _headed(db, tenant, recruiter)
    h = _headers(recruiter)
    assert _refused(
        await client.post("/api/invitations", json=_invite(own.id), headers=h)
    )

    await _save(auth_client, levels={"invitations": {"recruiter": "manage"}})
    assert (await client.get("/api/auth/me", headers=h)).json()["sections"][
        "invitations"
    ] == "manage"
    assert (
        await client.post("/api/invitations", json=_invite(own.id), headers=h)
    ).status_code == 201
    # No row in the inviter table: the floor is what a manager hands out.
    assert _refused(
        await client.post(
            "/api/invitations", json=_invite(own.id, "manager"), headers=h
        ),
        TIER,
    )
    assert _refused(
        await client.post(
            "/api/invitations", json=_invite(own.id, "recruiter"), headers=h
        ),
        TIER,
    )


@pytest.mark.parametrize("code", ADMIN_BLOCK)
def test_the_admin_block_is_locked_and_never_hidden(code):
    s = sections.SECTIONS_BY_CODE[code]
    assert s.admin_locked and s.never_hidden and not s.self_guarded
