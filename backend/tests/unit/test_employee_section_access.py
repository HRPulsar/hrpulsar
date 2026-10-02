"""HRP-829: the employees section on the tenant's access matrix.

``manage`` on ``employees`` runs the employee record - creates, edits and
moves people, keeps their history and pay - inside the caller's subtree,
admin-level roles the workspace. ``hr`` stays at ``view``: it never wrote
here, and since this ticket it no longer writes another's education and
courses either (Maxim, 24.09). A new record and a transfer land in the
caller's subtree, and one's own pay is not one's own to read or set. Deleting
someone, granting a role and the set-password link stay the admin role's.
The list and the card every other section reads answer whatever the matrix
says.
"""

import inspect
import uuid
from datetime import date

import pytest
from app.core.sections import section_for_path
from app.main import app
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from fastapi.routing import APIRoute

from tests.unit.test_catalogue_and_position_scope import _headers, _user
from tests.unit.test_section_gate import _save

GATE = "auth_insufficient_permissions"
FENCE = "outside_division_scope"
NO_WRITE = "employee_write_forbidden"
SELF = "cannot_edit_self_status"

EDUCATION = {
    "institution": "MIT",
    "degree": "BSc",
    "field_of_study": "CS",
    "start_date": "2015-09-01",
}
PAY = {"type": "salary", "amount": 1000, "currency": "EUR", "effective_date": "2025-01-01"}


def _refused(r, code=GATE):
    return r.status_code == 403 and r.json().get("code", r.json().get("error_code")) == code


async def _card(db, tenant, user, division):
    emp = Employee(user_id=user.id, tenant_id=tenant.id, division_id=division.id if division else None, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    # The app shares this session: an event on this card reads ``emp.user``,
    # which a request would have selectin-loaded and this constructor did not.
    await db.refresh(emp, ["user"])
    return emp


@pytest.fixture
async def org(db, tenant):
    """A manager heading ``mine`` with a report, a colleague in ``theirs``, an hr."""
    mine = Division(tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}")
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    mgr_user = await _user(db, tenant, "manager")
    mgr = await _card(db, tenant, mgr_user, mine)
    mine.manager_id = mgr.id
    await db.commit()
    report = await _card(db, tenant, await _user(db, tenant, "employee"), mine)
    colleague = await _card(db, tenant, await _user(db, tenant, "employee"), theirs)
    hr_user = await _user(db, tenant, "hr")
    return {
        "mine": mine,
        "theirs": theirs,
        "mgr_user": mgr_user,
        "mgr": mgr,
        "report": report,
        "colleague": colleague,
        "hr_user": hr_user,
    }


async def _hire(client, db, tenant, h, division):
    """POST /employees for a fresh account with no card yet."""
    body = {"user_id": str((await _user(db, tenant, "employee")).id), "hire_date": "2025-01-01"}
    if division is not None:
        body["division_id"] = str(division.id)
    return await client.post("/api/employees", json=body, headers=h)


async def test_the_default_matrix_keeps_todays_answers(client, db, tenant, org):
    mgr, hr = _headers(org["mgr_user"]), _headers(org["hr_user"])
    report, colleague = org["report"].id, org["colleague"].id

    # The division head runs their own subtree, as before...
    assert (await client.put(f"/api/employees/{report}", json={"status": "on_leave"}, headers=mgr)).status_code == 200
    assert _refused(await client.put(f"/api/employees/{colleague}", json={"status": "on_leave"}, headers=mgr), FENCE)
    assert (await _hire(client, db, tenant, mgr, org["mine"])).status_code == 201

    # ...hr reads the whole record at ``view`` and writes none of it.
    assert (await client.get("/api/auth/me", headers=hr)).json()["sections"]["employees"] == "view"
    rows = (await client.get("/api/employees?limit=200", headers=hr)).json()["items"]
    assert rows and all("status" in r for r in rows)
    assert _refused(await client.put(f"/api/employees/{colleague}", json={"status": "on_leave"}, headers=hr))
    assert _refused(await _hire(client, db, tenant, hr, None))
    assert _refused(await client.get(f"/api/employees/{colleague}/compensation", headers=hr))
    # Another's education was the one write the admin tier let hr through.
    assert _refused(await client.post(f"/api/employees/{colleague}/education", json=EDUCATION, headers=hr), NO_WRITE)


async def test_an_out_of_scope_write_does_not_say_who_holds_admin(client, db, tenant, org):
    # Review 01.10: the admin-level check ran before the subtree one, so an
    # out-of-scope target answered employee_write_forbidden when it held
    # admin or hr and outside_division_scope otherwise - a role oracle.
    mgr = _headers(org["mgr_user"])
    admin_card = await _card(db, tenant, await _user(db, tenant, "admin"), org["theirs"])
    for target in (admin_card.id, org["colleague"].id):
        r = await client.get(f"/api/employees/{target}/compensation", headers=mgr)
        assert _refused(r, FENCE), r.text


async def test_anyone_keeps_their_own_education_at_view(client, db, tenant, org):
    own = await _card(db, tenant, org["hr_user"], None)
    hr = _headers(org["hr_user"])
    created = await client.post(f"/api/employees/{own.id}/education", json=EDUCATION, headers=hr)
    assert created.status_code == 201, created.text
    employee = _headers(await _user(db, tenant, "employee"))
    assert _refused(await client.post(f"/api/employees/{own.id}/education", json=EDUCATION, headers=employee), NO_WRITE)


async def test_a_raised_role_runs_only_its_subtree(auth_client, client, db, tenant, org):
    recruiter = await _user(db, tenant, "recruiter")
    head = await _card(db, tenant, recruiter, org["theirs"])
    org["theirs"].manager_id = head.id
    await db.commit()
    h = _headers(recruiter)
    colleague, report = org["colleague"].id, org["report"].id

    assert _refused(await client.put(f"/api/employees/{colleague}", json={"status": "on_leave"}, headers=h))
    assert (await client.get("/api/employees?limit=200", headers=h)).json()["items"][0].get("status") is None
    await _save(auth_client, levels={"employees": {"recruiter": "manage"}})

    assert (await client.put(f"/api/employees/{colleague}", json={"status": "on_leave"}, headers=h)).status_code == 200
    assert (await client.post(f"/api/employees/{colleague}/education", json=EDUCATION, headers=h)).status_code == 201
    assert _refused(await client.put(f"/api/employees/{report}", json={"status": "on_leave"}, headers=h), FENCE)
    assert (await _hire(client, db, tenant, h, org["theirs"])).status_code == 201
    assert _refused(await _hire(client, db, tenant, h, org["mine"]), FENCE)
    rows = (await client.get("/api/employees?limit=200", headers=h)).json()["items"]
    assert {r["id"] for r in rows} >= {str(colleague)} and all("status" in r for r in rows)
    # The raise hands the record, not what only the admin role did.
    assert _refused(await client.delete(f"/api/employees/{colleague}", headers=h))
    assert _refused(await client.put(f"/api/employees/{colleague}/role", json={"role_code": "hr"}, headers=h))


async def test_hr_raised_to_manage_runs_the_workspace(auth_client, client, db, tenant, org):
    hr = _headers(org["hr_user"])
    await _save(auth_client, levels={"employees": {"hr": "manage"}})
    colleague = org["colleague"].id
    assert (await client.put(f"/api/employees/{colleague}", json={"division_id": None}, headers=hr)).status_code == 200
    assert (await _hire(client, db, tenant, hr, None)).status_code == 201
    assert (await client.post(f"/api/employees/{colleague}/compensation", json=PAY, headers=hr)).status_code == 201
    assert _refused(await client.delete(f"/api/employees/{colleague}", headers=hr))
    assert _refused(await client.post(f"/api/employees/{colleague}/set-password-link", headers=hr))


async def test_new_records_and_transfers_land_in_the_callers_subtree(client, db, tenant, org):
    mgr = _headers(org["mgr_user"])
    report = org["report"].id
    child = Division(tenant_id=tenant.id, name="Child", parent_id=org["mine"].id)
    db.add(child)
    await db.commit()

    assert (await client.put(f"/api/employees/{report}", json={"division_id": str(child.id)}, headers=mgr)).status_code == 200
    assert _refused(await client.put(f"/api/employees/{report}", json={"division_id": str(org["theirs"].id)}, headers=mgr), FENCE)
    assert _refused(await client.put(f"/api/employees/{report}", json={"division_id": None}, headers=mgr), FENCE)
    assert _refused(await _hire(client, db, tenant, mgr, None), FENCE)
    assert _refused(await _hire(client, db, tenant, mgr, org["theirs"]), FENCE)
    # Re-sending the division the card already has is no transfer.
    same = await client.put(f"/api/employees/{report}", json={"division_id": str(child.id), "status": "active"}, headers=mgr)
    assert same.status_code == 200, same.text


async def test_ones_own_pay_is_the_admin_levels(client, auth_client, db, tenant, org, employee):
    mgr, own = _headers(org["mgr_user"]), org["mgr"].id
    assert _refused(await client.get(f"/api/employees/{own}/compensation", headers=mgr), SELF)
    assert _refused(await client.post(f"/api/employees/{own}/compensation", json=PAY, headers=mgr), SELF)
    # A report's pay is still the division head's.
    report = org["report"].id
    item = await client.post(f"/api/employees/{report}/compensation", json=PAY, headers=mgr)
    assert item.status_code == 201, item.text
    # An admin-level role sets their own, as before.
    assert (await auth_client.post(f"/api/employees/{employee.id}/compensation", json=PAY)).status_code == 201
    mine = await auth_client.post(f"/api/employees/{own}/compensation", json=PAY)
    assert mine.status_code == 201
    for method in ("put", "delete"):
        kwargs = {"json": {"amount": 2000}} if method == "put" else {}
        r = await getattr(client, method)(f"/api/employees/{own}/compensation/{mine.json()['id']}", headers=mgr, **kwargs)
        assert _refused(r, SELF), method


async def test_lowering_the_manager_closes_the_writes_and_the_hr_rows(auth_client, client, db, tenant, org):
    mgr = _headers(org["mgr_user"])
    await _save(auth_client, levels={"employees": {"manager": "view"}})
    report = org["report"].id
    assert _refused(await client.put(f"/api/employees/{report}", json={"status": "on_leave"}, headers=mgr))
    assert _refused(await client.get(f"/api/employees/{report}/compensation", headers=mgr))
    assert _refused(await client.get("/api/employees/available-users", headers=mgr))
    assert _refused(await client.post(f"/api/employees/{report}/education", json=EDUCATION, headers=mgr), NO_WRITE)
    rows = (await client.get("/api/employees?limit=200", headers=mgr)).json()["items"]
    assert rows and all("status" not in r for r in rows)


async def test_closing_the_section_keeps_the_shared_reads(auth_client, client, db, tenant, org):
    user = await _user(db, tenant, "employee")
    own = await _card(db, tenant, user, org["mine"])
    h = _headers(user)
    await _save(auth_client, levels={"employees": {"employee": "none"}})

    assert "employees" not in (await client.get("/api/auth/me", headers=h)).json()["sections"]
    # The section's own reads close, one's own record included...
    for path in (f"/api/employees/{own.id}/education", f"/api/employees/{own.id}/events"):
        assert _refused(await client.get(path, headers=h)), path
    assert _refused(await client.post(f"/api/employees/{own.id}/education", json=EDUCATION, headers=h))
    # ...the people pickers every other section is built on do not.
    for path in ("/api/employees", f"/api/employees/{org['colleague'].id}", "/api/employees/me"):
        r = await client.get(path, headers=h)
        assert r.status_code == 200, (path, r.text)


def _guards(dependant) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__name__", "")
        if name in ("section_checker", "role_checker", "admin_checker"):
            out.append((name, inspect.getclosurevars(dep.call).nonlocals))
        out.extend(_guards(dep))
    return out


def _asks_for_itself(name: str, env: dict) -> bool:
    if name == "section_checker":
        return env["section"].code == "employees" and env["level"] == "manage"
    if name == "role_checker":
        return set(env["role_codes"]) == {"admin"}
    return True  # require_admin()


# HRP-66: one's own education and courses - the service lets the owner in
# and asks everyone else for ``manage`` (tested above), so the route itself
# only authenticates.
_SELF_SERVICE = {
    f"/api/employees/{{employee_id}}/{kind}{tail}"
    for kind in ("education", "courses")
    for tail in ("", "/{item_id}")
}
# Reads that are the record itself, not the directory or the HR card.
_MANAGED_READS = {
    "/api/employees/available-users",
    "/api/employees/{employee_id}/compensation",
}


def test_every_write_in_the_section_asks_for_itself():
    # ``employees`` is self-guarded: the gate lets ``view`` through on writes,
    # because anyone keeps their own education there. Every other write
    # route - and the two reads that are the record itself - must ask
    # ``manage`` on employees or the admin role, or it opens to every
    # ``view`` cell.
    routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and (s := section_for_path(r.path)) is not None
        and s.code == "employees"
    ]
    assert {r.path for r in routes if r.methods - {"GET"} and r.path in _SELF_SERVICE} == _SELF_SERVICE
    bare = [
        f"{sorted(r.methods)} {r.path}"
        for r in routes
        if (r.methods - {"GET", "HEAD", "OPTIONS"} and r.path not in _SELF_SERVICE)
        or r.path in _MANAGED_READS
        if not any(_asks_for_itself(*g) for g in _guards(r.dependant))
    ]
    assert not bare, bare


async def test_admin_level_records_are_closed_below_the_admin_level(auth_client, client, db, tenant, org):
    mgr = _headers(org["mgr_user"])
    # An admin already in the manager's subtree...
    boss = await _card(db, tenant, await _user(db, tenant, "admin"), org["mine"])
    assert _refused(await client.put(f"/api/employees/{boss.id}", json={"status": "terminated"}, headers=mgr), NO_WRITE)
    assert _refused(await client.get(f"/api/employees/{boss.id}/compensation", headers=mgr), NO_WRITE)
    # ...and one with no card yet, whom a card in the subtree would expose.
    owner = await _user(db, tenant, "admin")
    body = {"user_id": str(owner.id), "division_id": str(org["mine"].id), "hire_date": "2025-01-01"}
    assert _refused(await client.post("/api/employees", json=body, headers=mgr), NO_WRITE)
    offered = {u["id"] for u in (await client.get("/api/employees/available-users", headers=mgr)).json()}
    assert str(owner.id) not in offered
    assert str(owner.id) in {u["id"] for u in (await auth_client.get("/api/employees/available-users")).json()}


async def test_ones_own_record_below_the_admin_level_is_education_only(client, org):
    mgr, own = _headers(org["mgr_user"]), org["mgr"].id
    event = {"event_type": "compensation_change", "event_date": "2025-01-01"}
    assert _refused(await client.post(f"/api/employees/{own}/events", json=event, headers=mgr), SELF)
    history = {"company_name": "Acme", "position": "Y", "start_date": "2019-01-01", "end_date": "2020-01-01"}
    assert _refused(await client.post(f"/api/employees/{own}/previous-employment", json=history, headers=mgr), SELF)
    created = await client.post(f"/api/employees/{own}/education", json=EDUCATION, headers=mgr)
    assert created.status_code == 201, created.text
    # A report's history is still the division head's.
    assert (await client.post(f"/api/employees/{org['report'].id}/events", json=event, headers=mgr)).status_code == 201


async def test_a_seat_is_the_subtrees_or_the_workspaces(client, db, tenant, org):
    mgr, report = _headers(org["mgr_user"]), org["report"].id
    seats = {
        side: Position(tenant_id=tenant.id, title=f"{side} seat", source="manual", division_id=div)
        for side, div in (("mine", org["mine"].id), ("theirs", org["theirs"].id), ("general", None))
    }
    db.add_all(seats.values())
    await db.commit()
    move = lambda side: client.put(f"/api/employees/{report}", json={"position_id": str(seats[side].id)}, headers=mgr)  # noqa: E731
    assert _refused(await move("theirs"), FENCE)
    assert (await move("mine")).status_code == 200
    assert (await move("general")).status_code == 200
    body = {"user_id": str((await _user(db, tenant, "employee")).id), "division_id": str(org["mine"].id), "hire_date": "2025-01-01", "position_id": str(seats["theirs"].id)}
    assert _refused(await client.post("/api/employees", json=body, headers=mgr), FENCE)


async def test_pay_in_the_timeline_follows_the_pay_tab(auth_client, client, db, tenant, org):
    report = org["report"]
    assert (await auth_client.post(f"/api/employees/{report.id}/compensation", json=PAY)).status_code == 201

    def pay_events(r):
        return [e for e in r.json() if e["event_type"] == "compensation_change"]

    path = f"/api/employees/{report.id}/events"
    assert pay_events(await client.get(path, headers=_headers(org["mgr_user"])))
    assert pay_events(await client.get(path, headers=_headers(report.user)))
    # hr reads the whole record at ``view`` but was never given pay.
    hr = await client.get(path, headers=_headers(org["hr_user"]))
    assert hr.status_code == 200 and not pay_events(hr)
    typed = await client.get(f"{path}?type=compensation_change", headers=_headers(org["hr_user"]))
    assert typed.json() == []


async def test_payroll_analytics_follow_the_pay_tab(auth_client, client, org):
    mgr, hr = _headers(org["mgr_user"]), _headers(org["hr_user"])
    assert (await client.get("/api/analytics/compensation", headers=mgr)).status_code == 200
    assert _refused(await client.get("/api/analytics/compensation", headers=hr))
    await _save(auth_client, levels={"employees": {"manager": "view", "hr": "manage"}})
    assert _refused(await client.get("/api/analytics/compensation", headers=mgr))
    assert (await client.get("/api/analytics/compensation", headers=hr)).status_code == 200


async def test_a_pay_row_outside_the_scope_says_nothing_about_its_dates(auth_client, client, org):
    item = await auth_client.post(f"/api/employees/{org['colleague'].id}/compensation", json=PAY)
    bad = {"end_date": "2000-01-01"}
    r = await client.put(f"/api/employees/{org['colleague'].id}/compensation/{item.json()['id']}", json=bad, headers=_headers(org["mgr_user"]))
    assert _refused(r, FENCE)
