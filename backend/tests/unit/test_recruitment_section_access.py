"""HRP-830: the recruitment section on the tenant's access matrix.

``manage`` runs hiring - vacancies, candidates, interviews, AI analyses,
consents, reports, evaluation and hiring rounds - in the caller's scope,
``view`` reads it. The scope is the whole workspace for the admin level and
the recruiter, their divisions for a manager, the vacancies they are named
on for a hiring manager - at ``manage`` too (REDO, QA 14.10).
Two roles keep a piece at ``view`` (Maxim, 25.09): ``hiring_manager``
evaluates, ``manager`` runs hiring rounds, both in their scope. The tenant
settings stay the admin role's, GDPR and the audit log admin's and hr's.
``hiring_manager`` defaults to ``view``; ``hr`` keeps ``manage``.
"""

import inspect
import uuid
from datetime import date

import pytest
import pytest_asyncio
from app.core.sections import gated_section, section_for_path
from app.main import app
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.recruitment import notifications
from app.modules.recruitment import scope as recruitment_scope
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    Vacancy,
)
from app.modules.talent_market.models import TalentCandidate, TalentCard
from fastapi.routing import APIRoute

from tests.unit.test_recruitment_manager_scope import _headers, _user
from tests.unit.test_section_gate import _save

GATE = "auth_insufficient_permissions"
SCOPE = "outside_recruitment_scope"


def _refused(r, code=GATE):
    return r.status_code == 403 and r.json().get("code", r.json().get("error_code")) == code


async def _opening(db, tenant, division, **people):
    vac = Vacancy(tenant_id=tenant.id, title=f"Role {uuid.uuid4().hex[:4]}", division_id=division.id, **people)
    cand = Candidate(tenant_id=tenant.id, full_name="C", email=f"c-{uuid.uuid4().hex[:6]}@example.com")
    db.add_all([vac, cand])
    await db.commit()
    cv = CandidateVacancy(tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vac.id)
    db.add(cv)
    await db.commit()
    return vac, cv


@pytest_asyncio.fixture
async def hiring(db, tenant):
    """A manager heading ``mine``; an employee and a hiring manager named on
    the vacancy there; a neighbouring department's vacancy nobody of them
    is on."""
    mgr_user = await _user(db, tenant, "manager")
    mgr = Employee(user_id=mgr_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(mgr)
    await db.commit()
    mine = Division(tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}", manager_id=mgr.id)
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    emp_user = await _user(db, tenant, "employee")
    hm_user = await _user(db, tenant, "hiring_manager")
    mine_vac, mine_cv = await _opening(db, tenant, mine, hiring_manager_id=hm_user.id, owner_id=emp_user.id)
    theirs_vac, theirs_cv = await _opening(db, tenant, theirs)
    return {
        "mgr": mgr_user,
        "emp": emp_user,
        "hm": hm_user,
        "mine": mine_vac,
        "mine_cv": mine_cv,
        "theirs": theirs_vac,
        "theirs_cv": theirs_cv,
    }


async def test_view_reads_its_own_vacancies_and_writes_nothing(auth_client, client, hiring):
    # The Employee role never reaches recruitment (its ceiling, HRP-830) and a
    # recruiter at ``view`` reads the whole workspace (HRP-830 REDO), so the
    # scoped ``view`` is walked on the manager heading ``mine``.
    await _save(auth_client, levels={"recruitment": {"manager": "view"}})
    h = _headers(hiring["mgr"])
    listed = await client.get("/api/recruitment/vacancies", headers=h)
    assert listed.status_code == 200, listed.text
    assert {v["id"] for v in listed.json()["items"]} == {str(hiring["mine"].id)}
    assert (await client.get(f"/api/recruitment/vacancies/{hiring['mine'].id}", headers=h)).status_code == 200
    assert _refused(await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h), SCOPE)
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=h))
    # Evaluation is the hiring_manager role's at ``view``, not the level's.
    assert _refused(await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}", json={"manager_score": 5}, headers=h))


async def test_the_recruiter_runs_hiring_for_the_whole_workspace(client, db, tenant, hiring):
    # HRP-830 REDO: the whole workspace is the recruiter's (and the admin
    # level's); a manager raised to ``manage`` keeps their subtree - see
    # test_a_manager_at_manage_runs_hiring_on_their_divisions_only.
    h = _headers(await _user(db, tenant, "recruiter"))
    assert (await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h)).status_code == 200
    created = await client.post("/api/recruitment/vacancies", json={"title": "Raised"}, headers=h)
    assert created.status_code == 201, created.text
    patched = await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}", json={"manager_score": 5}, headers=h)
    assert patched.status_code == 200, patched.text


async def test_a_recruiter_at_view_reads_the_whole_workspace(auth_client, client, db, tenant, hiring):
    # HRP-830 REDO (QA 14.10): read-only, but every vacancy of the tenant.
    await _save(auth_client, levels={"recruitment": {"recruiter": "view"}})
    h = _headers(await _user(db, tenant, "recruiter"))
    listed = {v["id"] for v in (await client.get("/api/recruitment/vacancies", headers=h)).json()["items"]}
    assert {str(hiring["mine"].id), str(hiring["theirs"].id)} <= listed
    assert (await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h)).status_code == 200
    cands = (await client.get("/api/recruitment/candidates", headers=h)).json()["items"]
    assert str(hiring["theirs_cv"].candidate_id) in {c["id"] for c in cands}
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=h))
    assert _refused(await client.patch(f"/api/recruitment/vacancies/{hiring['theirs'].id}", json={"title": "X"}, headers=h))


async def test_a_manager_at_manage_runs_hiring_on_their_divisions_only(auth_client, client, db, hiring):
    # HRP-830 REDO (QA 14.10): full management, but only of the vacancies of
    # their own subtree - the neighbouring one answers like at ``view``.
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    h = _headers(hiring["mgr"])
    mine, theirs = hiring["mine"], hiring["theirs"]
    listed = {v["id"] for v in (await client.get("/api/recruitment/vacancies", headers=h)).json()["items"]}
    assert listed == {str(mine.id)}
    assert _refused(await client.get(f"/api/recruitment/vacancies/{theirs.id}", headers=h), SCOPE)
    for method, path, body in (
        ("PUT", f"/api/recruitment/vacancies/{theirs.id}", {"title": "X"}),
        ("POST", f"/api/recruitment/vacancies/{theirs.id}/archive", None),
        ("DELETE", f"/api/recruitment/vacancies/{theirs.id}", None),
        ("POST", f"/api/recruitment/vacancies/{theirs.id}/candidates", {"full_name": "N", "email": "n@example.com"}),
        ("PATCH", f"/api/recruitment/candidates/{hiring['theirs_cv'].candidate_id}", {"notes": "x"}),
        ("DELETE", f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}", None),
        ("PATCH", f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}", {"manager_score": 5}),
        ("POST", f"/api/recruitment/vacancies/{theirs.id}/reports", {}),
        ("POST", "/api/recruitment/candidate-vacancies", {"candidate_id": str(hiring["mine_cv"].candidate_id), "vacancy_id": str(theirs.id)}),
    ):
        r = await client.request(method, path, json=body, headers=h)
        assert _refused(r, SCOPE), f"{method} {path} -> {r.status_code} {r.text}"
    # Their own vacancy takes every write.
    ok = await client.put(f"/api/recruitment/vacancies/{mine.id}", json={"title": "Renamed"}, headers=h)
    assert ok.status_code == 200, ok.text
    # The Division picker is their subtree: inside it a vacancy is created,
    # moved out of it or created outside it is refused (no 500).
    created = await client.post("/api/recruitment/vacancies", json={"title": "Mine", "division_id": str(mine.division_id)}, headers=h)
    assert created.status_code == 201, created.text
    for r in (
        await client.post("/api/recruitment/vacancies", json={"title": "Out", "division_id": str(theirs.division_id)}, headers=h),
        await client.post("/api/recruitment/vacancies", json={"title": "Nowhere"}, headers=h),
        await client.put(f"/api/recruitment/vacancies/{mine.id}", json={"division_id": str(theirs.division_id)}, headers=h),
    ):
        assert _refused(r, SCOPE), r.text
    # A candidate on no vacancy is in nobody's scope: added from a vacancy.
    assert _refused(await client.post("/api/recruitment/candidates", json={"first_name": "A", "last_name": "B"}, headers=h), SCOPE)
    # The workspace's numbers narrow to their vacancies.
    summary = (await client.get("/api/recruitment/analytics/summary", headers=h)).json()
    assert {r["vacancy_id"] for r in summary["top_drop_off"] + summary["top_velocity"]} <= {str(mine.id), created.json()["id"]}


async def test_a_hiring_manager_at_manage_runs_their_named_vacancies(auth_client, client, db, tenant, hiring):
    # HRP-830 REDO (QA 14.10): full management of the vacancies they are the
    # hiring manager of; the Hiring manager picker offers only themselves.
    await _save(auth_client, levels={"recruitment": {"hiring_manager": "manage"}})
    hm = hiring["hm"]
    h = _headers(hm)
    listed = {v["id"] for v in (await client.get("/api/recruitment/vacancies", headers=h)).json()["items"]}
    assert listed == {str(hiring["mine"].id)}
    assert _refused(await client.put(f"/api/recruitment/vacancies/{hiring['theirs'].id}", json={"title": "X"}, headers=h), SCOPE)
    ok = await client.put(f"/api/recruitment/vacancies/{hiring['mine'].id}", json={"title": "Renamed"}, headers=h)
    assert ok.status_code == 200, ok.text
    picker = (await client.get("/api/recruitment/hiring-managers", headers=h)).json()
    assert [o["id"] for o in picker] == [str(hm.id)]
    created = await client.post("/api/recruitment/vacancies", json={"title": "Mine", "hiring_manager_id": str(hm.id)}, headers=h)
    assert created.status_code == 201, created.text
    other = await _user(db, tenant, "hiring_manager")
    for r in (
        await client.post("/api/recruitment/vacancies", json={"title": "Out", "hiring_manager_id": str(other.id)}, headers=h),
        await client.patch(
            f"/api/recruitment/vacancies/{created.json()['id']}",
            json={"hiring_manager_id": str(other.id)},
            headers={**h, "If-Match": created.headers.get("etag") or "*"},
        ),
    ):
        # Not "outside your division": they have none - name yourself.
        assert _refused(r, "vacancy_hiring_manager_must_be_you"), r.text


async def test_the_hiring_manager_evaluates_at_view_in_scope(client, hiring):
    h = _headers(hiring["hm"])
    ok = await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}", json={"manager_score": 5}, headers=h)
    assert ok.status_code == 200, ok.text
    assert _refused(await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}", json={"manager_score": 5}, headers=h), SCOPE)
    # The default moved to ``view``: authoring is ``manage``'s.
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=h))


async def test_the_manager_runs_rounds_at_view_and_closing_the_section_closes_v1(auth_client, client, hiring):
    h = _headers(hiring["mgr"])
    rounds = f"/api/v1/candidate-vacancies/{hiring['mine_cv'].id}/assessment-rounds"
    created = await client.post(rounds, json={"type": "pre_interview"}, headers=h)
    assert created.status_code == 201, created.text
    theirs = f"/api/v1/candidate-vacancies/{hiring['theirs_cv'].id}/assessment-rounds"
    assert _refused(await client.post(theirs, json={"type": "pre_interview"}, headers=h), SCOPE)
    # The vacancy's candidate table reads at ``view`` like the assessment
    # matrix beside it (the role list used to leave the manager out).
    table = f"/api/recruitment/vacancies/{hiring['mine'].id}/candidates/enriched"
    assert (await client.get(table, headers=h)).status_code == 200
    # The rounds live under /v1 next to the public API; until HRP-830 the
    # gate did not see them at all.
    await _save(auth_client, levels={"recruitment": {"manager": "none"}})
    assert _refused(await client.get(rounds, headers=h))
    assert _refused(await client.post(rounds, json={"type": "pre_interview"}, headers=h))


async def test_gdpr_and_the_audit_log_stay_admin_and_hr(auth_client, client, db, tenant):
    hr = _headers(await _user(db, tenant, "hr"))
    recruiter = _headers(await _user(db, tenant, "recruiter"))
    assert (await client.get("/api/recruitment/audit-log", headers=hr)).status_code == 200
    # ``manage`` alone does not reach them...
    assert _refused(await client.get("/api/recruitment/audit-log", headers=recruiter))
    # ...and hr lowered to ``view`` keeps them, while losing the authoring.
    await _save(auth_client, levels={"recruitment": {"hr": "view"}})
    assert (await client.get("/api/recruitment/audit-log", headers=hr)).status_code == 200
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=hr))
    await _save(auth_client, levels={"recruitment": {"hr": "none"}})
    assert _refused(await client.get("/api/recruitment/audit-log", headers=hr))


async def test_the_grade_pair_follows_the_section_not_the_hiring_roles(auth_client, client, db, tenant):
    # HRP-637: hiring reads a position's grade and specialization - a
    # requisition cannot be raised without them.
    employee, recruiter = await _user(db, tenant, "employee"), await _user(db, tenant, "recruiter")
    hm = await _user(db, tenant, "hiring_manager")

    async def job_profile(u):
        return (await client.get("/api/auth/me", headers=_headers(u))).json()["can_view_job_profile"]

    assert await job_profile(recruiter) is True
    assert await job_profile(hm) is True
    assert await job_profile(employee) is False
    await _save(auth_client, levels={"recruitment": {"recruiter": "none", "hiring_manager": "none"}})
    assert await job_profile(recruiter) is False
    assert await job_profile(hm) is False


async def test_fan_out_follows_who_runs_all_of_hiring(auth_client, db, tenant):
    # Events with no named recipient (a consent signed after its requester
    # left, a failed AI task) go to whoever holds ``manage`` on recruitment
    # over the whole workspace (HRP-830 REDO): a manager or hiring manager
    # raised to ``manage`` runs only their own vacancies and would be handed
    # candidates - and links - from vacancies they cannot open.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tests.conftest import TEST_DB_URL

    recruiter, manager = await _user(db, tenant, "recruiter"), await _user(db, tenant, "manager")
    hm, hr = await _user(db, tenant, "hiring_manager"), await _user(db, tenant, "hr")
    assert recruiter.id in {u.id for u in await notifications._async_resolve_admins(db, tenant.id)}
    await _save(
        auth_client, levels={"recruitment": {"recruiter": "none", "manager": "manage", "hiring_manager": "manage"}}
    )
    reached = {u.id for u in await notifications._async_resolve_admins(db, tenant.id)}
    assert hr.id in reached
    assert not reached & {manager.id, hm.id, recruiter.id}
    engine = create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with Session(engine) as sync_db:
            assert {u.id for u in notifications._sync_resolve_admins(sync_db, tenant.id)} == reached
    finally:
        engine.dispose()


def _guards(dependant) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__name__", "")
        if name in (
            "section_checker",
            "section_or_role_checker",
            "role_checker",
            "admin_checker",
            "sheet_owner_checker",
        ):
            out.append((name, inspect.getclosurevars(dep.call).nonlocals))
        out.extend(_guards(dep))
    return out


def _asks_for_itself(name: str, env: dict) -> bool:
    if name == "section_checker":
        return env["section"].code == "recruitment" and env["level"] == "manage"
    if name == "section_or_role_checker":
        return env["role"] in {"hiring_manager", "manager", "admin"}
    if name == "role_checker":
        return set(env["role_codes"]) in ({"admin"}, {"admin", "hr"})
    # HRP-630: ``runs_rounds``, or the sheet's own evaluator at any level.
    return name == "sheet_owner_checker"


# E2E seams, 404 outside ``E2E_MODE``.
_E2E_WRITES = {
    "/api/recruitment/_test/seed-parsed-files",
    "/api/recruitment/_test/seed-verdict",
    "/api/recruitment/_test/candidates/{candidate_id}/consent",
}
# Reads that are running hiring rather than reading it: they answered only
# the roles that write before the matrix, and ``view`` must not open them.
_RESTRICTED_READS = {
    # manage
    "/api/recruitment/consent-templates",
    "/api/recruitment/interviewers",
    "/api/recruitment/hiring-managers",
    "/api/recruitment/candidate-vacancies/{candidate_vacancy_id}/ai-analyses",
    "/api/recruitment/candidate-vacancies/{candidate_vacancy_id}/ai-analyses/topup-eligibility",
    "/api/recruitment/interviews/{interview_id}/upload/{upload_id}",
    "/api/recruitment/reports/{report_id}/shares",
    "/api/recruitment/onboarding",
    "/api/recruitment/analytics/summary",
    "/api/recruitment/settings/branding",
    # manage or the hiring_manager role
    "/api/recruitment/settings/matrix",
    # manage or the manager role
    "/api/v1/assessment-rounds/{round_id}/eligible-evaluators",
    # the admin role / admin and hr
    "/api/recruitment/settings/llm-providers",
    "/api/recruitment/settings/transcription-providers",
    "/api/recruitment/audit-log",
    "/api/recruitment/gdpr-requests",
    "/api/recruitment/settings/retention",
    "/api/recruitment/settings/roles",
}


def test_every_write_in_the_section_asks_for_itself():
    # ``recruitment`` is self-guarded: the gate lets ``view`` through on
    # writes, because the hiring_manager and manager roles evaluate there.
    # Every write route - and the reads that are running hiring - must ask
    # ``manage``, one of those two roles, or the admin / hr role, or it
    # opens to every ``view`` cell.
    routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and (s := section_for_path(r.path)) is not None
        and s.code == "recruitment"
        and gated_section(r) is not None
    ]
    writes = {r.path for r in routes if r.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes >= _E2E_WRITES
    assert {r.path for r in routes if "GET" in r.methods or "HEAD" in r.methods} >= _RESTRICTED_READS
    bare = [
        f"{sorted(r.methods)} {r.path}"
        for r in routes
        if (r.methods - {"GET", "HEAD", "OPTIONS"} and r.path not in _E2E_WRITES)
        or (r.path in _RESTRICTED_READS and r.methods <= {"GET", "HEAD"})
        if not any(_asks_for_itself(*g) for g in _guards(r.dependant))
    ]
    assert not bare, bare


def _scope_guards() -> dict[str, str]:
    """Each ``recruitment.scope`` guard -> the request parameter it keys on."""
    out = {}
    for name, fn in inspect.getmembers(recruitment_scope, inspect.iscoroutinefunction):
        if name.endswith("_scope") and name != "recruitment_scope":
            params = [p for p in inspect.signature(fn).parameters if p not in ("db", "current_user", "scope")]
            if params:
                out[name] = params[0]
    return out


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for dep in dependant.dependencies:
        names.add(getattr(dep.call, "__name__", ""))
        names |= _dependency_names(dep)
    return names


# The tenant's assessment-matrix settings: a workspace setting the hiring
# manager's canvas reads, not a hiring resource.
_TENANT_SETTINGS_READS = {"/api/recruitment/settings/matrix"}


def test_what_a_scoped_caller_reaches_is_scoped():
    # ``evaluates`` and ``runs_rounds`` let the hiring_manager and manager
    # roles through at ``view``, and ``view`` is scoped to their vacancies:
    # every such route must resolve each hiring resource it names back to
    # a vacancy in scope. ``manage`` needs no fence - it sees everything.
    guards = _scope_guards()
    keyed = set(guards.values())
    unscoped = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or (s := section_for_path(r.path)) is None or s.code != "recruitment":
            continue
        guards_of = _guards(r.dependant)
        roles = {env["role"] for name, env in guards_of if name == "section_or_role_checker"}
        opens_view = roles & {"hiring_manager", "manager"} or any(n == "sheet_owner_checker" for n, _ in guards_of)
        if not opens_view or r.path in _TENANT_SETTINGS_READS:
            continue
        named = {k for k in keyed if f"{{{k}}}" in r.path}
        covered = {guards[n] for n in _dependency_names(r.dependant) if n in guards}
        if not named or not named <= covered:
            unscoped.append(f"{sorted(r.methods)} {r.path}: {sorted(named - covered) or 'no key'}")
    assert not unscoped, unscoped


@pytest.mark.parametrize("role", ["manager", "hiring_manager"])
async def test_manage_runs_the_assessment_scales(auth_client, client, db, tenant, hiring, role):
    # HRP-1045 (QA 14.10, FR=ER): Recruitment x {Manager, Recruiter, Hiring
    # manager} = Manage - the assessment scales are full management, whatever
    # the vacancy scope.
    await _save(auth_client, levels={"recruitment": {role: "manage"}})
    h = _headers(hiring["mgr" if role == "manager" else "hm"])
    scale = {
        "name": f"S {uuid.uuid4().hex[:4]}",
        "levels": [{"value": 1, "label": "Low", "weight": 0}, {"value": 2, "label": "High", "weight": 100}],
    }
    created = await client.post("/api/v1/tenants/me/assessment-scales", json=scale, headers=h)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    for method, path, body in (
        ("PATCH", f"/api/v1/assessment-scales/{sid}", {"name": "Renamed"}),
        ("POST", f"/api/v1/assessment-scales/{sid}/archive", None),
        ("DELETE", f"/api/v1/assessment-scales/{sid}", None),
    ):
        r = await client.request(method, path, json=body, headers=h)
        assert r.status_code < 300, f"{method} {path} -> {r.status_code} {r.text}"


async def test_the_interviewer_picker_asks_the_candidacy_scope(auth_client, client, hiring):
    # HRP-830 REDO review: the picker drops the users fenced off a candidacy
    # (HRP-971), so for a foreign candidacy the difference names who applied.
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    h = _headers(hiring["mgr"])
    url = "/api/recruitment/interviewers"
    assert (await client.get(url, headers=h)).status_code == 200
    assert (await client.get(url, params={"candidate_vacancy_id": str(hiring["mine_cv"].id)}, headers=h)).status_code == 200
    r = await client.get(url, params={"candidate_vacancy_id": str(hiring["theirs_cv"].id)}, headers=h)
    assert _refused(r, SCOPE), r.text


@pytest.mark.parametrize("role", ["manager", "hiring_manager"])
async def test_a_scoped_caller_links_only_candidates_in_scope(auth_client, client, db, tenant, hiring, role):
    # HRP-830 REDO (security review, fail-closed): linking a candidate to
    # one's own vacancy hands their card and resumes over, so only one
    # already in scope links - a bare id or an email typed in does not.
    await _save(auth_client, levels={"recruitment": {role: "manage"}})
    me = hiring["mgr" if role == "manager" else "hm"]
    h = _headers(me)
    placement = {"division_id": str(hiring["mine"].division_id)} if role == "manager" else {"hiring_manager_id": str(me.id)}
    second = await client.post("/api/recruitment/vacancies", json={"title": "Second", **placement}, headers=h)
    assert second.status_code == 201, second.text
    outside = hiring["theirs_cv"].candidate_id
    theirs = await db.get(Candidate, outside)
    attach = "/api/recruitment/candidate-vacancies"
    r = await client.post(attach, json={"candidate_id": str(outside), "vacancy_id": second.json()["id"]}, headers=h)
    assert _refused(r, SCOPE), r.text
    inside = {"candidate_id": str(hiring["mine_cv"].candidate_id), "vacancy_id": second.json()["id"]}
    r = await client.post(attach, json=inside, headers=h)
    assert r.status_code == 201, r.text
    manual = f"/api/recruitment/vacancies/{hiring['mine'].id}/candidates"
    for email in ("someone-else@example.com", theirs.email.upper()):
        r = await client.post(manual, json={"full_name": "Dup", "email": email, "link_candidate_id": str(outside)}, headers=h)
        assert _refused(r, SCOPE), r.text
    # Typing their email says it is taken, not whose card it is.
    r = await client.post(manual, json={"full_name": "Dup", "email": theirs.email}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "candidate_email_taken_elsewhere", r.text
    assert str(outside) not in r.text
    # The resume dedup preview flags the duplicate without naming it.
    cf = CandidateFile(
        tenant_id=tenant.id,
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size=1,
        parse_status="completed",
        parsed_data={"contacts": {"email": theirs.email}},
    )
    db.add(cf)
    await db.commit()
    preview = await client.get(
        f"/api/recruitment/vacancies/{hiring['mine'].id}/resumes/dedup-preview", params={"file_ids": str(cf.id)}, headers=h
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()[0]["duplicate_elsewhere"] is True and preview.json()[0]["existing_candidate_id"] is None
    # Nor does an email change onto their address (PATCH of the card).
    r = await client.patch(
        f"/api/recruitment/candidates/{hiring['mine_cv'].candidate_id}", json={"email": theirs.email}, headers=h
    )
    assert r.status_code == 409 and r.json()["code"] == "candidate_email_taken_elsewhere", r.text
    assert str(outside) not in r.text
    # HRP-830 REDO re-review: promoting an employee off the internal
    # shortlist reuses their candidate row - not one out of reach.
    colleague = await _user(db, tenant, "employee")
    col_emp = Employee(user_id=colleague.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    card = TalentCard(
        tenant_id=tenant.id,
        title="Twin",
        card_type="vacancy",
        author_id=me.id,
        start_date=date(2026, 1, 1),
        status="published",
        is_published=True,
    )
    db.add_all([col_emp, card])
    await db.commit()
    db.add(TalentCandidate(card_id=card.id, employee_id=col_emp.id))
    hiring["mine"].talent_card_id = card.id
    elsewhere = Candidate(tenant_id=tenant.id, full_name="Col", email=colleague.email)
    db.add(elsewhere)
    await db.commit()
    db.add(CandidateVacancy(tenant_id=tenant.id, candidate_id=elsewhere.id, vacancy_id=hiring["theirs"].id))
    await db.commit()
    promote = f"/api/recruitment/vacancies/{hiring['mine'].id}/internal-candidates/{col_emp.id}/add"
    r = await client.post(promote, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "candidate_email_taken_elsewhere", r.text
    assert str(elsewhere.id) not in r.text
    # Whoever sees all of hiring keeps the link offer.
    rec = _headers(await _user(db, tenant, "recruiter"))
    promoted = await client.post(promote, headers=rec)
    assert promoted.status_code == 201 and str(elsewhere.id) in promoted.text, promoted.text
    r = await client.post(manual, json={"full_name": "Dup", "email": theirs.email}, headers=rec)
    assert r.status_code == 409 and str(outside) in r.text, r.text
    preview = await client.get(
        f"/api/recruitment/vacancies/{hiring['mine'].id}/resumes/dedup-preview", params={"file_ids": str(cf.id)}, headers=rec
    )
    assert preview.json()[0]["existing_candidate_id"] == str(outside)


async def test_a_scoped_caller_archives_only_a_candidate_wholly_in_scope(auth_client, client, db, hiring):
    # HRP-830 REDO (security review): archiving takes a candidate off every
    # vacancy in the tenant; one also on someone else's vacancy is detached
    # from one's own instead.
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    h = _headers(hiring["mgr"])
    shared = hiring["mine_cv"].candidate_id
    db.add(CandidateVacancy(tenant_id=hiring["mine"].tenant_id, candidate_id=shared, vacancy_id=hiring["theirs"].id))
    await db.commit()
    assert _refused(await client.delete(f"/api/recruitment/candidates/{shared}", headers=h), SCOPE)
    detached = await client.delete(f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}", headers=h)
    assert detached.status_code == 204, detached.text
    own = await client.post(
        f"/api/recruitment/vacancies/{hiring['mine'].id}/candidates", json={"full_name": "Own", "email": "own@example.com"}, headers=h
    )
    assert own.status_code == 201, own.text
    archived = await client.delete(f"/api/recruitment/candidates/{own.json()['id']}", headers=h)
    assert archived.status_code == 204, archived.text


def test_manage_routes_scope_every_hiring_key_in_their_path():
    # HRP-830 REDO: ``manage`` runs hiring inside the caller's scope, so a
    # ``runs_hiring`` route resolves every hiring resource it names - through
    # the path guard (``PATH_SCOPE_KEYS``) or a guard of its own for a key
    # that names two tables (``assessment_id``, ``question_id``).
    guards = _scope_guards()
    keys = set(guards.values()) | set(recruitment_scope.PATH_SCOPE_KEYS)
    unscoped = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or (s := section_for_path(r.path)) is None or s.code != "recruitment":
            continue
        names = _dependency_names(r.dependant)
        if "runs_hiring" not in names:
            continue
        named = {k for k in keys if f"{{{k}}}" in r.path}
        covered = set(recruitment_scope.PATH_SCOPE_KEYS) | {guards[n] for n in names if n in guards}
        if not named <= covered:
            unscoped.append(f"{sorted(r.methods)} {r.path}: {sorted(named - covered)}")
    assert not unscoped, unscoped


async def test_the_hiring_manager_scores_only_their_own_column(auth_client, client, db, tenant, hiring):
    # Another evaluator's cell is ``manage``'s (Maxim, 25.09): the hiring
    # manager edits and reverts their own column only.
    cv = hiring["mine_cv"].id
    competence = str(uuid.uuid4())
    recruiter = await _user(db, tenant, "recruiter")
    theirs = await client.post(
        f"/api/recruitment/candidate-vacancies/{cv}/assessments",
        json={"competence_id": competence, "score": 3},
        headers=_headers(recruiter),
    )
    assert theirs.status_code == 201, theirs.text
    hm = _headers(hiring["hm"])
    assert _refused(await client.patch(f"/api/recruitment/assessments/{theirs.json()['id']}", json={"score": 1}, headers=hm))
    revert = f"/api/recruitment/candidate-vacancies/{cv}/assessments/{competence}/evaluators/{recruiter.id}/revert"
    assert _refused(await client.post(revert, json={"audit_event_id": str(uuid.uuid4())}, headers=hm))
    own = await client.post(
        f"/api/recruitment/candidate-vacancies/{cv}/assessments",
        json={"competence_id": competence, "score": 4},
        headers=hm,
    )
    assert own.status_code == 201, own.text
    patched = await client.patch(f"/api/recruitment/assessments/{own.json()['id']}", json={"score": 5}, headers=hm)
    assert patched.status_code == 200, patched.text
    # ``manage`` edits any column.
    fixed = await client.patch(f"/api/recruitment/assessments/{own.json()['id']}", json={"score": 2}, headers=_headers(recruiter))
    assert fixed.status_code == 200, fixed.text


async def test_a_stage_change_stays_inside_the_vacancys_funnel(client, hiring):
    h = _headers(hiring["hm"])
    moved = await client.patch(
        f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}/status",
        json={"stage_id": str(uuid.uuid4())},
        headers=h,
    )
    assert moved.status_code == 404 and moved.json().get("code", moved.json().get("error_code")) == "stage_not_found_for_vacancy"
