"""HRP-826: assessments on the tenant's access matrix.

One menu entry, two halves. ``manage`` runs assessments - single and mass,
calibration, external reviewers, detailed results, CPA - within the
caller's read scope, and reads drafts and results there. ``view`` is the
respondent: answering is a POST, so the section guards itself - the gate
closes ``none``, the routes that run it ask for ``manage``. ``hr`` sits
at ``view`` by default and keeps the admin tier's read.
"""

import uuid

from tests.unit.test_exams_section_access import _employee_for
from tests.unit.test_section_gate import _save
from tests.unit.test_work_containers import _user_with_role

GATE = "auth_insufficient_permissions"


async def _person(db, tenant, code):
    user, token = await _user_with_role(db, tenant, code)
    emp = await _employee_for(db, tenant, user)
    return {"Authorization": f"Bearer {token}"}, emp


async def _assessment_for(client, headers, emp):
    return await client.post(
        "/api/assessments",
        json={"employee_id": str(emp.id), "type_code": "self"},
        headers=headers,
    )


def _ids(listed):
    return [a["id"] for a in listed.json()["items"]]


async def test_the_default_matrix_keeps_todays_answers(
    client, db, tenant, assessment_statuses, assessment_types
):
    # admin and manager run assessments, nobody else does - the role list
    # the routes carried until HRP-826, read off the matrix instead.
    for code in ("admin", "manager", "platform_admin"):
        h, emp = await _person(db, tenant, code)
        created = await _assessment_for(client, h, emp)
        assert created.status_code == 201, (code, created.text)
    for code in ("hr", "recruiter", "hiring_manager", "employee"):
        h, emp = await _person(db, tenant, code)
        refused = await _assessment_for(client, h, emp)
        assert refused.status_code == 403 and refused.json()["code"] == GATE, code
        for path in ("/api/assessments", "/api/assessments-grouped", "/api/answer-scales"):
            assert (await client.get(path, headers=h)).status_code == 200, (code, path)
        cpa = await client.get("/api/cpa", headers=h)
        assert cpa.status_code == 403 and cpa.json()["code"] == GATE, code
        me = await client.get("/api/auth/me", headers=h)
        assert me.json()["sections"]["assessments"] == "view", code


async def test_handing_the_section_to_hr_opens_running_it(
    auth_client, client, db, tenant, assessment_statuses, assessment_types
):
    hr, emp = await _person(db, tenant, "hr")
    assert (await _assessment_for(client, hr, emp)).status_code == 403

    await _save(auth_client, levels={"assessments": {"hr": "manage"}})

    created = await _assessment_for(client, hr, emp)
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    detailed = await client.get(f"/api/assessments/{aid}/detailed-results", headers=hr)
    assert detailed.status_code == 200, detailed.text
    assert (await client.get("/api/cpa", headers=hr)).status_code == 200


async def test_a_raised_role_runs_only_its_own_scope(
    auth_client, client, db, tenant, assessment_statuses, assessment_types
):
    # The level opens the section; whose assessment it is stays the org
    # structure's answer. A recruiter manages no division, so the raise
    # reaches their own record and nobody else's.
    recruiter, own = await _person(db, tenant, "recruiter")
    _, other = await _person(db, tenant, "employee")
    await _save(auth_client, levels={"assessments": {"recruiter": "manage"}})

    mine = await _assessment_for(client, recruiter, own)
    assert mine.status_code == 201, mine.text
    theirs = await _assessment_for(client, recruiter, other)
    assert theirs.status_code == 403 and theirs.json()["code"] == "outside_division_scope"
    foreign = (await _assessment_for(auth_client, None, other)).json()["id"]
    assert foreign not in _ids(await client.get("/api/assessments", headers=recruiter))


async def test_a_manager_lowered_to_view_stops_running_assessments(
    auth_client, client, db, tenant, assessment_statuses, assessment_types
):
    # "Sees drafts and results" was "admin-level or manager"; the manager
    # role is the level now, the admin tier stays.
    manager, emp = await _person(db, tenant, "manager")
    aid = (await _assessment_for(client, manager, emp)).json()["id"]
    assert aid in _ids(await client.get("/api/assessments", headers=manager))

    await _save(auth_client, levels={"assessments": {"manager": "view"}})

    assert aid not in _ids(await client.get("/api/assessments", headers=manager))
    for method, path, body in (
        ("post", "/api/assessments", {"employee_id": str(emp.id), "type_code": "self"}),
        ("patch", f"/api/assessments/{aid}", {"title": "Mine now"}),
        ("post", f"/api/assessments/{aid}/status", {"status_code": "active"}),
        ("get", f"/api/assessments/{aid}/detailed-results", None),
        ("get", f"/api/assessments/{aid}/external-reviewers", None),
        ("get", "/api/assessments/criteria/specializations", None),
        ("post", "/api/assessment-groups", {"employee_ids": [str(emp.id)], "type_code": "self"}),
        ("get", "/api/cpa", None),
    ):
        r = await client.request(method, path, json=body, headers=manager)
        assert r.status_code == 403 and r.json()["code"] == GATE, path

    # hr at `view` keeps the admin tier: whole tenant, drafts included.
    hr, _ = await _person(db, tenant, "hr")
    assert aid in _ids(await client.get("/api/assessments", headers=hr))


async def test_the_respondent_answers_at_view(client, db, tenant):
    # Answering is a POST at `view` - the gate's method rule would have cut
    # it, the reason the section guards itself. The route's own checks
    # answer (no such participant), not the gate.
    employee, _ = await _person(db, tenant, "employee")
    missing = str(uuid.uuid4())
    r = await client.post(
        f"/api/assessments/{missing}/answers",
        json={"participant_id": missing, "indicator_id": missing, "score": 1},
        headers=employee,
    )
    assert r.json().get("code") != GATE, r.text


async def test_taking_the_section_away_closes_it(
    auth_client, client, db, tenant, assessment_statuses, assessment_types
):
    employee, emp = await _person(db, tenant, "employee")
    aid = (await _assessment_for(auth_client, None, emp)).json()["id"]

    await _save(auth_client, levels={"assessments": {"employee": "none"}})

    missing = str(uuid.uuid4())
    for method, path, body in (
        ("get", "/api/assessments", None),
        ("get", "/api/assessments-grouped", None),
        ("get", f"/api/assessments/{aid}", None),
        ("get", "/api/answer-scales", None),
        (
            "post",
            f"/api/assessments/{aid}/answers",
            {"participant_id": missing, "indicator_id": missing, "score": 1},
        ),
    ):
        r = await client.request(method, path, json=body, headers=employee)
        assert r.status_code == 403 and r.json()["code"] == GATE, path
    me = await client.get("/api/auth/me", headers=employee)
    assert "assessments" not in me.json()["sections"]
