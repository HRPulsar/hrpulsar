"""HRP-828: the company section on the tenant's access matrix.

``manage`` on ``company`` shapes the org chart - divisions, their
specialization mapping, positions, AI-drafted positions - inside the
caller's subtree, admin-level roles the workspace. ``hr`` defaults to
``view`` (Maxim, 24.09): it never wrote either, and the specialization
ladder and matrices it does write stay an admin/hr asset by role. The grade
system, the company profile, deletes and the matrix itself stay the admin
role's. The pickers every other section reads answer whatever the matrix
says.
"""

import inspect
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from app.core.sections import section_for_path
from app.main import app
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from fastapi.routing import APIRoute

from tests.unit.test_catalogue_and_position_scope import (  # noqa: F401 - pytest fixture
    _headers,
    _user,
    catalogue,
)
from tests.unit.test_section_gate import _save

GATE = "auth_insufficient_permissions"
FENCE = "outside_division_scope"


@pytest.fixture
def chart(catalogue):  # noqa: F811 - the imported fixture, requested by name
    """Two divisions with a position each, a manager of one, an hr and an admin."""
    return catalogue


def _refused(r, code=GATE):
    return r.status_code == 403 and r.json().get("code", r.json().get("error_code")) == code


def _position(c, side="mine"):
    return {"title": f"P-{uuid.uuid4().hex[:6]}", "division_id": str(c[f"{side}_division"].id)}


async def _rows(client, h):
    return (await client.get("/api/positions?limit=200", headers=h)).json()["items"]


async def _spec_and_grade(auth_client):
    spec = await auth_client.post("/api/dictionaries/specialization", json={"title": f"S-{uuid.uuid4().hex[:6]}"})
    grade = await auth_client.post("/api/dictionaries/grade", json={"title": f"G-{uuid.uuid4().hex[:6]}"})
    return spec.json()["id"], grade.json()["id"]


async def test_the_default_matrix_keeps_todays_answers(auth_client, client, chart):
    mgr, hr = _headers(chart["mgr_user"]), _headers(chart["hr_user"])
    spec, grade = await _spec_and_grade(auth_client)

    # The division head shapes their own subtree, as before.
    assert (await client.post("/api/positions", json=_position(chart), headers=mgr)).status_code == 201
    mine = chart["mine_division"].id
    assert (await client.put(f"/api/divisions/{mine}", json={"name": "Renamed"}, headers=mgr)).status_code == 200

    # hr reads the chart at ``view`` and writes none of it...
    assert (await client.get("/api/auth/me", headers=hr)).json()["sections"]["company"] == "view"
    assert _refused(await client.post("/api/positions", json=_position(chart), headers=hr))
    assert _refused(await client.post("/api/divisions", json={"name": "Root"}, headers=hr))
    assert _refused(await client.put(f"/api/divisions/{mine}", json={"name": "X"}, headers=hr))
    assert _refused(await client.post("/api/ai/generate-positions", headers=hr))
    assert not any(r["can_manage"] for r in await _rows(client, hr))
    # ...but keeps the specialization ladder, which the manager never had.
    added = await client.post(f"/api/specializations/{spec}/grades", json={"grade_ids": [grade]}, headers=hr)
    assert added.status_code == 201, added.text
    assert _refused(await client.post(f"/api/specializations/{spec}/grades", json={"grade_ids": [grade]}, headers=mgr))


async def test_handing_the_section_to_hr_opens_the_whole_chart(auth_client, client, chart):
    hr = _headers(chart["hr_user"])
    await _save(auth_client, levels={"company": {"hr": "manage"}})

    # An admin-level role at ``manage`` shapes the workspace, root included.
    created = await client.post("/api/divisions", json={"name": f"Root {uuid.uuid4().hex[:4]}"}, headers=hr)
    assert created.status_code == 201, created.text
    assert (await client.post("/api/positions", json=_position(chart, "theirs"), headers=hr)).status_code == 201
    assert all(r["can_manage"] for r in await _rows(client, hr))
    # The raise hands the chart, not what only the admin role did.
    assert _refused(await client.delete(f"/api/divisions/{created.json()['id']}", headers=hr))
    assert _refused(await client.delete(f"/api/positions/{chart['theirs_position'].id}", headers=hr))
    assert _refused(await client.post("/api/grade-system/chains", json={}, headers=hr))
    assert _refused(await client.put("/api/company", json={}, headers=hr))
    assert _refused(await client.get("/api/settings/section-access", headers=hr))


async def test_a_raised_role_writes_only_inside_its_subtree(auth_client, client, db, tenant, chart):
    recruiter = await _user(db, tenant, "recruiter")
    emp = Employee(user_id=recruiter.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    own = Division(tenant_id=tenant.id, name=f"Own {uuid.uuid4().hex[:4]}", manager_id=emp.id)
    db.add(own)
    await db.commit()
    h = _headers(recruiter)
    body = {"title": "Sourcer", "division_id": str(own.id)}

    assert _refused(await client.post("/api/positions", json=body, headers=h))
    await _save(auth_client, levels={"company": {"recruiter": "manage"}})

    assert (await client.post("/api/positions", json=body, headers=h)).status_code == 201
    assert _refused(await client.post("/api/positions", json=_position(chart, "theirs"), headers=h), FENCE)
    assert _refused(await client.post("/api/divisions", json={"name": "Root"}, headers=h), FENCE)
    child = await client.post("/api/divisions", json={"name": "Child", "parent_id": str(own.id)}, headers=h)
    assert child.status_code == 201, child.text


async def test_ai_positions_are_refused_before_billing_without_a_subtree(auth_client, client, db, tenant):
    # A raised role heading nothing has nowhere to file a draft: the run
    # would be charged and save nothing.
    recruiter = _headers(await _user(db, tenant, "recruiter"))
    await _save(auth_client, levels={"company": {"recruiter": "manage"}})
    assert _refused(await client.post("/api/ai/generate-positions", headers=recruiter))


@patch("app.modules.ai.tasks.generate_positions_task")
async def test_ai_positions_are_the_workspace_roles_only(mock_task, auth_client, client, chart):
    # HRP-631 (QA 06.10): a division head at ``manage`` authors positions in
    # their subtree by hand but never runs the workspace-wide generator...
    mock_task.apply_async.return_value = MagicMock(id="task-pos")
    mgr, hr = _headers(chart["mgr_user"]), _headers(chart["hr_user"])
    assert (await client.get("/api/auth/me", headers=mgr)).json()["sections"]["company"] == "manage"
    assert _refused(await client.post("/api/ai/generate-positions", headers=mgr))
    mock_task.apply_async.assert_not_called()
    # ...while hr raised to ``manage`` keeps it, and the admin as before.
    await _save(auth_client, levels={"company": {"hr": "manage"}})
    assert (await client.post("/api/ai/generate-positions", headers=hr)).status_code == 202
    assert (await auth_client.post("/api/ai/generate-positions")).status_code == 202


async def test_lowering_the_manager_closes_the_writes_and_the_buttons(auth_client, client, chart):
    mgr = _headers(chart["mgr_user"])
    await _save(auth_client, levels={"company": {"manager": "view"}})

    mine = chart["mine_division"].id
    assert _refused(await client.post("/api/positions", json=_position(chart), headers=mgr))
    assert _refused(await client.put(f"/api/positions/{chart['mine_position'].id}", json={"title": "X"}, headers=mgr))
    assert _refused(await client.put(f"/api/divisions/{mine}", json={"name": "X"}, headers=mgr))
    assert _refused(await client.post("/api/ai/generate-positions", headers=mgr))
    assert not any(r["can_manage"] for r in await _rows(client, mgr))
    one = await client.get(f"/api/positions/{chart['mine_position'].id}", headers=mgr)
    assert one.json()["can_manage"] is False


async def test_closing_the_section_keeps_the_shared_reads(auth_client, client, db, tenant, chart):
    spec, _ = await _spec_and_grade(auth_client)
    employee = _headers(await _user(db, tenant, "employee"))
    await _save(auth_client, levels={"company": {"employee": "none"}})

    assert "company" not in (await client.get("/api/auth/me", headers=employee)).json()["sections"]
    pos, div = chart["mine_position"].id, chart["mine_division"].id
    # The section's own pages close...
    for path in (
        f"/api/positions/{pos}/occupancy",
        f"/api/specializations/{spec}",
        f"/api/divisions/{div}/specializations",
        "/api/settings/company-profile",
    ):
        assert _refused(await client.get(path, headers=employee)), path
    # ...the pickers every other section is built on do not.
    for path in (
        "/api/company",
        "/api/onboarding/status",
        "/api/divisions",
        "/api/divisions/scope",
        f"/api/divisions/{div}",
        "/api/positions",
        f"/api/positions/{pos}",
        "/api/specializations",
        f"/api/specializations/{spec}/grades",
        f"/api/grade-system/specializations/{spec}",
        f"/api/grade-system/specializations/{spec}/grades",
    ):
        r = await client.get(path, headers=employee)
        assert r.status_code == 200, (path, r.text)


async def test_a_plain_employee_reads_the_pickers_but_not_the_details(auth_client, client, db, tenant, chart):
    # HRP-622: the profile, positions and specializations tabs are not a
    # plain employee's - their reads 403 at the default ``view``, the
    # pickers stay open, and a raise to ``manage`` hands the tabs back.
    spec, _ = await _spec_and_grade(auth_client)
    employee = _headers(await _user(db, tenant, "employee"))
    hiring = _headers(await _user(db, tenant, "hiring_manager"))
    pos = chart["mine_position"].id
    details = (
        "/api/settings/company-profile",
        f"/api/positions/{pos}/employees",
        f"/api/positions/{pos}/occupancy",
        f"/api/positions/{pos}/matrix-status",
        f"/api/positions/{pos}/competences",
        f"/api/specializations/{spec}",
        f"/api/specializations/{spec}/positions",
        f"/api/specializations/{spec}/employees",
        f"/api/specializations/{spec}/matrix-bulk",
    )
    for path in details:
        assert _refused(await client.get(path, headers=employee)), path
        # Any role on top of ``employee`` keeps the tabs at ``view``.
        r = await client.get(path, headers=hiring)
        assert r.status_code == 200, (path, r.text)
    for path in ("/api/positions", f"/api/positions/{pos}", "/api/specializations"):
        r = await client.get(path, headers=employee)
        assert r.status_code == 200, (path, r.text)

    await _save(auth_client, levels={"company": {"employee": "manage"}})
    for path in details:
        r = await client.get(path, headers=employee)
        assert r.status_code == 200, (path, r.text)


async def test_platform_admin_shapes_the_chart_but_does_not_delete(client, db, tenant):
    # The matrix never gates the platform role; deletes stay the admin role's.
    platform = _headers(await _user(db, tenant, "platform_admin"))
    created = await client.post("/api/divisions", json={"name": "Platform"}, headers=platform)
    assert created.status_code == 201, created.text
    assert _refused(await client.delete(f"/api/divisions/{created.json()['id']}", headers=platform))


def _guards(dependant) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__name__", "")
        if name in ("section_checker", "role_checker"):
            out.append((name, inspect.getclosurevars(dep.call).nonlocals))
        out.extend(_guards(dep))
    return out


def _asks_for_itself(name: str, env: dict) -> bool:
    if name == "section_checker":
        return env["section"].code == "company" and env["level"] == "manage"
    return set(env["role_codes"]) <= {"admin", "hr"}


def test_every_write_in_the_section_asks_for_itself():
    # ``company`` is self-guarded: the gate lets ``view`` through on writes,
    # because hr writes the ladder there. A write route must ask ``manage``
    # on company or an admin/hr role itself, or it opens to every ``view``
    # cell - a bare ``require_section("company")`` asks for ``view`` only.
    bare = [
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.methods - {"GET", "HEAD", "OPTIONS"}
        and (s := section_for_path(r.path)) is not None
        and s.code == "company"
        and not any(_asks_for_itself(*g) for g in _guards(r.dependant))
    ]
    assert not bare, bare
