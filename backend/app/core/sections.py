"""The section registry (HRP-820): which API paths make up a menu section,
what each role gets there by default, and the flags the tenant's
section × role matrix must respect.

One source of truth. ``test_section_registry.py`` fails a route the
registry does not place, ``test_section_defaults.py`` pins the defaults
to the matrix in docs/core/docs/rbac.md.

Every section's routes read the matrix (``require_section``, HRP-821…831):
``none`` closes the section, ``view`` reads, ``manage`` writes, and the
tenant may raise a role above its default as well as lower it.

A *self-guarded* section keeps finer rules of its own (Coverage, HRP-821):
the gate closes ``none`` and leaves the rest to the section's dependencies,
which know what one ``view`` caller may still do - edit the process they
own, ask for an agent for themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends
from fastapi.dependencies.models import Dependant
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session
from starlette.requests import HTTPConnection
from starlette.routing import BaseRoute

from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.models import User

Level = Literal["none", "view", "manage"]
LEVELS: tuple[Level, ...] = ("none", "view", "manage")
LEVEL_ORDER: dict[str, int] = {level: i for i, level in enumerate(LEVELS)}
ROLE_CODES: tuple[str, ...] = ("admin", "hr", "manager", "recruiter", "hiring_manager", "employee")
PLATFORM_ROLE = "platform_admin"  # sees everything, has no row in the matrix


@dataclass(frozen=True)
class Section:
    code: str
    prefixes: tuple[str, ...]  # route path prefixes under /api; the longest match wins
    defaults: Mapping[str, Level]  # role code -> level
    self_guarded: bool = False  # its routes rule mutations per resource
    admin_locked: bool = False  # the admin row never drops below manage; implies never_hidden
    never_hidden: bool = False  # cannot be hidden from everyone


def _row(
    admin: Level, hr: Level, manager: Level, recruiter: Level, hiring_manager: Level, employee: Level
) -> dict[str, Level]:
    return {
        "admin": admin,
        "hr": hr,
        "manager": manager,
        "recruiter": recruiter,
        "hiring_manager": hiring_manager,
        "employee": employee,
    }


# Today's behaviour read from the code - sidebar flags for visibility,
# the privileged mutations for ``manage`` - oddities included.
SECTIONS: tuple[Section, ...] = (
    # HRP-829: ``manage`` runs the employee record - creates, edits, moves
    # people and keeps their history and pay - within the caller's subtree
    # (admin-level roles the workspace). ``hr`` stays at ``view``: it never
    # wrote here (the role list was admin/manager). Deleting someone,
    # granting a role and the set-password link stay the admin role's.
    # Anyone keeps their own education and courses at ``view`` (HRP-66),
    # so the section guards itself: every write asks for ``manage``, the
    # admin role or the owner, the gate closes ``none``.
    Section(
        "employees",
        ("/employees",),
        _row("manage", "view", "manage", "view", "view", "view"),
        self_guarded=True,
        never_hidden=True,
    ),
    # HRP-828: ``manage`` shapes the org chart - creates, edits, moves and
    # maps divisions and authors positions - within the caller's subtree
    # (admin-level roles the workspace). ``hr`` defaults to ``view``: it
    # never wrote either (the role list was admin/manager), and its old
    # ``manage`` cell came from the specialization ladder and matrices,
    # which stay an admin/hr asset by role like the answer scales. Those
    # are writes at ``view``, so the section guards itself: the routes
    # that shape the chart ask for ``manage``, the gate closes ``none``.
    # The grade system, the company profile, deletes and this very matrix
    # stay the admin role's. The pickers every section reads stay outside
    # the gate (SHARED_READS).
    Section(
        "company",
        ("/company", "/divisions", "/onboarding", "/positions", "/specializations", "/grade-system",
         "/settings/company-profile", "/settings/section-access"),
        _row("manage", "view", "manage", "view", "view", "view"),
        self_guarded=True,
        admin_locked=True,
        never_hidden=True,
    ),
    # HRP-826: ``manage`` runs assessments - creates, edits, calibrates and
    # reads the detailed results of single and mass assessments within the
    # caller's read scope, and the CPA cycles. ``view`` is the respondent's
    # half: answering is a POST, so the section guards itself - the routes
    # that run it ask for ``manage``, the gate closes ``none``. ``hr``
    # defaults to ``view``: it never ran assessments (the role list was
    # admin/manager), and its old ``manage`` cell came from the answer-scale
    # catalogue, which stays an admin/hr asset by role (HRP-631).
    Section(
        "assessments",
        ("/assessments", "/assessments-grouped", "/assessment-groups", "/answer-scales", "/cpa", "/review"),
        _row("manage", "view", "manage", "view", "view", "view"),
        self_guarded=True,
    ),
    # The plan's progress chart is read by every role from the plan page.
    # HRP-825: ``manage`` authors plans - creates, edits, restores and
    # drafts them with AI - within the caller's read scope, and walks the
    # full status graph. ``view`` is the other half of the same entry: the
    # owner marks items and submits for review, the named reviewer ticks
    # items during the review, both comment. Those are POSTs, so the section guards
    # itself - the authoring routes ask for ``manage``, the gate closes
    # ``none``. One's own plan stays inside the matrix, unlike an assigned
    # exam: a tenant that closes the section to a role has stopped running
    # plans for it, and the dashboard never asks for ``/pdp``.
    Section(
        "development",
        ("/pdp", "/analytics/pdp"),
        _row("manage", "view", "manage", "view", "view", "view"),
        self_guarded=True,
    ),
    # HRP-823: ``manage`` runs the section - mass exams, their questions,
    # pass marks, results and assignments. ``view`` is the other side of the
    # same menu entry: the taker's own exams, which no level closes (see
    # PERSONAL_PATHS) because the assignment e-mail links straight to
    # ``/exams``. Reading someone else's exam is part of running the section
    # rather than of ``view`` - ``employee`` defaults to ``view``, and that
    # cell must not hand the workspace's exams to everyone.
    Section(
        "exams",
        ("/exams", "/mass-exams"),
        _row("manage", "view", "manage", "view", "view", "view"),
    ),
    # HRP-827: ``manage`` authors the tenant's competence catalogue -
    # groups, competences, indicators, materials and their per-specialization
    # overrides, AI-drafted indicators and materials included. The catalogue
    # has no owning division, so the level reaches all of it (HRP-631).
    # Deleting from it, writing the skill-level ladder and generating the
    # tree with AI stay the admin role's on top of ``manage``: they were
    # admin-only before the matrix, and ``hr``'s ``manage`` cell is its
    # authoring. The reads other sections are built on stay outside the
    # gate (SHARED_READS). Self-guarded since HRP-632: a division head adds
    # a personal draft at ``view``, every other write asks ``manage`` itself.
    Section(
        "competences",
        ("/competences", "/competence-groups", "/competence-tree", "/indicators", "/materials",
         "/skill-levels", "/competence-generation"),
        _row("manage", "manage", "view", "view", "view", "view"),
        self_guarded=True,
    ),
    # HRP-821: ``manage`` is the section's manager - every process, the
    # agent registry, everyone's assignments. The process dynamics
    # (``work.access.section_level``) narrow ``/auth/me``'s menu only: the
    # gate reads ``matrix_levels`` and never sees them, so a caller who
    # reads no process still gets the ``/work`` routes' own answers (an
    # empty list, a 404) rather than a blanket 403.
    Section(
        "coverage",
        ("/work", "/primitives", "/ai-workforce"),
        _row("manage", "manage", "view", "view", "view", "view"),
        self_guarded=True,
    ),
    # HRP-824: ``manage`` authors the board - creates, edits, publishes,
    # staffs and deletes cards within the caller's read scope (admin-level
    # roles the workspace, anyone else their managed subtree and their own
    # cards). ``view`` is the candidate's half of the same entry: the cards
    # one's own name is on, the reaction and the plan request. Two of those
    # and the search itself are POSTs, so the section is self-guarded - the
    # routes that run the board ask for ``manage`` themselves, the gate only
    # closes ``none``. Nothing here leaves the matrix: unlike an assigned
    # exam, a candidacy is an invitation to read, and a closed section
    # closes it, e-mail link included.
    Section(
        "talent-market",
        ("/talent-market",),
        _row("manage", "view", "manage", "view", "view", "view"),
        self_guarded=True,
    ),
    # HRP-830: ``manage`` runs hiring for the whole workspace - vacancies,
    # candidates, interviews, AI analyses, consents, reports, evaluation and
    # hiring rounds - and sees all of it (``recruitment.scope``). ``view``
    # reads the vacancies in the caller's scope: their own, the ones they
    # are hiring manager of, their managed subtree's. Two roles keep a
    # piece on top of ``view`` there (Maxim, 25.09): ``hiring_manager``
    # evaluates - questions, human scores, the candidate's stage - and
    # ``manager`` runs hiring rounds, so the section guards itself: every
    # write asks for ``manage``, one of those roles, or the admin / hr role
    # for the tenant settings and GDPR it always held. ``hiring_manager``
    # defaults to ``view`` - it never authored here; ``hr`` keeps ``manage``.
    # The rounds, question sets and scales live under ``/v1`` next to the
    # public API, so their prefixes are named here one by one.
    Section(
        "recruitment",
        ("/recruitment", "/reports", "/v1/candidates", "/v1/candidate-vacancies", "/v1/question-sets",
         "/v1/questions", "/v1/tenants/me/assessment-scales", "/v1/assessment-scales", "/v1/vacancies",
         "/v1/assessment-rounds", "/v1/assessments", "/v1/manager-assessment-invites"),
        _row("manage", "manage", "view", "manage", "view", "none"),
        self_guarded=True,
    ),
    # HRP-822: read-only by nature, so the generic rule is enough and the
    # section needs no ``self_guarded`` - ``view`` reads the charts,
    # ``manage`` adds the two exports and the AI summary. How wide the
    # figures are stays the read scope's answer rather than the level's:
    # full coverage is an admin-level role (``core/access_scope.py``),
    # a manager gets their subtree, anyone else their own row.
    Section(
        "analytics",
        ("/analytics",),
        _row("manage", "manage", "manage", "none", "none", "none"),
    ),
    # HRP-827: ``manage`` edits the dictionaries (grades, specializations,
    # competence types) and opens their page; ``view`` is the pickers every
    # form reads, which SHARED_READS keeps open whatever the matrix says.
    Section(
        "dictionaries",
        ("/dictionaries",),
        _row("manage", "view", "view", "view", "view", "view"),
        admin_locked=True,
        never_hidden=True,
    ),
    # HRP-831: the admin block. ``view`` reads (the import history, the
    # role list, the AI settings, the invitations in one's scope), ``manage``
    # writes. Invitations narrow by org structure below the admin level:
    # a manager sees and sends only into their subtree; the role a caller
    # may hand out stays the inviter hierarchy's (``_INVITE_ALLOWED``).
    Section("import", ("/import",), _row("manage", "none", "none", "none", "none", "none"), admin_locked=True, never_hidden=True),
    Section("invitations", ("/invitations",), _row("manage", "manage", "manage", "none", "none", "none"), admin_locked=True, never_hidden=True),
    Section("roles", ("/roles",), _row("manage", "none", "none", "none", "none", "none"), admin_locked=True, never_hidden=True),
    Section("ai-settings", ("/admin/ai-settings",), _row("manage", "none", "none", "none", "none", "none"), admin_locked=True, never_hidden=True),
)
SECTIONS_BY_CODE: dict[str, Section] = {s.code: s for s in SECTIONS}

# Outside the matrix: auth, the public API, enterprise, and surfaces with
# no menu entry. ``/ai`` has no section of its own: each route under it
# guards itself: a section, the admin role, or just a signed-in user for
# the search (left so in HRP-832).
# ``/v1`` is the API-key surface; recruitment's own ``/v1`` routes are
# claimed by the section above (longest prefix wins).
# ``/public-check`` is the anonymous process check (HRP-922): no account, no
# role, nothing of a tenant's.
ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "/auth", "/v1", "/platform", "/billing", "/ee", "/blog", "/ai", "/notifications",
    "/settings/notifications", "/settings/email-logs", "/webhooks", "/files", "/api-keys",
    "/demo", "/signup-request", "/public", "/tasks", "/feedback", "/public-check",
)

# One's own profile, loop and exams stay reachable whatever the matrix says.
PERSONAL_PATHS: frozenset[str] = frozenset(
    {
        "/api/employees/me",
        "/api/analytics/my-loop",
        "/api/analytics/my-loop/ai-summary",
        # HRP-823: everything under ``/exams`` is the taker's own side of
        # the exams section - the list answers the caller's read scope, the
        # other four resolve one exam through the caller's own employee row.
        # ``/mass-exams`` is the section itself and stays gated.
        "/api/exams",
        "/api/exams/{exam_id}/questions",
        "/api/exams/{exam_id}/review",
        "/api/exams/{exam_id}/answer",
        "/api/exams/{exam_id}/finish",
    }
)

# HRP-827: catalogue reads the rest of the product is built on - the
# competence tree and card behind every picker, the skill levels, the
# indicators by level a specialization matrix shows, the dictionary lists. They answer every signed-in
# caller as before: closing the catalogue's menu entry must not break the
# assessment, the vacancy or the profile that reads it. Writes on the same
# paths stay gated.
SHARED_READS: frozenset[str] = frozenset(
    {
        "/api/competence-tree",
        "/api/competences/{competence_id}",
        "/api/competences/{competence_id}/indicators-by-level",
        "/api/skill-levels",
        "/api/dictionaries/{item_type}",
        "/api/dictionaries/items/{item_id}",
        # HRP-828: the org chart and the job catalogue behind every
        # division, position and grade picker, and the company the
        # dashboard greets with.
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
        # HRP-829: the employee list behind every people picker and the
        # global search, and the card other sections open an employee
        # with. Each keeps its own read scope and schema.
        "/api/employees",
        "/api/employees/{employee_id}",
        # HRP-831: the role list behind the invitation form - the route
        # itself answers whoever opens roles or invitations. Writing a
        # role stays gated.
        "/api/roles",
    }
)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def section_for_path(path: str) -> Section | None:
    """The section owning an ``/api/...`` route path; the longest prefix wins."""
    best: tuple[int, Section] | None = None
    for section in SECTIONS:
        for prefix in section.prefixes:
            full = "/api" + prefix
            if _under(path, full) and (best is None or len(full) > best[0]):
                best = (len(full), section)
    return best[1] if best else None


def is_allowlisted(path: str) -> bool:
    return any(_under(path, "/api" + prefix) for prefix in ALLOWLIST_PREFIXES)


def role_level(
    section: Section,
    role: str,
    overrides: Mapping[tuple[str, str], Level],
    hidden: Container[str],
) -> Level:
    """One cell after the tenant's override and the lockout floor."""
    level = overrides.get((section.code, role), section.defaults[role])
    if section.code in hidden and not section.never_hidden:
        level = "none"
    if section.admin_locked and role == "admin":
        level = "manage"  # §8: the admin block never locks the admin out
    return level


def effective_levels(
    role_codes: Iterable[str],
    overrides: Mapping[tuple[str, str], Level],
    hidden: Container[str],
) -> dict[str, Level]:
    """Per section, the strongest level any of the caller's roles reaches."""
    held = set(role_codes)
    # Invariant: every account holds at least ``employee`` (granted on every
    # creation path, backfilled by migration). An account with none of the
    # six configurable roles - a custom/unknown code only - still reaches
    # whatever ``employee`` reaches, so the gate does not 403 a route that
    # today only checks ``get_current_user``.
    codes = [r for r in ROLE_CODES if r in held] or ["employee"]
    return {
        s.code: max(
            (role_level(s, r, overrides, hidden) for r in codes),
            key=LEVEL_ORDER.__getitem__,
            default="none",
        )
        for s in SECTIONS
    }


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def denies(section: Section, level: Level, method: str) -> bool:
    """Whether the gate answers 403 for this level on this method."""
    if level == "none":
        return True
    if section.self_guarded:
        return False  # its own dependencies answer for everything above ``none``
    return level == "view" and method not in _READ_METHODS


# HRP-1018: ``db.info`` key of the per-session memo below,
# ``{(user id, role codes): levels}``. A session is a request (``get_db``).
_MEMO = "section_matrix_levels"


@event.listens_for(Session, "after_flush")
@event.listens_for(Session, "after_soft_rollback")
def _forget(session: Session, _context: object) -> None:
    session.info.pop(_MEMO, None)


@event.listens_for(Session, "do_orm_execute")
def _forget_on_write(state: ORMExecuteState) -> None:
    # A bulk or Core write never flushes; any non-SELECT counts as one. A raw
    # ``text()`` read is not a SELECT to SQLAlchemy either and drops the memo
    # too - an extra read, never a stale one.
    if not state.is_select:
        state.session.info.pop(_MEMO, None)


async def matrix_levels(db: AsyncSession, user: User) -> dict[str, Level]:
    """What the tenant's matrix alone says per section: the caller's roles,
    the overrides and the lockout floor. The gate and
    ``require_section`` read this.

    Read once per session and kept in ``db.info`` (HRP-1018): the gate,
    ``require_section`` and the modules' scopes ask several times a request.
    Any write in the session - pending, flushed or rolled back - drops the
    memo, so a request, or a test that shares one session across requests,
    never reads a level it has just changed or undone. The role codes are
    part of the key, so a role change is a new key. Returns a copy: callers
    may narrow it (``levels_for``)."""
    codes = {r.code for r in user.roles}
    if PLATFORM_ROLE in codes:
        return dict.fromkeys(SECTIONS_BY_CODE, "manage")
    key = (user.id, frozenset(codes))
    if db.new or db.dirty or db.deleted:
        # Pending rows reach the overrides only through the autoflush the
        # read below triggers; the memo would answer before it.
        db.info.pop(_MEMO, None)
    levels = db.info.get(_MEMO, {}).get(key)
    if levels is None:
        # Imported here: core sits under every module.
        from app.modules.company.service import get_section_overrides

        overrides, hidden = await get_section_overrides(db, user.tenant_id)
        levels = effective_levels(codes, overrides, hidden)
        db.info.setdefault(_MEMO, {})[key] = levels
    return dict(levels)


async def levels_for(db: AsyncSession, user: User) -> dict[str, Level]:
    """What ``/auth/me`` shows: the matrix, and for Coverage the process
    dynamics narrowing it - the menu entry needs a process to open, the
    gate does not (see the ``coverage`` entry above)."""
    levels = await matrix_levels(db, user)
    codes = {r.code for r in user.roles}
    if PLATFORM_ROLE not in codes:
        # Imported here: core sits under every module.
        from app.modules.work.access import section_level

        levels["coverage"] = await section_level(db, user, levels["coverage"]) or "none"
    return levels


def require_section(code: str, level: Level = "view") -> Callable:
    """Explicit gate for a section (HRP-821...831): the caller
    reaches ``code`` at ``level`` or better, else 403."""
    section = SECTIONS_BY_CODE[code]
    from app.modules.auth.dependencies import get_current_user

    async def section_checker(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        actual = (await matrix_levels(db, current_user))[section.code]
        if LEVEL_ORDER[actual] < LEVEL_ORDER[level]:
            raise AppError("auth_insufficient_permissions", 403)
        return current_user

    return section_checker


# HRP-820: the global gate (see section_gate below). Keyed by id(route),
# not the route itself: Starlette's Route defines __eq__ without __hash__,
# so route objects are unhashable. Safe because the only routes ever fed
# in are the single module-level ``app``'s, which live for the process.
_GATED: dict[int, Section | None] = {}


def _needs_user(dependant: Dependant) -> bool:
    return any(
        getattr(dep.call, "__name__", "") == "get_current_user" or _needs_user(dep)
        for dep in dependant.dependencies
    )


def gated_section(route: BaseRoute | None) -> Section | None:
    """The section a route is narrowed by: none for personal paths and
    shared reads, for routes outside the matrix, and for routes with no user
    to narrow (token links such as ``/review/{token}``). Cached per route
    object."""
    key = id(route)
    if key in _GATED:
        return _GATED[key]
    path = getattr(route, "path", "")
    dependant = getattr(route, "dependant", None)
    shared = path in SHARED_READS and set(getattr(route, "methods", None) or ()) <= _READ_METHODS
    section = None
    if path not in PERSONAL_PATHS and not shared and dependant is not None and _needs_user(dependant):
        section = section_for_path(path)
    _GATED[key] = section
    return section


async def section_gate(conn: HTTPConnection, db: AsyncSession = Depends(get_db)) -> None:
    """Global dependency (``FastAPI(dependencies=[…])``): 403 when the
    caller's level in the route's section denies the method.

    Takes ``HTTPConnection``, not ``Request``: app-level dependencies are
    copied onto every route ``include_router`` adds, WebSocket routes
    included, but FastAPI's dependency solver only fills a
    ``Request``-annotated parameter for HTTP connections - a WebSocket
    handshake would crash in dependency resolution before the endpoint's
    own auth ever ran (HRP-820 review). ``HTTPConnection`` is the common
    base and is filled for both, so the first line below bails out on a
    WebSocket scope and leaves it to the route's own handler (``/ws``'s
    JWT-over-query-param), which the gate has nothing to add to anyway.
    """
    if conn.scope["type"] != "http":
        return
    section = gated_section(conn.scope.get("route"))
    if section is None:
        return
    # Parsed exactly like the route's OAuth2 scheme (it strips the token):
    # a header the route accepts must never fail here and skip the matrix.
    scheme, token = get_authorization_scheme_param(conn.headers.get("authorization"))
    if scheme.lower() != "bearer" or not token:
        return  # the route's own guard answers 401
    from app.modules.auth.dependencies import resolve_user_from_access_token

    user = await resolve_user_from_access_token(db, token)
    if user is None:
        return
    # ponytail: a gated authenticated request re-resolves the caller here
    # (user + roles + employee status) on top of the route's own
    # get_current_user; the override tables are read once per request
    # (matrix_levels' memo). Stash the resolved user on request.state and
    # let get_current_user reuse it if this shows up in profiles.
    level = (await matrix_levels(db, user))[section.code]
    if denies(section, level, conn.scope["method"]):
        raise AppError("auth_insufficient_permissions", 403)
