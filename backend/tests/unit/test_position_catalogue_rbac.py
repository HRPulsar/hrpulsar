"""HRP-637: the positions catalogue published grades and salary bands to everyone.

``GET /positions`` hung on a bare ``get_current_user``, took ``limit`` up to
500 and answered ``grade_title``, ``specialization_title`` and the inherited
``salary_min`` / ``salary_max`` / ``salary_currency`` for every row. The
employee directory already publishes "colleague -> position" to the same
caller, so joining the two rebuilt any colleague's grade — which is exactly
what ``Tenant.directory_show_grades`` (HRP-623) exists to prevent. The flag
was closing the directory's copy of the field, not the fact behind it.

Two classes of field, two different rules:

* grade and specialization follow ``directory_show_grades`` — off, a
  rank-and-file caller sees neither; on, they see both;
* salary bands are compensation, not structure, and never reach anyone
  outside admin / hr / manager whatever the flag says.

Blanking the columns alone would not have closed either one: ``?grade_id=``
over an open list answers the same question ``grade_title`` answers, one
request per grade, and the specialization page serves the same join under
its own URLs. Fields, predicates and the sibling routes are checked here
together, because closing any two of the three still leaves the catalogue
readable through the third.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.config import settings
from app.core.security import create_access_token
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# The "position -> grade" join, in every spelling the payloads use.
GRADE_FIELDS = ("grade_id", "grade_title", "specialization_id", "specialization_title")
SALARY_FIELDS = ("salary_min", "salary_max")

# Roles that read the pair. Hiring is in the set and compensation is not:
# a requisition cannot be raised without the grade of the position it fills,
# but the band is not the recruiter's to read.
GRADE_ROLES = ("manager", "recruiter", "hiring_manager")


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    # `skill_levels` is a seed prerequisite, not something this file reads:
    # the demo seed builds competence matrices and fails without it.
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


async def _system_role(db: AsyncSession, code: str, name: str) -> Role:
    result = await db.execute(
        select(Role).where(Role.code == code, Role.is_system.is_(True))
    )
    role = result.scalars().first()
    if not role:
        role = Role(name=name, code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession) -> Role:
    return await _system_role(db, "employee", "Employee")


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession) -> Role:
    # The demo seed only hands out roles that already exist, so without this
    # the seeded division heads come back role-less and the manager half of
    # the boundary would never be exercised.
    return await _system_role(db, "manager", "Manager")


@pytest_asyncio.fixture
async def recruiter_role(db: AsyncSession) -> Role:
    return await _system_role(db, "recruiter", "Recruiter")


@pytest_asyncio.fixture
async def hiring_manager_role(db: AsyncSession) -> Role:
    return await _system_role(db, "hiring_manager", "Hiring Manager")


class DemoPersona:
    def __init__(
        self,
        tenant_id,
        admin_headers,
        headers,
        position_id,
        spec_id,
        grade_id,
    ):
        self.tenant_id = tenant_id
        self.admin_headers = admin_headers
        self.headers = headers
        self.position_id = position_id
        self.spec_id = spec_id
        self.grade_id = grade_id


@pytest_asyncio.fixture
async def persona(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    recruiter_role,
    hiring_manager_role,
    enable_demo,
) -> DemoPersona:
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    admin_headers = {"Authorization": f"Bearer {start.json()['access_token']}"}

    switched = await client.post(
        "/api/demo/switch-view", json={"persona": "employee"}, headers=admin_headers
    )
    assert switched.status_code == 200, switched.text
    headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}

    tenant_id = start.json()["tenant_id"]
    # Any position carrying both halves of the pair — without one the grade
    # assertions below would pass on a row that never had a grade to leak.
    position = (
        (
            await db.execute(
                select(Position)
                .where(
                    Position.tenant_id == tenant_id,
                    Position.specialization_id.is_not(None),
                    Position.grade_id.is_not(None),
                )
                .order_by(Position.title)
            )
        )
        .scalars()
        .first()
    )
    assert position is not None, "demo seed has no position with a specialization"
    return DemoPersona(
        tenant_id,
        admin_headers,
        headers,
        position.id,
        position.specialization_id,
        position.grade_id,
    )


@pytest_asyncio.fixture
async def manager_headers(db: AsyncSession, persona: DemoPersona) -> dict[str, str]:
    """A division head who is *only* a manager.

    The demo seed hands the People & Talent head the ``hr`` role on top of
    ``manager``, and ``hr`` reads everything by design — that actor would
    turn "a manager still sees the bands" into a tautology about admins.
    """
    from app.core.access_scope import ADMIN_ROLE_CODES

    divisions = (
        (
            await db.execute(
                select(Division).where(
                    Division.tenant_id == persona.tenant_id,
                    Division.manager_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for division in divisions:
        head = await db.get(Employee, division.manager_id)
        if head is None or head.user_id is None:
            continue
        codes = {
            r.code
            for r in (
                await db.execute(
                    select(Role)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == head.user_id)
                )
            )
            .scalars()
            .all()
        }
        if "manager" in codes and not (codes & ADMIN_ROLE_CODES):
            token = create_access_token(str(head.user_id), str(persona.tenant_id))
            return {"Authorization": f"Bearer {token}"}
    pytest.fail("demo seed has no division head who is only a manager")


@pytest_asyncio.fixture
async def role_headers(db: AsyncSession, persona: DemoPersona):
    """Mint a token for a seeded user holding `code` and no admin role.

    Takes the person the demo seed already built rather than inventing one,
    so the row under test is wired to real positions and divisions.
    """
    from app.core.access_scope import ADMIN_ROLE_CODES

    async def _for(code: str) -> dict[str, str]:
        # ``is_active`` matters: the demo seed deactivates some of the people
        # it creates, and a token for one of those 401s before any of this
        # ticket's rules are reached. Found by minting one against a live
        # server and getting "could not validate credentials".
        rows = (
            await db.execute(
                select(Role.code, user_roles.c.user_id)
                .join(user_roles, user_roles.c.role_id == Role.id)
                .join(User, User.id == user_roles.c.user_id)
                .where(User.tenant_id == persona.tenant_id, User.is_active.is_(True))
            )
        ).all()
        by_user: dict[uuid.UUID, set[str]] = {}
        for role_code, user_id in rows:
            by_user.setdefault(user_id, set()).add(role_code)
        for user_id, codes in by_user.items():
            if code in codes and not (codes & ADMIN_ROLE_CODES):
                token = create_access_token(str(user_id), str(persona.tenant_id))
                return {"Authorization": f"Bearer {token}"}
        pytest.fail(f"demo seed has no {code} without an admin role")

    return _for


async def _show_grades(db: AsyncSession, tenant_id, value: bool) -> None:
    tenant = await db.get(Tenant, uuid.UUID(str(tenant_id)))
    tenant.directory_show_grades = value
    await db.commit()


async def _catalogue(client: AsyncClient, headers: dict, query: str = "") -> dict:
    resp = await client.get(f"/api/positions?limit=200{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"], "the catalogue came back empty — the assertions are vacuous"
    return body


# --- (a) the position -> grade join ---------------------------------------


@pytest.mark.asyncio
async def test_catalogue_hides_the_pair_while_the_flag_is_off(
    client: AsyncClient, persona: DemoPersona
):
    body = await _catalogue(client, persona.headers)
    for row in body["items"]:
        for field in GRADE_FIELDS:
            assert row[field] is None, f"{field} leaked into the catalogue row"
        # HRP-180's option pools are the same fact in list form.
        assert row["specializations"] == []
        assert row["grades"] == []
        # What a catalogue is for still arrives.
        assert row["title"]
    assert any(row["headcount"] is not None for row in body["items"])


@pytest.mark.asyncio
async def test_catalogue_shows_the_pair_once_the_tenant_opts_in(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    await _show_grades(db, persona.tenant_id, True)
    body = await _catalogue(client, persona.headers)
    assert any(row["grade_title"] for row in body["items"]), (
        "directory_show_grades is on and the catalogue still hides the grade"
    )
    assert any(row["specialization_title"] for row in body["items"])


@pytest.mark.asyncio
async def test_the_grade_filter_dies_with_the_field(
    client: AsyncClient, persona: DemoPersona
):
    """A predicate over a hidden field answers the question the field would.

    One request per grade rebuilds the whole "position -> grade" map without
    the payload ever naming a grade, so the filters go when the columns go —
    and come back when the columns do.
    """
    everything = await _catalogue(client, persona.headers)
    for query in (
        f"&grade_id={persona.grade_id}",
        f"&specialization_id={persona.spec_id}",
    ):
        filtered = await _catalogue(client, persona.headers, query)
        assert filtered["total"] == everything["total"], (
            f"{query} still narrowed the catalogue for a rank-and-file caller"
        )

    # The same predicate must still work for the caller it was built for,
    # or the assertion above would pass on a filter that never filtered.
    narrowed = await _catalogue(
        client, persona.admin_headers, f"&grade_id={persona.grade_id}"
    )
    assert narrowed["total"] < everything["total"]
    assert all(row["grade_id"] == str(persona.grade_id) for row in narrowed["items"])


@pytest.mark.asyncio
async def test_the_filter_comes_back_with_the_flag(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    await _show_grades(db, persona.tenant_id, True)
    everything = await _catalogue(client, persona.headers)
    filtered = await _catalogue(
        client, persona.headers, f"&grade_id={persona.grade_id}"
    )
    assert filtered["total"] < everything["total"]


@pytest.mark.asyncio
async def test_the_detail_and_both_matrix_reads_hide_the_pair(
    client: AsyncClient, persona: DemoPersona
):
    """The list is one of four routes that carry the pair.

    ``grade_specialization_id`` counts as a spelling of it: the
    specialization page turns that id straight back into a grade title.
    """
    routes = {
        f"/api/positions/{persona.position_id}": GRADE_FIELDS,
        f"/api/positions/{persona.position_id}/matrix-status": (
            "specialization_id",
            "grade_id",
            "grade_specialization_id",
        ),
        f"/api/positions/{persona.position_id}/competences": (
            "specialization_id",
            "grade_id",
            "grade_specialization_id",
        ),
    }
    for url, fields in routes.items():
        resp = await client.get(url, headers=persona.headers)
        assert resp.status_code == 200, resp.text
        row = resp.json()
        for field in fields:
            assert row[field] is None, f"{field} leaked from {url}"

    # Same routes, an admin: the fields are there to be leaked.
    for url, fields in routes.items():
        resp = await client.get(url, headers=persona.admin_headers)
        assert resp.status_code == 200, resp.text
        assert any(resp.json()[field] is not None for field in fields), (
            f"{url} carries none of {fields} even for an admin — rewrite this test"
        )


@pytest.mark.asyncio
async def test_the_specialization_drill_down_hides_the_pair(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """Same join, one specialization at a time instead of one filter away."""
    url = f"/api/specializations/{persona.spec_id}/positions"

    hidden = await client.get(url, headers=persona.headers)
    assert hidden.status_code == 200, hidden.text
    rows = [pos for block in hidden.json() for pos in block["positions"]]
    assert rows, "no positions under the specialization — nothing was checked"
    for row in rows:
        assert row["grade_id"] is None, "grade_id leaked into the drill-down"
        assert row["grade_title"] is None, "grade_title leaked into the drill-down"
        assert row["title"]

    await _show_grades(db, persona.tenant_id, True)
    shown = await client.get(url, headers=persona.headers)
    assert shown.status_code == 200, shown.text
    assert any(
        pos["grade_title"] for block in shown.json() for pos in block["positions"]
    ), "the flag is on and the drill-down still hides the grade"


# --- (b) compensation ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True])
async def test_salary_bands_never_reach_a_rank_and_file_caller(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona, flag: bool
):
    """Compensation is not structure — ``directory_show_grades`` does not open it.

    Parametrised over the flag on purpose: the grade fields and the bands
    ride the same payloads, and a rule written once for both would hand out
    the salary the moment a tenant turned grades on in the directory.
    """
    await _show_grades(db, persona.tenant_id, flag)
    body = await _catalogue(client, persona.headers)
    for row in body["items"]:
        for field in SALARY_FIELDS:
            assert row[field] is None, f"{field} leaked into the catalogue row"

    detail = await client.get(
        f"/api/positions/{persona.position_id}", headers=persona.headers
    )
    assert detail.status_code == 200, detail.text
    for field in SALARY_FIELDS:
        assert detail.json()[field] is None, f"{field} leaked from the position detail"


@pytest.mark.asyncio
async def test_the_specialization_page_hides_its_bands(
    client: AsyncClient, persona: DemoPersona
):
    """The grade ladder stays readable; the band bolted to each rung does not.

    Three routes serve the same rows — the grades tab, the specialization
    detail that embeds them, and the legacy grade-system chain read.
    """
    ladder = await client.get(
        f"/api/specializations/{persona.spec_id}/grades", headers=persona.headers
    )
    assert ladder.status_code == 200, ladder.text
    rungs = ladder.json()
    assert rungs, "the specialization has no grades — nothing was checked"
    for rung in rungs:
        assert rung["salary_min"] is None, "salary_min leaked from the grades tab"
        assert rung["salary_max"] is None, "salary_max leaked from the grades tab"
        # The ladder itself is what the page is for.
        assert rung["grade_title"]

    detail = await client.get(
        f"/api/specializations/{persona.spec_id}", headers=persona.headers
    )
    assert detail.status_code == 200, detail.text
    assert all(g["salary_min"] is None for g in detail.json()["grades"]), (
        "the embedded ladder still carries the bands"
    )

    chains = await client.get(
        f"/api/grade-system/specializations/{persona.spec_id}",
        headers=persona.headers,
    )
    assert chains.status_code == 200, chains.text
    assert all(c["salary_min"] is None for c in chains.json()), (
        "the grade-system chain read still carries the bands"
    )


@pytest.mark.asyncio
async def test_a_manager_still_reads_the_bands(
    client: AsyncClient, persona: DemoPersona, manager_headers: dict
):
    """Admin / hr / manager keep compensation — the cut is below them."""
    body = await _catalogue(client, manager_headers)
    assert any(row["salary_min"] is not None for row in body["items"]), (
        "the catalogue lost its salary bands for a manager"
    )

    ladder = await client.get(
        f"/api/specializations/{persona.spec_id}/grades", headers=manager_headers
    )
    assert ladder.status_code == 200, ladder.text
    assert any(rung["salary_min"] is not None for rung in ladder.json()), (
        "the specialization page lost its salary bands for a manager"
    )


@pytest.mark.asyncio
async def test_an_admin_reads_the_whole_row(client: AsyncClient, persona: DemoPersona):
    """The guard against a trim that quietly applied to everybody."""
    body = await _catalogue(client, persona.admin_headers)
    for field in (*GRADE_FIELDS, *SALARY_FIELDS):
        assert any(row[field] is not None for row in body["items"]), (
            f"{field} disappeared from the catalogue for an admin"
        )


# --- (c) the role x flag matrix, both cells for every role ----------------


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("code", GRADE_ROLES)
async def test_the_pair_reaches_every_grade_role_whatever_the_flag_says(
    client: AsyncClient,
    db: AsyncSession,
    persona: DemoPersona,
    role_headers,
    code: str,
    flag: bool,
):
    """Four cells the first pass left open, and one product decision.

    ``manager`` was only ever pinned for the bands, so swapping the rule for
    "the flag alone" would have emptied the catalogue for every division
    head with the suite still green. ``recruiter`` and ``hiring_manager``
    read the pair by decision — the requisition form fills its pickers from
    it — which is why this predicate is not ``is_employee_only()``.
    """
    await _show_grades(db, persona.tenant_id, flag)
    headers = await role_headers(code)
    body = await _catalogue(client, headers)
    assert any(row["grade_title"] for row in body["items"]), (
        f"{code} lost the grade with directory_show_grades={flag}"
    )
    assert any(row["specialization_title"] for row in body["items"])
    assert any(row["grades"] for row in body["items"]), (
        f"{code} lost the option pools the requisition form reads"
    )
    # The predicate that survives the field also has to survive for them.
    everything = await _catalogue(client, headers)
    narrowed = await _catalogue(client, headers, f"&grade_id={persona.grade_id}")
    assert narrowed["total"] < everything["total"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["recruiter", "hiring_manager"])
async def test_the_hiring_roles_read_the_pair_but_not_the_band(
    client: AsyncClient, persona: DemoPersona, role_headers, code: str
):
    """The two predicates carry different role sets — pin the gap itself.

    Expressing both through one helper would hand the bands to hiring the
    next time somebody tidied the two calls into one.
    """
    headers = await role_headers(code)
    body = await _catalogue(client, headers)
    assert any(row["grade_title"] for row in body["items"])
    for row in body["items"]:
        for field in SALARY_FIELDS:
            assert row[field] is None, f"{code} was handed {field}"

    ladder = await client.get(
        f"/api/specializations/{persona.spec_id}/grades", headers=headers
    )
    assert ladder.status_code == 200, ladder.text
    assert all(rung["salary_min"] is None for rung in ladder.json()), (
        f"{code} was handed the bands on the specialization page"
    )


@pytest.mark.asyncio
async def test_a_manager_keeps_the_band_the_hiring_roles_lose(
    client: AsyncClient, persona: DemoPersona, manager_headers: dict
):
    """The other side of the same gap, so neither role set can drift alone."""
    body = await _catalogue(client, manager_headers)
    assert any(row["salary_min"] is not None for row in body["items"])


@pytest.mark.asyncio
async def test_the_currency_leaves_with_the_band(
    client: AsyncClient, persona: DemoPersona
):
    """``salary_currency`` is dropped, not blanked — pin that it is dropped.

    ``SpecializationGradeRead.salary_currency`` is a bare ``str`` whose
    default factory refills it, so a rank-and-file caller sees the
    installation currency rather than the band's own. Without this the field
    could be dropped from the rule and nothing would fail.

    HRP-708: the demo seed quotes its bands in the installation currency
    like every other writer, so the divergence this test needs is written
    here rather than borrowed from a seed that happened to disagree.
    """
    from app.core.currency import installation_currency

    admin = await client.get(
        f"/api/specializations/{persona.spec_id}/grades",
        headers=persona.admin_headers,
    )
    assert admin.status_code == 200, admin.text
    banded = [r for r in admin.json() if r["salary_min"] is not None]
    assert banded, "no grade carries a band — the assertion below is vacuous"

    foreign = "JPY" if installation_currency() != "JPY" else "CHF"
    patched = await client.patch(
        f"/api/specializations/{persona.spec_id}/grades/{banded[0]['grade_id']}",
        json={"salary_currency": foreign},
        headers=persona.admin_headers,
    )
    assert patched.status_code == 200, patched.text

    admin = await client.get(
        f"/api/specializations/{persona.spec_id}/grades",
        headers=persona.admin_headers,
    )
    assert admin.status_code == 200, admin.text
    banded = [r for r in admin.json() if r["salary_min"] is not None]
    assert any(r["salary_currency"] != installation_currency() for r in banded), (
        "the band written in a foreign currency came back in the installation "
        "currency — this test cannot tell a dropped field from a kept one"
    )

    trimmed = await client.get(
        f"/api/specializations/{persona.spec_id}/grades", headers=persona.headers
    )
    assert trimmed.status_code == 200, trimmed.text
    assert all(
        r["salary_currency"] == installation_currency() for r in trimmed.json()
    ), "the band's own currency survived the trim"


# --- (d) one regression per route the sweep found open -------------------


@pytest.mark.asyncio
async def test_the_dictionary_usage_preview_is_admin_only(
    client: AsyncClient, persona: DemoPersona
):
    """The cheapest way around every guard above, and it touched no /positions.

    ``GET /dictionaries/grade`` hands any member every grade id, and this
    route answered, per id, the exact list of positions holding it — by
    title. Joined with ``position_title`` from the directory that is a
    colleague's grade in N+1 requests. It exists to warn an admin what a
    delete would break, and the delete is admin-only, so the preview is too.
    """
    grades = await client.get("/api/dictionaries/grade", headers=persona.headers)
    assert grades.status_code == 200, grades.text
    items = grades.json()
    assert items, "no grades in the dictionary — the walk below proves nothing"

    for item in items:
        resp = await client.get(
            f"/api/dictionaries/items/{item['id']}/usage", headers=persona.headers
        )
        assert resp.status_code == 403, (
            f"usage preview answered {resp.status_code} for a grade id: {resp.text}"
        )

    ok = await client.get(
        f"/api/dictionaries/items/{items[0]['id']}/usage",
        headers=persona.admin_headers,
    )
    assert ok.status_code == 200, ok.text
    assert "positions" in ok.json(), "the admin lost the preview this route is for"


@pytest.mark.asyncio
async def test_the_matrix_oracle_is_closed_on_both_sides(
    client: AsyncClient, persona: DemoPersona
):
    """Blanking the pair ids is not enough while a lookup keyed by one answers.

    ``/positions/{id}/competences`` still returns the competence set of the
    hidden pair. Comparing that set against ``/specializations/{id}/matrix
    ?grade_id=G``, one candidate grade at a time, named the grade exactly —
    the ids never had to appear. ``matrix-bulk`` carried the same mapping in
    one request, with ``grade_title`` attached.
    """
    bulk = await client.get(
        f"/api/specializations/{persona.spec_id}/matrix-bulk",
        headers=persona.headers,
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["grades"] == [], "matrix-bulk still maps grades to competences"

    probe = await client.get(
        f"/api/specializations/{persona.spec_id}/matrix?grade_id={persona.grade_id}",
        headers=persona.headers,
    )
    assert probe.status_code == 403, (
        f"the per-grade matrix lookup answered {probe.status_code}"
    )

    # Both stay open for the roles that build the matrix.
    for headers in (persona.admin_headers,):
        assert (
            await client.get(
                f"/api/specializations/{persona.spec_id}/matrix-bulk",
                headers=headers,
            )
        ).json()["grades"], "matrix-bulk went empty for an admin"
        assert (
            await client.get(
                f"/api/specializations/{persona.spec_id}/matrix"
                f"?grade_id={persona.grade_id}",
                headers=headers,
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_the_matrix_predicate_dies_with_its_field(
    client: AsyncClient, persona: DemoPersona
):
    """``matrix_configured`` is the hidden pair showing through a boolean."""
    body = await _catalogue(client, persona.headers)
    for row in body["items"]:
        assert row.get("matrix_configured") in (None, False), (
            "matrix_configured survived the trim"
        )

    everything = await _catalogue(client, persona.headers)
    for value in ("true", "false"):
        filtered = await _catalogue(
            client, persona.headers, f"&matrix_unconfigured={value}"
        )
        assert filtered["total"] == everything["total"], (
            f"?matrix_unconfigured={value} narrowed the catalogue"
        )

    # Still a working filter for the caller it was built for. Its result may
    # legitimately be empty (every position wired), so this one reads the
    # total directly rather than through the non-empty helper above.
    admin_all = await _catalogue(client, persona.admin_headers)
    resp = await client.get(
        "/api/positions?limit=200&matrix_unconfigured=true",
        headers=persona.admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] < admin_all["total"], (
        "matrix_unconfigured narrows nothing even for an admin — rewrite this"
    )


@pytest.mark.asyncio
async def test_the_division_scoped_chain_read_drops_its_bands(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """``/grade-system/divisions/{id}`` shares the helper but had no coverage.

    The demo seed maps no specialization to a division, so the route answers
    an empty list for everyone and would have passed on nothing. The mapping
    is created here to make the assertion mean something.
    """
    from app.modules.company.models import SpecializationDivision

    division_id = await db.scalar(
        select(Division.id).where(Division.tenant_id == persona.tenant_id)
    )
    assert division_id is not None
    db.add(
        SpecializationDivision(
            tenant_id=persona.tenant_id,
            division_id=division_id,
            specialization_id=persona.spec_id,
        )
    )
    await db.commit()

    url = f"/api/grade-system/divisions/{division_id}"
    admin = await client.get(url, headers=persona.admin_headers)
    assert admin.status_code == 200, admin.text
    assert any(c["salary_min"] is not None for c in admin.json()), (
        "no chain under this division carries a band — nothing to check"
    )

    trimmed = await client.get(url, headers=persona.headers)
    assert trimmed.status_code == 200, trimmed.text
    assert trimmed.json(), "the trimmed caller lost the chains entirely"
    assert all(c["salary_min"] is None for c in trimmed.json()), (
        "the division-scoped chain read still carries the bands"
    )
