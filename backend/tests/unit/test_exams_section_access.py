"""HRP-823: the exams section on the tenant's access matrix.

Two halves, one menu entry. ``manage`` runs the mass exams - and reads
them, because a mass exam carries everyone's results and ``view`` is what
the other half of the entry means here: the employee taking an exam of
their own. That half stays outside the matrix, so closing the section
never strands an assignment the e-mail already linked to.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.modules.employee.models import Employee

from tests.unit.test_work_containers import _user_with_role

URL = "/api/settings/section-access"
MISSING = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _headers(db, tenant, code):
    _, token = await _user_with_role(db, tenant, code)
    return {"Authorization": f"Bearer {token}"}


async def _employee_for(db, tenant, user):
    emp = Employee(user_id=user.id, tenant_id=tenant.id, hire_date=date(2026, 1, 15))
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _launched_exam_for(auth_client, employee_ids):
    """A mass exam assigned to those employees and sent, made the way the
    UI makes one."""
    deadline = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    created = await auth_client.post(
        "/api/mass-exams", json={"title": f"Section probe {uuid.uuid4().hex[:6]}", "ended_at": deadline}
    )
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    question = await auth_client.post(
        f"/api/mass-exams/{mid}/questions",
        json={
            "title": "Does a closed section still hand over the answer key?",
            "question_type": "single_choice",
            "options": [{"title": "No", "is_correct": True}, {"title": "Yes", "is_correct": False}],
        },
    )
    assert question.status_code == 201, question.text
    assigned = await auth_client.post(f"/api/mass-exams/{mid}/employees", json=[str(e) for e in employee_ids])
    assert assigned.status_code == 201, assigned.text
    sent = await auth_client.post(f"/api/mass-exams/{mid}/status", json={"status_code": "sent"})
    assert sent.status_code == 200, sent.text
    return mid


async def _save(auth_client, levels):
    matrix = (await auth_client.get(URL)).json()
    body = []
    for s in matrix["sections"]:
        s["levels"].update(levels.get(s["code"], {}))
        body.append({"code": s["code"], "hidden": False, "levels": s["levels"]})
    r = await auth_client.put(URL, json={"sections": body})
    assert r.status_code == 200, r.text


async def test_the_default_matrix_keeps_todays_answers(client, db, tenant):
    # admin and manager run the section, nobody else reaches the mass
    # exams - the role lists the routes carried until HRP-823, now read
    # off the matrix instead.
    for code in ("admin", "manager"):
        r = await client.get("/api/mass-exams", headers=await _headers(db, tenant, code))
        assert r.status_code == 200, code
    for code in ("hr", "recruiter", "employee"):
        r = await client.get("/api/mass-exams", headers=await _headers(db, tenant, code))
        assert r.status_code == 403, code
        assert r.json()["code"] == "auth_insufficient_permissions"


async def test_handing_the_section_to_hr_opens_the_menu_and_the_writes(
    auth_client, client, db, tenant
):
    hr = await _headers(db, tenant, "hr")
    assert (await client.get("/api/mass-exams", headers=hr)).status_code == 403

    await _save(auth_client, {"exams": {"hr": "manage"}})

    assert (await client.get("/api/mass-exams", headers=hr)).status_code == 200
    created = await client.post(
        "/api/mass-exams", json={"title": "Safety briefing"}, headers=hr
    )
    assert created.status_code == 201, created.text
    assert (await client.get("/api/auth/me", headers=hr)).json()["sections"]["exams"] == "manage"


async def test_taking_the_section_away_closes_it_for_a_role_that_ran_it(
    auth_client, client, db, tenant
):
    manager = await _headers(db, tenant, "manager")
    assert (await client.get("/api/mass-exams", headers=manager)).status_code == 200

    await _save(auth_client, {"exams": {"manager": "none"}})

    closed = await client.get("/api/mass-exams", headers=manager)
    assert closed.status_code == 403 and closed.json()["code"] == "auth_insufficient_permissions"
    assert (
        await client.post("/api/mass-exams", json={"title": "x"}, headers=manager)
    ).status_code == 403
    assert "exams" not in (await client.get("/api/auth/me", headers=manager)).json()["sections"]


async def test_view_reads_no_mass_exam_it_could_not_read_before(
    auth_client, client, db, tenant
):
    # `view` is the taker's half of the entry, not a read-only manager:
    # `employee` defaults to it, so letting it list the mass exams would
    # hand the workspace's exams to everyone the day the section was
    # translated.
    await _save(auth_client, {"exams": {"manager": "view"}})
    manager = await _headers(db, tenant, "manager")
    assert (await client.get("/api/mass-exams", headers=manager)).status_code == 403
    assert (await client.get("/api/exams", headers=manager)).status_code == 200


async def test_an_assigned_exam_outlives_a_closed_section(auth_client, client, db, tenant):
    await _save(auth_client, {"exams": dict.fromkeys(("employee", "manager", "hr"), "none")})
    employee = await _headers(db, tenant, "employee")

    assert (await client.get("/api/exams", headers=employee)).status_code == 200
    # The four routes that take one exam answer for themselves - a missing
    # exam is a 404, never the gate's 403. That is the whole point of
    # keeping them out of the matrix: the assignment e-mail links here.
    for method, path in (
        ("get", f"/api/exams/{MISSING}/questions"),
        ("get", f"/api/exams/{MISSING}/review"),
        ("post", f"/api/exams/{MISSING}/finish"),
    ):
        r = await getattr(client, method)(path, headers=employee)
        assert r.json().get("code") != "auth_insufficient_permissions", path


async def test_a_closed_section_narrows_the_personal_reads_to_ones_own(
    auth_client, client, db, tenant
):
    # The other half of keeping `/exams*` out of the matrix: those routes
    # read more than one's own row - the list answers the caller's read
    # scope and `review` admits anyone it covers - so without this a role
    # set to `none` would keep reading its subtree's exams, and "taking
    # the section away closes its API" would be false.
    hr_user, hr_token = await _user_with_role(db, tenant, "hr")
    other_user, _ = await _user_with_role(db, tenant, "employee")
    hr_emp = await _employee_for(db, tenant, hr_user)
    other_emp = await _employee_for(db, tenant, other_user)
    await _launched_exam_for(auth_client, [hr_emp.id, other_emp.id])
    hr = {"Authorization": f"Bearer {hr_token}"}

    open_list = await client.get("/api/exams", headers=hr)
    assert open_list.status_code == 200
    assert {row["employee_id"] for row in open_list.json()} == {str(hr_emp.id), str(other_emp.id)}
    others = [row for row in open_list.json() if row["employee_id"] == str(other_emp.id)]
    # Someone else's exam is unfinished, not out of reach, while the
    # section is open: a 409 rather than a 403.
    assert (await client.get(f"/api/exams/{others[0]['id']}/review", headers=hr)).status_code == 409

    await _save(auth_client, {"exams": {"hr": "none"}})

    closed_list = await client.get("/api/exams", headers=hr)
    assert closed_list.status_code == 200
    assert {row["employee_id"] for row in closed_list.json()} == {str(hr_emp.id)}
    denied = await client.get(f"/api/exams/{others[0]['id']}/review", headers=hr)
    assert denied.status_code == 403 and denied.json()["code"] == "exam_belongs_to_another_employee"
    # Asking for the other employee by id is refused too, not silently widened.
    scoped = await client.get(f"/api/exams?employee_id={other_emp.id}", headers=hr)
    assert scoped.status_code == 403


async def test_the_taker_still_answers_and_finishes_a_closed_section(
    auth_client, client, db, tenant
):
    taker_user, taker_token = await _user_with_role(db, tenant, "employee")
    taker_emp = await _employee_for(db, tenant, taker_user)
    await _launched_exam_for(auth_client, [taker_emp.id])
    await _save(auth_client, {"exams": {"employee": "none"}})
    taker = {"Authorization": f"Bearer {taker_token}"}

    mine = await client.get("/api/exams", headers=taker)
    assert mine.status_code == 200 and len(mine.json()) == 1
    exam_id = mine.json()[0]["id"]
    take = await client.get(f"/api/exams/{exam_id}/questions", headers=taker)
    assert take.status_code == 200
    question = take.json()["questions"][0]
    answered = await client.post(
        f"/api/exams/{exam_id}/answer",
        json={"question_id": question["id"], "selected_option_ids": [question["options"][0]["id"]]},
        headers=taker,
    )
    assert answered.status_code == 201, answered.text
    finished = await client.post(f"/api/exams/{exam_id}/finish", headers=taker)
    assert finished.status_code == 200, finished.text
    assert (await client.get(f"/api/exams/{exam_id}/review", headers=taker)).status_code == 200
