"""HRP-820: one cell of the matrix - the tenant's override, the hidden flag,
the admin floor - and what the gate makes of a level."""

import pytest
from app.core import sections
from app.core.errors import AppError
from app.core.sections import denies, effective_levels, require_section, role_level

from tests.unit.test_work_containers import _user_with_role

EMPLOYEES = sections.SECTIONS_BY_CODE["employees"]
COMPANY = sections.SECTIONS_BY_CODE["company"]
INVITATIONS = sections.SECTIONS_BY_CODE["invitations"]
IMPORT = sections.SECTIONS_BY_CODE["import"]
ROLES = sections.SECTIONS_BY_CODE["roles"]
COVERAGE = sections.SECTIONS_BY_CODE["coverage"]
URL = "/api/settings/section-access"


def test_override_applies_both_ways():
    # HRP-831 translated the last section and HRP-832 dropped the clamp that
    # narrowed an untranslated one: a raise counts as much as a cut.
    assert role_level(IMPORT, "recruiter", {("import", "recruiter"): "manage"}, set()) == "manage"
    assert role_level(INVITATIONS, "manager", {("invitations", "manager"): "view"}, set()) == "view"
    assert role_level(INVITATIONS, "manager", {}, set()) == "manage"


def test_a_role_never_goes_above_its_ceiling():
    # HRP-831 (QA 15.10): the roles below ``manager`` invite nobody, and
    # writing roles is the admin's alone - whatever a row says.
    for role in ("recruiter", "hiring_manager", "employee"):
        assert role_level(INVITATIONS, role, {("invitations", role): "manage"}, set()) == "none"
    for role in ("hr", "manager", "recruiter", "hiring_manager", "employee"):
        assert role_level(ROLES, role, {("roles", role): "manage"}, set()) == "view"
        assert role_level(ROLES, role, {("roles", role): "view"}, set()) == "view"
    assert role_level(ROLES, "admin", {}, set()) == "manage"
    # HRP-830: the Employee role never reaches hiring.
    recruitment = sections.SECTIONS_BY_CODE["recruitment"]
    assert role_level(recruitment, "employee", {("recruitment", "employee"): "view"}, set()) == "none"
    assert role_level(recruitment, "hiring_manager", {("recruitment", "hiring_manager"): "manage"}, set()) == "manage"
    assert effective_levels(["employee", "manager"], {("roles", "manager"): "manage"}, set())["roles"] == "view"


def test_every_default_sits_under_its_ceiling():
    # A default above the ceiling would be a cell the screen cannot show.
    for s in sections.SECTIONS:
        for role, cap in s.ceilings.items():
            assert role in sections.ROLE_CODES, (s.code, role)
            assert sections.LEVEL_ORDER[s.defaults[role]] <= sections.LEVEL_ORDER[cap], (s.code, role)


def test_hidden_is_none_for_everyone_unless_never_hidden():
    exams = sections.SECTIONS_BY_CODE["exams"]
    assert role_level(exams, "admin", {}, {"exams"}) == "none"
    assert role_level(EMPLOYEES, "admin", {}, {"employees"}) == "manage"


def test_admin_locked_floor_wins_over_everything():
    assert role_level(COMPANY, "admin", {("company", "admin"): "none"}, {"company"}) == "manage"
    assert role_level(COMPANY, "hr", {("company", "hr"): "none"}, set()) == "none"


def test_strongest_role_wins():
    levels = effective_levels(["employee", "hr"], {}, set())
    assert levels["competences"] == "manage"  # hr
    assert levels["employees"] == "view"
    assert levels["roles"] == "none"
    # Fix round 2: no configurable role held falls back to the employee
    # baseline, not "none" everywhere - see
    # test_no_configurable_role_falls_back_to_the_employee_baseline below.
    assert effective_levels([], {}, set())["employees"] == "view"


def test_no_configurable_role_falls_back_to_the_employee_baseline():
    # CONTROLLER RULING (fix round 2): every account holds at least
    # ``employee`` (granted on every creation path, backfilled by
    # migration). An account with none of the six configurable roles - no
    # roles at all, or only a custom/unknown code - still reaches whatever
    # ``employee`` reaches, matrix-wide, so the gate never 403s a route
    # that today only checks ``get_current_user``.
    employee_row = {s.code: s.defaults["employee"] for s in sections.SECTIONS}
    assert effective_levels([], {}, set()) == employee_row
    assert effective_levels(["some-custom-role"], {}, set()) == employee_row


def test_the_gate_closes_none_and_view_writes():
    assert denies(INVITATIONS, "none", "GET")
    assert denies(INVITATIONS, "view", "POST")
    assert not denies(INVITATIONS, "view", "GET")
    assert not denies(INVITATIONS, "manage", "DELETE")


def test_a_self_guarded_section_leaves_its_writes_to_its_routes():
    # HRP-821: the tenant may hand Coverage to a role the defaults gave only
    # ``view`` - but a ``view`` caller there still edits the process they
    # own and asks for an agent for themselves. The section's own
    # dependencies know that; the HTTP method does not.
    assert role_level(COVERAGE, "manager", {("coverage", "manager"): "manage"}, set()) == "manage"
    assert not denies(COVERAGE, "view", "POST")
    assert denies(COVERAGE, "none", "POST")
    assert denies(COVERAGE, "none", "GET")


async def test_widening_reaches_me_and_require_section(auth_client, client, db, tenant):
    matrix = (await auth_client.get(URL)).json()
    for s in matrix["sections"]:
        if s["code"] == "import":
            s["levels"]["recruiter"] = "manage"
    r = await auth_client.put(
        URL,
        json={
            "sections": [
                {"code": s["code"], "hidden": s["hidden"], "levels": s["levels"]}
                for s in matrix["sections"]
            ]
        },
    )
    assert r.status_code == 200, r.text

    recruiter, token = await _user_with_role(db, tenant, "recruiter")
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["sections"]["import"] == "manage"

    for level in ("view", "manage"):
        assert await require_section("import", level)(db=db, current_user=recruiter) is recruiter
    with pytest.raises(AppError) as exc:
        await require_section("roles", "view")(db=db, current_user=recruiter)
    assert exc.value.status_code == 403


async def test_matrix_levels_reads_the_tenant_once_per_session(db, user):
    # HRP-1018: the gate, require_section and the scopes all ask; one read.
    from sqlalchemy import event

    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        first = await sections.matrix_levels(db, user)
        assert statements, "the first call reads the overrides"
        statements.clear()
        first["coverage"] = "none"  # a caller narrowing its own copy
        second = await sections.matrix_levels(db, user)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert statements == []
    assert second["coverage"] == "manage"


async def test_a_write_in_the_session_drops_the_memo(db, tenant, user):
    from app.modules.auth.models import User
    from app.modules.company.models import TenantSectionAccess
    from sqlalchemy import delete, select
    from sqlalchemy.orm import selectinload

    user_id, tenant_id = user.id, tenant.id

    assert (await sections.matrix_levels(db, user))["coverage"] == "manage"
    db.add(
        TenantSectionAccess(
            tenant_id=tenant.id, section="coverage", role_code="admin", level="view"
        )
    )
    await db.commit()  # an ORM write: after_flush
    assert (await sections.matrix_levels(db, user))["coverage"] == "view"
    await db.execute(
        delete(TenantSectionAccess).where(TenantSectionAccess.tenant_id == tenant.id)
    )
    # a Core write never flushes: do_orm_execute
    assert (await sections.matrix_levels(db, user))["coverage"] == "manage"
    await db.commit()
    db.add(
        TenantSectionAccess(
            tenant_id=tenant.id, section="coverage", role_code="admin", level="none"
        )
    )
    await db.flush()
    assert (await sections.matrix_levels(db, user))["coverage"] == "none"
    await db.rollback()  # the write is undone, and so is the memo
    user = await db.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    assert (await sections.matrix_levels(db, user))["coverage"] == "manage"
    # A pending row, not flushed yet: the read autoflushes it, the memo must
    # not answer first.
    db.add(
        TenantSectionAccess(
            tenant_id=tenant_id, section="coverage", role_code="admin", level="view"
        )
    )
    assert (await sections.matrix_levels(db, user))["coverage"] == "view"
    await db.commit()
