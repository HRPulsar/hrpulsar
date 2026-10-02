"""HRP-825: development plans on the tenant's access matrix.

One menu entry, two halves. ``manage`` authors plans within the caller's
read scope and walks the full status graph. ``view`` is the plan's own
people: the owner marks items and submits for review, the named reviewer
ticks items during the review, both comment. Those are POSTs, so the section guards
itself - the gate closes ``none``, the authoring routes ask for
``manage``. One's own plan stays inside the matrix: a closed section
closes it too.
"""

import uuid

from tests.unit.test_exams_section_access import _employee_for
from tests.unit.test_section_gate import _save
from tests.unit.test_work_containers import _user_with_role

MISSING = uuid.UUID("00000000-0000-0000-0000-000000000000")
GATE = "auth_insufficient_permissions"


async def _person(db, tenant, code):
    user, token = await _user_with_role(db, tenant, code)
    emp = await _employee_for(db, tenant, user)
    return {"Authorization": f"Bearer {token}"}, emp


async def _plan_for(client, headers, emp):
    return await client.post(
        "/api/pdp", json={"title": "Section probe", "employee_id": str(emp.id)}, headers=headers
    )


async def test_the_default_matrix_keeps_todays_answers(client, db, tenant):
    # admin and manager author plans, nobody else does - the role list the
    # routes carried until HRP-825, read off the matrix instead.
    for code in ("admin", "manager", "platform_admin"):
        h, emp = await _person(db, tenant, code)
        created = await _plan_for(client, h, emp)
        assert created.status_code == 201, (code, created.text)
    for code in ("hr", "recruiter", "hiring_manager", "employee"):
        h, emp = await _person(db, tenant, code)
        refused = await _plan_for(client, h, emp)
        assert refused.status_code == 403 and refused.json()["code"] == GATE, code
        assert (await client.get("/api/pdp", headers=h)).status_code == 200, code
        me = await client.get("/api/auth/me", headers=h)
        assert me.json()["sections"]["development"] == "view", code


async def test_handing_the_section_to_hr_opens_authoring(auth_client, client, db, tenant):
    hr, emp = await _person(db, tenant, "hr")
    assert (await _plan_for(client, hr, emp)).status_code == 403

    await _save(auth_client, levels={"development": {"hr": "manage"}})

    assert (await _plan_for(client, hr, emp)).status_code == 201
    drafted = await client.post(
        "/api/ai/suggest-pdp", json={"assessment_id": str(MISSING)}, headers=hr
    )
    assert drafted.json().get("code") != GATE


async def test_the_owners_half_writes_at_view_and_authoring_does_not(
    auth_client, client, db, tenant
):
    # The owner comments on their plan at `view` - a POST the gate's
    # method rule would have cut, the reason the section guards itself.
    owner, emp = await _person(db, tenant, "employee")
    pid = (await _plan_for(auth_client, None, emp)).json()["id"]

    commented = await client.post(
        f"/api/pdp/{pid}/comments", json={"text": "On it"}, headers=owner
    )
    assert commented.status_code == 201, commented.text
    for method, path, body in (
        ("patch", f"/api/pdp/{pid}", {"title": "Mine now"}),
        ("post", f"/api/pdp/{pid}/items/reorder", {"ordered_ids": []}),
        ("post", "/api/ai/suggest-pdp", {"assessment_id": str(MISSING)}),
    ):
        r = await client.request(method, path, json=body, headers=owner)
        assert r.status_code == 403 and r.json()["code"] == GATE, path


async def test_a_manager_lowered_to_view_stops_running_plans(auth_client, client, db, tenant):
    # "Sees drafts, walks the full graph" was "admin-level or manager"; the
    # manager role is the level now, the admin tier stays.
    manager, emp = await _person(db, tenant, "manager")
    pid = (await _plan_for(client, manager, emp)).json()["id"]
    listed = await client.get("/api/pdp", headers=manager)
    assert [p["id"] for p in listed.json()] == [pid]

    await _save(auth_client, levels={"development": {"manager": "view", "hr": "view"}})

    assert (await client.get("/api/pdp", headers=manager)).json() == []
    moved = await client.post(
        f"/api/pdp/{pid}/status", json={"status_code": "sent"}, headers=manager
    )
    assert moved.status_code == 403 and moved.json()["code"] == "pdp_status_change_forbidden"
    refused = await _plan_for(client, manager, emp)
    assert refused.status_code == 403 and refused.json()["code"] == GATE

    # hr at `view` keeps the admin tier: whole tenant, drafts included.
    hr, _ = await _person(db, tenant, "hr")
    assert pid in [p["id"] for p in (await client.get("/api/pdp", headers=hr)).json()]


async def test_taking_the_section_away_closes_it_own_plan_included(
    auth_client, client, db, tenant
):
    owner, emp = await _person(db, tenant, "employee")
    pid = (await _plan_for(auth_client, None, emp)).json()["id"]
    assert (await client.get(f"/api/pdp/{pid}", headers=owner)).status_code == 200
    # The chart opens at `view` and counts what the list shows: the admin's
    # draft is still being authored, so the owner's figures leave it out.
    stats = await client.get("/api/analytics/pdp", headers=owner)
    assert stats.status_code == 200 and stats.json()["total"] == 0
    assert (await auth_client.get("/api/analytics/pdp")).json()["by_status"]["draft"] >= 1

    await _save(auth_client, levels={"development": {"employee": "none"}})

    for method, path, body in (
        ("get", "/api/pdp", None),
        ("get", f"/api/pdp/{pid}", None),
        ("post", f"/api/pdp/{pid}/comments", {"text": "Still here?"}),
        ("get", f"/api/analytics/pdp/{pid}/progress", None),
        ("get", "/api/analytics/pdp", None),
    ):
        r = await client.request(method, path, json=body, headers=owner)
        assert r.status_code == 403 and r.json()["code"] == GATE, path
    me = await client.get("/api/auth/me", headers=owner)
    assert "development" not in me.json()["sections"]


async def test_a_hidden_section_takes_no_ai_drafts(auth_client):
    # ``/ai`` sits outside the gate; the drafting route asks for itself.
    path = "/api/ai/suggest-pdp"
    body = {"assessment_id": str(MISSING)}
    assert (await auth_client.post(path, json=body)).json().get("code") != GATE

    await _save(auth_client, hidden=["development"])

    refused = await auth_client.post(path, json=body)
    assert refused.status_code == 403 and refused.json()["code"] == GATE
