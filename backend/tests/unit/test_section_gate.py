"""HRP-820: one global dependency narrows every section route by the
tenant's matrix - and nothing else changes: personal paths, the allowlist,
token links and platform admins pass."""

import inspect

import pytest
from app.core.sections import gated_section, section_for_path
from app.main import app
from fastapi.routing import APIRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.unit.test_work_containers import _user_with_role

URL = "/api/settings/section-access"


async def _headers(db, tenant, code):
    _, token = await _user_with_role(db, tenant, code)
    return {"Authorization": f"Bearer {token}"}


async def _save(auth_client, *, hidden=(), levels=None, headers=None):
    matrix = (await auth_client.get(URL, headers=headers)).json()
    for s in matrix["sections"]:
        s["hidden"] = s["code"] in hidden
        s["levels"].update((levels or {}).get(s["code"], {}))
    r = await auth_client.put(URL, json={"sections": [{"code": s["code"], "hidden": s["hidden"], "levels": s["levels"]} for s in matrix["sections"]]}, headers=headers)
    assert r.status_code == 200, r.text


def test_gate_is_a_global_dependency():
    names = {getattr(d.call, "__name__", "") for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/mass-exams" for d in r.dependant.dependencies}
    assert "section_gate" in names


def test_token_links_and_personal_paths_are_not_gated():
    by_path = {(r.path, tuple(sorted(r.methods))): r for r in app.routes if isinstance(r, APIRoute)}
    assert gated_section(by_path[("/api/review/{token}", ("GET",))]) is None
    assert gated_section(by_path[("/api/reports/share/{token}", ("GET",))]) is None
    assert gated_section(by_path[("/api/employees/me", ("GET",))]) is None
    # /auth is outside the matrix entirely (ALLOWLIST_PREFIXES), a
    # different reason to skip than the token-link/personal-path set below.
    assert gated_section(by_path[("/api/auth/me", ("GET",))]) is None
    # HRP-823: one's own exams left the matrix with the section's
    # translation; the section itself is /api/mass-exams.
    assert gated_section(by_path[("/api/exams", ("GET",))]) is None
    assert gated_section(by_path[("/api/mass-exams", ("GET",))]).code == "exams"


def test_the_gate_skips_exactly_the_known_token_links_and_personal_paths():
    # IMPORTANT 2 (review): pin the whole skip-set inside the matrix, not
    # a handful of spot picks - a future route that resolves its user
    # through anything other than get_current_user must turn this red
    # instead of silently dropping out of the matrix with no test noticing.
    skipped = {
        r.path
        for r in app.routes
        if isinstance(r, APIRoute)
        and section_for_path(r.path) is not None
        and gated_section(r) is None
    }
    assert skipped == {
        "/api/employees/me",
        "/api/analytics/my-loop",
        "/api/analytics/my-loop/ai-summary",
        "/api/exams",
        "/api/exams/{exam_id}/questions",
        "/api/exams/{exam_id}/review",
        "/api/exams/{exam_id}/answer",
        "/api/exams/{exam_id}/finish",
        "/api/review/{token}",
        "/api/review/{token}/submit",
        "/api/reports/share/{token}",
        "/api/recruitment/invite/{token}",
        "/api/recruitment/invite/{token}/assessments",
        "/api/recruitment/invite/{token}/canvas",
        "/api/recruitment/invite/{token}/context",
        "/api/recruitment/consent/{token}",
        "/api/recruitment/consent/{token}/sign",
        "/api/recruitment/consent/{token}/revoke",
        # HRP-827: catalogue reads other sections are built on (their GET
        # only - the writes on the same paths stay gated).
        "/api/competence-tree",
        "/api/competences/{competence_id}",
        "/api/competences/{competence_id}/indicators-by-level",
        "/api/skill-levels",
        "/api/dictionaries/{item_type}",
        "/api/dictionaries/items/{item_id}",
        # HRP-828: the org chart and the job catalogue behind the pickers.
        "/api/company",
        "/api/onboarding/status",
        "/api/divisions",
        "/api/divisions/scope",
        "/api/divisions/{division_id}",
        "/api/positions",
        "/api/positions/{position_id}",
        "/api/specializations",
        "/api/specializations/{spec_id}/grades",
        "/api/grade-system/specializations/{specialization_id}",
        "/api/grade-system/specializations/{specialization_id}/grades",
        # HRP-829: the people pickers and the card other sections open.
        "/api/employees",
        "/api/employees/{employee_id}",
        # HRP-831: the role list behind the invitation form.
        "/api/roles",
    }


async def test_hidden_section_answers_403_on_every_route_for_everyone(auth_client, client, db, tenant):
    await _save(auth_client, hidden=["exams"])
    employee = await _headers(db, tenant, "employee")
    r = await client.get("/api/mass-exams", headers=employee)
    assert r.status_code == 403 and r.json()["code"] == "auth_insufficient_permissions"
    # ... the admin who hid it included.
    assert (await auth_client.get("/api/mass-exams")).status_code == 403
    # HRP-823: an exam already assigned is still the taker's to finish.
    assert (await client.get("/api/exams", headers=employee)).status_code == 200


async def test_extra_spaces_after_bearer_do_not_open_a_hidden_section(auth_client, client, db, tenant):
    # Review 01.10: the gate split the header on the first space and kept
    # the rest unstripped, so ``Bearer  <jwt>`` failed its signature check
    # in the gate (and passed) while the route's OAuth2 scheme stripped it
    # and authenticated - the matrix stopped applying.
    await _save(auth_client, hidden=["talent-market"])
    _, token = await _user_with_role(db, tenant, "employee")
    r = await client.post("/api/talent-market/search", json={}, headers={"Authorization": f"Bearer   {token}"})
    assert r.status_code == 403 and r.json()["code"] == "auth_insufficient_permissions"


async def test_none_for_a_role_closes_the_section_but_not_the_personal_paths(auth_client, client, db, tenant):
    await _save(auth_client, levels={"employees": {"hr": "none"}})
    hr = await _headers(db, tenant, "hr")
    assert (await client.get("/api/employees/available-users", headers=hr)).status_code == 403
    assert (await client.get("/api/employees/me", headers=hr)).status_code != 403
    assert (await client.get("/api/auth/me", headers=hr)).status_code == 200
    assert (await auth_client.get("/api/employees/available-users")).status_code == 200


async def test_none_on_employees_closes_a_colleagues_loop_but_not_ones_own(auth_client, client, db, tenant):
    # Review 01.10: /analytics/my-loop is a personal path the gate skips,
    # yet with ?employee_id= it reads a colleague's assessments and plans -
    # the card's sub-resource, which employees=none closes.
    from datetime import date

    from app.modules.employee.models import Employee

    await _save(auth_client, levels={"employees": {"hr": "none"}})
    hr, token = await _user_with_role(db, tenant, "hr")
    colleague, _ = await _user_with_role(db, tenant, "employee")
    mine = Employee(user_id=hr.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1), status="active")
    theirs = Employee(user_id=colleague.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1), status="active")
    db.add_all([mine, theirs])
    await db.commit()
    h = {"Authorization": f"Bearer {token}"}
    r = await client.get(f"/api/analytics/my-loop?employee_id={theirs.id}", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "auth_insufficient_permissions"
    assert (await client.get(f"/api/analytics/my-loop?employee_id={mine.id}", headers=h)).status_code == 200
    assert (await client.get("/api/analytics/my-loop", headers=h)).status_code == 200


async def test_default_none_closes_what_the_role_never_saw_in_the_menu(client, db, tenant):
    employee = await _headers(db, tenant, "employee")
    assert (await client.get("/api/analytics/division-matrix", headers=employee)).status_code == 403
    assert (await client.get("/api/analytics/my-loop", headers=employee)).status_code != 403


async def test_anonymous_and_token_links_are_untouched(auth_client, client):
    await _save(auth_client, hidden=["assessments", "exams"])
    # client and auth_client are the same httpx client (conftest.py sets
    # Authorization on it in place); drop it to go anonymous again, same as
    # test_invitation_preview.py.
    client.headers.pop("Authorization", None)
    assert (await client.get("/api/exams")).status_code == 401
    # Not 401 and not 403 - the gate did not touch it: an unknown external
    # review token answers 404 (external_review_link_invalid), same as
    # before the gate existed.
    assert (await client.get("/api/review/no-such-token")).status_code == 404


def test_websocket_handshake_survives_the_gate():
    # CRITICAL 1 (review): section_gate used to take a plain Request, which
    # FastAPI's dependency solver only fills for HTTP connections - every
    # /api/ws handshake died in dependency resolution with `TypeError:
    # section_gate() missing 1 required positional argument: 'request'`
    # before the route's own auth ever ran. Confirmed RED on the pre-fix
    # signature: tests/unit/test_websocket.py had 5 tests fail with that
    # exact TypeError (see task-5-report.md's Fix round 2 section for the
    # captured output); all pass again on this fix.
    #
    # An invalid token fails to decode before any DB query, so this needs
    # no get_db override: reaching the route's own 1008 rejection - not a
    # crash inside the gate - is the proof the handshake survives it.
    with (
        TestClient(app, raise_server_exceptions=False) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/api/ws?token=not-a-real-jwt"),
    ):
        pass


async def test_garbage_bearer_token_is_401_not_403(client):
    # Rider 7 (review): a token that fails to decode makes
    # resolve_user_from_access_token return None, so the gate no-ops (its
    # own comment: "the route's own guard answers 401") and get_current_user
    # is the one that rejects it - never a 403 or a 500 from the gate itself.
    r = await client.get(
        "/api/exams", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert r.status_code == 401


async def test_platform_admin_passes_a_hidden_section(auth_client, client, db, tenant):
    await _save(auth_client, hidden=["exams"])
    assert (await client.get("/api/mass-exams", headers=await _headers(db, tenant, "platform_admin"))).status_code == 200


async def test_coverage_dynamics_do_not_gate(client, db, tenant):
    # HRP-820 fix round 1: the gate reads the matrix only. An employee who
    # reads no process gets the route's own semantics - an empty list, a
    # 404 for a container that is not theirs to see - never a blanket 403
    # from the gate just because Coverage's process dynamics are cold.
    employee = await _headers(db, tenant, "employee")
    listed = await client.get("/api/work/containers", headers=employee)
    assert listed.status_code == 200 and listed.json()["items"] == []
    got = await client.get(
        "/api/work/containers/00000000-0000-0000-0000-000000000000", headers=employee
    )
    assert got.status_code == 404
    me = await client.get("/api/auth/me", headers=employee)
    assert "coverage" not in me.json()["sections"]


async def test_matrix_narrowing_closes_coverage(auth_client, client, db, tenant):
    await _save(auth_client, levels={"coverage": {"employee": "none"}})
    employee = await _headers(db, tenant, "employee")
    assert (await client.get("/api/work/containers", headers=employee)).status_code == 403

    await _save(auth_client, hidden=["coverage"])
    assert (await auth_client.get("/api/work/containers")).status_code == 403



def _section_checks(dependant):
    for dep in dependant.dependencies:
        if getattr(dep.call, "__name__", "") == "section_checker":
            bound = inspect.getclosurevars(dep.call).nonlocals
            yield bound["section"].code, bound["level"]
        yield from _section_checks(dep)


def test_no_route_asks_again_what_the_gate_answers():
    # HRP-1018: a route's own ``require_section`` on the section the gate
    # narrows it by repeats the gate when the gate denies the same - ``view``
    # anywhere, ``manage`` on a write outside a self-guarded section.
    repeated = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or (section := gated_section(route)) is None:
            continue
        writes = bool(route.methods - {"GET", "HEAD", "OPTIONS"})
        for code, level in _section_checks(route.dependant):
            if code == section.code and (
                level == "view" or (writes and not section.self_guarded)
            ):
                repeated.append(f"{sorted(route.methods)} {route.path}")
    assert repeated == []


# HRP-1018: the sections whose routes leave ``view`` and the writes to the
# gate - a role at ``view`` cannot write, at ``none`` cannot read. Roles
# answers its one read itself (a shared read, see test_settings_section_access),
# dictionaries' reads are shared.
GATED_ONLY = [
    ("import", "hr", "/api/import/jobs", ("POST", "/api/import/employees")),
    ("invitations", "hr", "/api/invitations", ("POST", "/api/invitations")),
    ("roles", "hr", None, ("POST", "/api/roles")),
    (
        "ai-settings",
        "hr",
        "/api/admin/ai-settings",
        ("PATCH", "/api/admin/ai-settings"),
    ),
    ("dictionaries", "hr", None, ("POST", "/api/dictionaries/grade")),
    (
        "exams",
        "manager",
        "/api/mass-exams/import-template",
        ("POST", "/api/mass-exams"),
    ),
    (
        "analytics",
        "hr",
        "/api/analytics/assessments",
        ("POST", "/api/analytics/export/assessments"),
    ),
]


@pytest.mark.parametrize(
    ("code", "role", "read", "write"), GATED_ONLY, ids=[g[0] for g in GATED_ONLY]
)
async def test_the_gate_refuses_writes_at_view_and_reads_at_none(
    auth_client, client, db, tenant, code, role, read, write
):
    headers = await _headers(db, tenant, role)
    await _save(auth_client, levels={code: {role: "view"}})
    r = await client.request(*write, json={}, headers=headers)
    assert (
        r.status_code == 403 and r.json()["code"] == "auth_insufficient_permissions"
    ), r.text
    if read is not None:
        await _save(auth_client, levels={code: {role: "none"}})
        r = await client.get(read, headers=headers)
        assert (
            r.status_code == 403 and r.json()["code"] == "auth_insufficient_permissions"
        ), r.text
