"""HRP-824: the talent market on the tenant's access matrix.

One menu entry, two audiences. ``manage`` authors the board within the
caller's org scope - admin-level roles the workspace, anyone else their
managed subtree and the cards they created. ``view`` is the candidate's
half: the search, the cards one's own name is on, the reaction and the
plan request. That half is three POSTs, so the section guards itself: the
global gate closes ``none`` only and the routes ask for ``manage``.
Nothing here leaves the matrix - a closed section closes the candidate's
half too, e-mail link included.
"""

import uuid

from app.modules.company.models import Division

from tests.unit.test_exams_section_access import _employee_for
from tests.unit.test_section_gate import _headers, _save
from tests.unit.test_work_containers import _user_with_role

MISSING = uuid.UUID("00000000-0000-0000-0000-000000000000")
CARD = {"title": "Section probe", "card_type": "talent"}
GATE = "auth_insufficient_permissions"


async def _create(client, headers):
    return await client.post("/api/talent-market", json=CARD, headers=headers)


async def _search(client, headers):
    return await client.post("/api/talent-market/search", json={}, headers=headers)


async def test_the_default_matrix_keeps_todays_answers(client, db, tenant):
    # admin and manager author the board, nobody else does - the role list
    # the routes carried until HRP-824, read off the matrix instead. The
    # search is everyone's, and it is a POST: the reason the section rules
    # its own writes rather than leaving them to the gate's method rule.
    for code in ("admin", "manager"):
        h = await _headers(db, tenant, code)
        assert (await _create(client, h)).status_code == 201, code
        assert (await _search(client, h)).status_code == 200, code
    for code in ("hr", "recruiter", "hiring_manager", "employee"):
        h = await _headers(db, tenant, code)
        refused = await _create(client, h)
        assert refused.status_code == 403 and refused.json()["code"] == GATE, code
        assert (await _search(client, h)).status_code == 200, code
        me = await client.get("/api/auth/me", headers=h)
        assert me.json()["sections"]["talent-market"] == "view", code


async def test_handing_the_section_to_hr_opens_the_writes(auth_client, client, db, tenant):
    hr = await _headers(db, tenant, "hr")
    assert (await _create(client, hr)).status_code == 403

    await _save(auth_client, levels={"talent-market": {"hr": "manage"}})

    assert (await _create(client, hr)).status_code == 201
    me = await client.get("/api/auth/me", headers=hr)
    assert me.json()["sections"]["talent-market"] == "manage"


async def test_taking_the_section_away_closes_it_for_a_role_that_ran_it(
    auth_client, client, db, tenant
):
    manager = await _headers(db, tenant, "manager")
    created = await _create(client, manager)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    await _save(auth_client, levels={"talent-market": {"manager": "none"}})

    # The board and the candidate's half alike: nothing of the section
    # stays reachable, which is what leaves it inside the matrix.
    for method, path, body in (
        ("post", "/api/talent-market/search", {}),
        ("get", f"/api/talent-market/{cid}", None),
        ("post", f"/api/talent-market/{cid}/react", None),
        ("post", "/api/talent-market", CARD),
    ):
        r = await client.request(method, path, headers=manager, json=body)
        assert r.status_code == 403 and r.json()["code"] == GATE, path
    me = await client.get("/api/auth/me", headers=manager)
    assert "talent-market" not in me.json()["sections"]


async def test_view_keeps_the_candidates_half_and_nothing_of_the_board(
    auth_client, client, db, tenant
):
    # A division head lowered to `view` reads like the people on the cards:
    # the search answers, the reaction reaches the service (a 409 - the
    # card is still a draft - never the gate's 403), and no write passes.
    manager_user, token = await _user_with_role(db, tenant, "manager")
    emp = await _employee_for(db, tenant, manager_user)
    manager = {"Authorization": f"Bearer {token}"}
    cid = (await auth_client.post("/api/talent-market", json=CARD)).json()["id"]
    added = await auth_client.post(
        f"/api/talent-market/{cid}/candidates", json={"employee_id": str(emp.id)}
    )
    assert added.status_code == 201, added.text

    await _save(auth_client, levels={"talent-market": {"manager": "view"}})

    assert (await _search(client, manager)).status_code == 200
    reacted = await client.post(f"/api/talent-market/{cid}/react", headers=manager)
    assert reacted.status_code == 409, reacted.text
    assert reacted.json()["code"] == "tm_card_not_open_for_reactions"
    for path in ("/api/talent-market", f"/api/talent-market/{cid}/publish"):
        r = await client.post(path, json=CARD, headers=manager)
        assert r.status_code == 403 and r.json()["code"] == GATE, path


async def test_a_role_raised_to_manage_reads_what_it_authors(auth_client, client, db, tenant):
    # "Reads only the cards one's own name is on" was a role test until
    # HRP-824: a recruiter the tenant raised to `manage` would have created
    # a card and then not found it. The scope reads the level instead.
    await _save(auth_client, levels={"talent-market": {"recruiter": "manage"}})
    recruiter = await _headers(db, tenant, "recruiter")
    created = await _create(client, recruiter)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    listed = await _search(client, recruiter)
    assert [c["id"] for c in listed.json()["items"]] == [cid]
    assert listed.json()["items"][0]["can_manage"] is True
    detail = await client.get(f"/api/talent-market/{cid}", headers=recruiter)
    assert detail.status_code == 200 and detail.json()["can_manage"] is True


async def test_a_division_head_below_manage_keeps_only_their_own_breakdown(
    auth_client, client, db, tenant
):
    # Review of HRP-824: "may open anyone's breakdown" used to be "holds
    # admin or manager", and a managed division must not stand in for the
    # level - a head holding only the employee role reads their subtree's
    # cards, not every card's requirements and every colleague's scores.
    head_user, token = await _user_with_role(db, tenant, "employee")
    other_user, _ = await _user_with_role(db, tenant, "employee")
    head_emp = await _employee_for(db, tenant, head_user)
    other_emp = await _employee_for(db, tenant, other_user)
    db.add(Division(tenant_id=tenant.id, name="Led by an employee", manager_id=head_emp.id))
    await db.commit()
    head = {"Authorization": f"Bearer {token}"}
    cid = (await auth_client.post("/api/talent-market", json=CARD)).json()["id"]
    added = await auth_client.post(
        f"/api/talent-market/{cid}/candidates", json={"employee_id": str(other_emp.id)}
    )
    assert added.status_code == 201, added.text

    refused = await client.get(
        f"/api/talent-market/{cid}/candidates/{other_emp.id}/breakdown", headers=head
    )
    assert refused.status_code == 403 and refused.json()["code"] == "tm_insufficient_permissions"


async def test_manage_opens_breakdowns_of_the_cards_it_runs_not_of_others_drafts(
    auth_client, client, db, tenant
):
    # Review 01.10: a division head at `manage` who did not compete on the
    # card skipped every check, so another division's draft and any
    # employee's per-competence results opened by id.
    manager = await _headers(db, tenant, "manager")
    other_user, _ = await _user_with_role(db, tenant, "employee")
    other_emp = await _employee_for(db, tenant, other_user)
    elsewhere = Division(tenant_id=tenant.id, name=f"Elsewhere {uuid.uuid4().hex[:4]}")
    db.add(elsewhere)
    await db.commit()
    foreign = await auth_client.post(
        "/api/talent-market", json={**CARD, "division_id": str(elsewhere.id)}
    )
    assert foreign.status_code == 201, foreign.text
    refused = await client.get(
        f"/api/talent-market/{foreign.json()['id']}/candidates/{other_emp.id}/breakdown",
        headers=manager,
    )
    assert refused.status_code == 403 and refused.json()["code"] == "tm_insufficient_permissions"
    own = (await _create(client, manager)).json()["id"]
    opened = await client.get(
        f"/api/talent-market/{own}/candidates/{other_emp.id}/breakdown", headers=manager
    )
    assert opened.status_code == 200, opened.text


async def test_manage_deletes_within_scope_and_not_beyond(auth_client, client, db, tenant):
    # Delete stood on an admin-only role guard with no scope at all, while
    # the list's action menu offered it to a division head on their own
    # cards - and answered 403. Now it is a write like the others.
    manager = await _headers(db, tenant, "manager")
    own = (await _create(client, manager)).json()["id"]
    boards = (await auth_client.post("/api/talent-market", json=CARD)).json()["id"]

    refused = await client.delete(f"/api/talent-market/{boards}", headers=manager)
    assert refused.status_code == 403 and refused.json().get("code") != GATE
    assert (await client.delete(f"/api/talent-market/{own}", headers=manager)).status_code == 204
    assert (await client.delete(f"/api/talent-market/{own}", headers=manager)).status_code == 403


async def test_the_plan_from_a_card_asks_the_development_section_too(
    auth_client, client, db, tenant
):
    # HR raised to `manage` on the board still holds `view` on development
    # plans by default, and the plan is that section's record - the rule
    # HRP-821 set for a Coverage gap raising a vacancy.
    await _save(auth_client, levels={"talent-market": {"hr": "manage"}})
    hr = await _headers(db, tenant, "hr")
    path = f"/api/talent-market/{MISSING}/candidates/{MISSING}/development-plan"

    refused = await client.post(path, json={}, headers=hr)
    assert refused.status_code == 403 and refused.json()["code"] == GATE
    # The admin runs both sections: past the gates, a missing card is 404.
    assert (await auth_client.post(path, json={})).status_code == 404


async def test_a_market_closed_to_the_caller_takes_no_postings_from_a_vacancy(
    auth_client, client, db, tenant
):
    # The bridge from recruitment writes a talent-market record from outside
    # the section's own routes - the class of hole HRP-821 found on Coverage.
    path = f"/api/recruitment/vacancies/{MISSING}/talent-card"
    assert (await auth_client.post(path)).status_code == 404

    await _save(auth_client, hidden=["talent-market"])

    refused = await auth_client.post(path)
    assert refused.status_code == 403 and refused.json()["code"] == GATE


async def test_platform_admin_authors_the_board(client, db, tenant):
    # The role guard it replaced did not list the platform role; the matrix
    # reads it as `manage` everywhere, the way it does on every section.
    h = await _headers(db, tenant, "platform_admin")
    assert (await _create(client, h)).status_code == 201
