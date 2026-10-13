"""HRP-615: recruitment reads are gated, not merely authenticated.

Before this, 40-odd recruitment GETs hung on bare ``get_current_user``:
any employee of the tenant could list candidates with their contacts,
download resumes and read interview transcripts. The endpoints sat behind
a list of recruitment roles; since HRP-830 they sit behind ``view`` on the
``recruitment`` section, which ``employee`` does not get by default.

Two layers here: request-level tests on the surfaces that actually leak
PII, plus a scanner that fails when a *new* GET lands outside the
section gate — the regression this file exists to prevent.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from app.core.sections import gated_section, section_for_path
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import Role, User, user_roles
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

BACKEND = Path(__file__).resolve().parents[2]
RECRUITMENT = BACKEND / "app" / "modules" / "recruitment"

# Modules the scanner skips wholesale: ``e2e_seed`` is gated by ``E2E_MODE``
# rather than by a role.
SCAN_SKIP_FILES = frozenset({"e2e_seed.py"})

# GET handlers that legitimately carry no authentication at all. Each one
# takes a 256-bit opaque token and sits behind the per-IP limiter in
# ``routers/common.py``: candidate consent, invited-evaluator canvas,
# shared report links. Adding a name here must be a deliberate decision —
# that is the whole point of the list.
UNAUTHENTICATED_GET_ALLOWLIST = frozenset(
    {
        # 256-bit opaque token in the path, per-IP limiter from
        # ``routers/common.py``: candidate consent, invited-evaluator
        # canvas, shared report links.
        "assessments.py::get_invite",
        "assessments.py::get_invite_canvas",
        "assessments.py::get_invite_context",
        "consents.py::get_consent_by_token",
        "reports.py::open_shared_report",
        "manager_assessment_router.py::public_get_endpoint",
        "manager_assessment_router.py::public_resume_preview_endpoint",
        # 404s unless ``E2E_MODE`` is on — the Playwright suite's way into
        # the HRP-186 public flow.
        "manager_assessment_router.py::dev_get_manager_invite_token",
    }
)


async def _user_with_role(db: AsyncSession, tenant, code: str) -> User:
    result = await db.execute(select(Role).where(Role.code == code))
    role = result.scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)

    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=code,
        last_name="Reader",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    # Same dance as the ``user`` conftest fixture: the request handler shares
    # this session, so the identity map would hand it a User with an empty
    # ``roles`` collection unless we re-fetch it eagerly loaded.
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


# Representative slice of the gated surface: list + detail + the three
# download paths that hand over candidate PII verbatim.
GATED_PATHS = [
    "/api/recruitment/vacancies",
    "/api/recruitment/candidates",
    f"/api/recruitment/candidates/{uuid.uuid4()}",
    f"/api/recruitment/candidates/{uuid.uuid4()}/resumes",
    f"/api/recruitment/resumes/{uuid.uuid4()}/download",
    f"/api/recruitment/interviews/{uuid.uuid4()}",
    f"/api/recruitment/interviews/{uuid.uuid4()}/media-url",
    "/api/recruitment/reports",
    f"/api/recruitment/vacancies/{uuid.uuid4()}/candidates",
    "/api/recruitment/settings/scales/active",
]


@pytest_asyncio.fixture
async def employee_reader(db: AsyncSession, tenant):
    return await _user_with_role(db, tenant, "employee")


@pytest_asyncio.fixture
async def recruiter_reader(db: AsyncSession, tenant):
    return await _user_with_role(db, tenant, "recruiter")


class TestRecruitmentReadGate:
    async def test_plain_employee_is_refused(
        self, client: AsyncClient, employee_reader: User
    ):
        headers = _headers(employee_reader)
        for path in GATED_PATHS:
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"

    async def test_recruiter_passes_the_gate(
        self, client: AsyncClient, recruiter_reader: User
    ):
        headers = _headers(recruiter_reader)
        for path in GATED_PATHS:
            resp = await client.get(path, headers=headers)
            # 404 on the random UUIDs is fine — the gate is what we pin.
            assert resp.status_code != 403, f"{path} -> {resp.status_code}"

    async def test_lists_are_readable_for_recruiter(
        self, client: AsyncClient, recruiter_reader: User
    ):
        headers = _headers(recruiter_reader)
        for path in ("/api/recruitment/vacancies", "/api/recruitment/candidates"):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200, f"{path} -> {resp.text}"


# Dependencies that authenticate a recruitment handler (HRP-830): bare
# ``get_current_user`` for reads - the section gate answers ``view`` - and
# the section's own level guards from ``routers/common.py``.
AUTH_DEPENDENCIES = frozenset(
    {"get_current_user", "runs_hiring", "evaluates", "runs_rounds", "reads_hiring_settings"}
)


def _depends(node) -> list:
    args = node.args
    defaults = [None] * (len(args.args) - len(args.defaults))
    defaults += list(args.defaults)
    # Keyword-only params carry dependencies just as well.
    defaults += list(args.kw_defaults)
    return [
        d.args[0]
        for d in defaults
        if isinstance(d, ast.Call) and getattr(d.func, "id", None) == "Depends" and d.args
    ]


def _scan_get_endpoints() -> list[str]:
    """Walk every recruitment router; the GET/HEAD handlers with no auth
    dependency at all."""
    files = sorted((RECRUITMENT / "routers").glob("*.py"))
    files += sorted(RECRUITMENT.glob("*router*.py"))
    unauthenticated: list[str] = []
    for path in files:
        if path.name in SCAN_SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = {
                getattr(dec.func, "attr", None)
                for dec in node.decorator_list
                if isinstance(dec, ast.Call)
            }
            if not methods & {"get", "head"}:
                continue
            guarded = any(
                getattr(d, "id", None) in AUTH_DEPENDENCIES
                or (isinstance(d, ast.Call) and getattr(d.func, "id", "") in ("require_role", "require_admin"))
                for d in _depends(node)
            )
            if not guarded:
                unauthenticated.append(f"{path.name}::{node.name}")
    return unauthenticated


def test_every_authenticated_recruitment_get_is_behind_the_section():
    # HRP-830: a read that authenticates is the section's - ``/v1`` rounds,
    # question sets and scales included, which sat outside the matrix next
    # to the public API until this ticket.
    outside = [
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.endpoint.__module__.startswith("app.modules.recruitment.")
        and not r.endpoint.__module__.endswith("e2e_seed")
        and r.methods <= {"GET", "HEAD"}
        and "get_current_user" in _dependency_names(r.dependant)
        and (
            (section := section_for_path(r.path)) is None
            or section.code != "recruitment"
            or gated_section(r) is None
        )
    ]
    assert not outside, outside


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for dep in dependant.dependencies:
        names.add(getattr(dep.call, "__name__", ""))
        names |= _dependency_names(dep)
    return names


def test_unauthenticated_recruitment_gets_are_declared():
    unauthenticated = _scan_get_endpoints()
    unexpected = sorted(set(unauthenticated) - UNAUTHENTICATED_GET_ALLOWLIST)
    assert not unexpected, (
        "these recruitment GET endpoints take no authentication; if that is "
        "deliberate (opaque token + rate limiter) add them to "
        "UNAUTHENTICATED_GET_ALLOWLIST with a reason: " + ", ".join(unexpected)
    )


# HRP-629: a GET keyed by one of these resources reads someone's hiring
# data, so it must carry the matching scope guard from
# ``recruitment.scope`` — the role gate alone would hand a division head
# the neighbouring department's candidates.
SCOPED_PATH_KEYS = (
    "vacancy_id",
    "candidate_id",
    "cv_id",
    "candidate_vacancy_id",
    "interview_id",
    "resume_id",
    "export_id",
    "report_id",
    "round_id",
    "assessment_id",
)

# Guard name -> the request parameter it reads. Kept here rather than
# imported so a rename in ``scope.py`` has to be mirrored deliberately.
SCOPE_GUARDS = {
    "vacancy_scope": "vacancy_id",
    "candidate_scope": "candidate_id",
    "cv_scope": "cv_id",
    "candidate_vacancy_scope": "candidate_vacancy_id",
    "interview_scope": "interview_id",
    "resume_scope": "resume_id",
    "export_scope": "export_id",
    "report_scope": "report_id",
    "round_scope": "round_id",
    "assessment_scope": "assessment_id",
    "vacancy_query_scope": "vacancy_id",
    "candidate_vacancy_query_scope": "candidate_vacancy_id",
}


def _route_handlers():
    """(file name, handler node, route path) for every recruitment GET/HEAD."""
    files = sorted((RECRUITMENT / "routers").glob("*.py"))
    files += sorted(RECRUITMENT.glob("*router*.py"))
    for path in files:
        if path.name in SCAN_SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = [
                dec
                for dec in node.decorator_list
                if isinstance(dec, ast.Call)
                and getattr(dec.func, "attr", None) in ("get", "head")
                and dec.args
            ]
            if not routes:
                continue
            route_path = "".join(
                part.value
                for part in ast.walk(routes[0].args[0])
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            yield path.name, node, route_path


def _declared_guards(node) -> set[str]:
    args = node.args
    defaults = [None] * (len(args.args) - len(args.defaults))
    defaults += list(args.defaults) + list(args.kw_defaults)
    return {
        d.args[0].id
        for d in defaults
        if isinstance(d, ast.Call)
        and getattr(d.func, "id", None) == "Depends"
        and d.args
        and getattr(d.args[0], "id", None) in SCOPE_GUARDS
    }


# Dependencies a scoped caller gets through (HRP-830): ``view`` on the
# section (bare ``get_current_user`` behind the gate), and the two roles
# that keep a piece at ``view`` - ``hiring_manager`` evaluates,
# ``manager`` runs hiring rounds. ``runs_hiring`` is ``manage``, which sees
# the whole workspace, and ``require_role("admin"[, "hr"])`` is admin-level:
# a route only those reach needs no guard - and stating it this way rather
# than as an allowlist means widening such a route re-arms the check.
SCOPED_REACH = frozenset({"get_current_user", "evaluates", "runs_rounds"})


def _reached_by_scoped_callers(node) -> bool:
    return any(getattr(d, "id", None) in SCOPED_REACH for d in _depends(node))


def test_keyed_recruitment_gets_carry_a_scope_guard():
    """A GET that names a hiring resource must scope it, path or query."""
    unguarded: list[str] = []
    for file_name, node, route_path in _route_handlers():
        params = {a.arg for a in node.args.args + node.args.kwonlyargs}
        in_path = {k for k in SCOPED_PATH_KEYS if f"{{{k}}}" in route_path}
        in_query = {k for k in SCOPED_PATH_KEYS if k in params} - in_path
        if not (in_path or in_query):
            continue
        if not _reached_by_scoped_callers(node):
            continue
        covered = {SCOPE_GUARDS[g] for g in _declared_guards(node)}
        missing = (in_path | in_query) - covered
        if missing:
            unguarded.append(f"{file_name}::{node.name} misses {sorted(missing)}")
    assert not unguarded, (
        "these recruitment GETs name a hiring resource but do not scope it, "
        "so a division manager would read another division's data: "
        + ", ".join(unguarded)
    )


def test_scope_guards_read_a_parameter_the_route_actually_has():
    """A guard whose parameter the route lacks becomes a required query arg.

    FastAPI does not complain — it silently promotes the name, and every
    caller gets a 422. Nothing else in the suite would notice.
    """
    mismatched: list[str] = []
    for file_name, node, route_path in _route_handlers():
        params = {a.arg for a in node.args.args + node.args.kwonlyargs}
        for guard in _declared_guards(node):
            wanted = SCOPE_GUARDS[guard]
            if f"{{{wanted}}}" in route_path or wanted in params:
                continue
            mismatched.append(
                f"{file_name}::{node.name} uses {guard} but has no {wanted}"
            )
    assert not mismatched, ", ".join(mismatched)
