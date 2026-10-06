"""HRP-830: the recruitment section on the tenant's access matrix.

``manage`` runs hiring for the whole workspace - vacancies, candidates,
interviews, AI analyses, consents, reports, evaluation and hiring rounds -
and sees all of it. ``view`` reads the vacancies in the caller's scope.
Two roles keep a piece at ``view`` (Maxim, 25.09): ``hiring_manager``
evaluates, ``manager`` runs hiring rounds, both in their scope. The tenant
settings stay the admin role's, GDPR and the audit log admin's and hr's.
``hiring_manager`` defaults to ``view``; ``hr`` keeps ``manage``.
"""

import inspect
import uuid
from datetime import date

import pytest_asyncio
from app.core.sections import gated_section, section_for_path
from app.main import app
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.recruitment import notifications
from app.modules.recruitment import scope as recruitment_scope
from app.modules.recruitment.models import Candidate, CandidateVacancy, Vacancy
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
    await _save(auth_client, levels={"recruitment": {"employee": "view"}})
    h = _headers(hiring["emp"])
    listed = await client.get("/api/recruitment/vacancies", headers=h)
    assert listed.status_code == 200, listed.text
    assert {v["id"] for v in listed.json()["items"]} == {str(hiring["mine"].id)}
    assert (await client.get(f"/api/recruitment/vacancies/{hiring['mine'].id}", headers=h)).status_code == 200
    assert _refused(await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h), SCOPE)
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=h))
    # Evaluation is the hiring_manager role's at ``view``, not the level's.
    assert _refused(await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}", json={"manager_score": 5}, headers=h))


async def test_manage_runs_hiring_for_the_whole_workspace(auth_client, client, hiring):
    await _save(auth_client, levels={"recruitment": {"employee": "manage"}})
    h = _headers(hiring["emp"])
    assert (await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h)).status_code == 200
    created = await client.post("/api/recruitment/vacancies", json={"title": "Raised"}, headers=h)
    assert created.status_code == 201, created.text
    patched = await client.patch(f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}", json={"manager_score": 5}, headers=h)
    assert patched.status_code == 200, patched.text


async def test_a_recruiter_lowered_to_view_is_scoped_and_read_only(auth_client, client, db, tenant, hiring):
    await _save(auth_client, levels={"recruitment": {"recruiter": "view"}})
    h = _headers(await _user(db, tenant, "recruiter"))
    assert (await client.get("/api/recruitment/vacancies", headers=h)).json()["items"] == []
    assert _refused(await client.get(f"/api/recruitment/vacancies/{hiring['theirs'].id}", headers=h), SCOPE)
    assert _refused(await client.post("/api/recruitment/vacancies", json={"title": "X"}, headers=h))


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

    async def job_profile(u):
        return (await client.get("/api/auth/me", headers=_headers(u))).json()["can_view_job_profile"]

    assert await job_profile(recruiter) is True
    assert await job_profile(employee) is False
    await _save(auth_client, levels={"recruitment": {"employee": "view", "recruiter": "none"}})
    assert await job_profile(recruiter) is False
    assert await job_profile(employee) is True


async def test_fan_out_follows_who_runs_hiring(auth_client, db, tenant):
    # Events with no named recipient (a consent signed after its requester
    # left, a failed AI task) go to whoever holds ``manage`` on recruitment.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tests.conftest import TEST_DB_URL

    recruiter, employee = await _user(db, tenant, "recruiter"), await _user(db, tenant, "employee")
    assert recruiter.id in {u.id for u in await notifications._async_resolve_admins(db, tenant.id)}
    await _save(auth_client, levels={"recruitment": {"recruiter": "none", "employee": "manage"}})
    reached = {u.id for u in await notifications._async_resolve_admins(db, tenant.id)}
    assert employee.id in reached and recruiter.id not in reached
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
        if name in ("section_checker", "section_or_role_checker", "role_checker", "admin_checker"):
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
    return False


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
    "/api/v1/assessment-rounds/{round_id}/aggregate",
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
        roles = {env["role"] for name, env in _guards(r.dependant) if name == "section_or_role_checker"}
        if not roles & {"hiring_manager", "manager"} or r.path in _TENANT_SETTINGS_READS:
            continue
        named = {k for k in keyed if f"{{{k}}}" in r.path}
        covered = {guards[n] for n in _dependency_names(r.dependant) if n in guards}
        if not named or not named <= covered:
            unscoped.append(f"{sorted(r.methods)} {r.path}: {sorted(named - covered) or 'no key'}")
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
