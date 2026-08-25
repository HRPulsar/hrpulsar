"""HRP-631: catalogues become HR's, positions stay the division head's.

`Competence`, `CompetenceGroup`, `Indicator`, `Material` and `AnswerScale`
carry only `tenant_id` — no division, no owner, nothing to scope a manager
to — so the head of a three-person department was renaming, deactivating
and re-parenting rows the whole company works from. Those mutations moved
to `admin` / `hr`.

`Position` is the exception: it has `division_id`, so a manager keeps the
role and gains a fence instead.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.competence.models import Competence, CompetenceGroup, Indicator
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _user(db: AsyncSession, tenant, code: str) -> User:
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
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


async def _call(client: AsyncClient, method: str, path: str, body, headers) -> int:
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return (await getattr(client, method)(path, **kwargs)).status_code


@pytest_asyncio.fixture
async def catalogue(db: AsyncSession, tenant, skill_levels) -> dict:
    """One competence group, competence and indicator; two divisions with a
    position each; a manager of one of them, an HR and an admin."""
    mgr_user = await _user(db, tenant, "manager")
    hr_user = await _user(db, tenant, "hr")
    admin_user = await _user(db, tenant, "admin")

    mgr_emp = Employee(
        user_id=mgr_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    db.add(mgr_emp)
    await db.commit()
    await db.refresh(mgr_emp)

    mine = Division(
        tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}", manager_id=mgr_emp.id
    )
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    await db.refresh(mine)
    await db.refresh(theirs)

    group = CompetenceGroup(title=f"G-{uuid.uuid4().hex[:6]}", tenant_id=tenant.id)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    competence = Competence(
        title=f"C-{uuid.uuid4().hex[:6]}", group_id=group.id, tenant_id=tenant.id
    )
    db.add(competence)
    await db.commit()
    await db.refresh(competence)
    indicator = Indicator(
        title=f"I-{uuid.uuid4().hex[:6]}",
        competence_id=competence.id,
        skill_level_id=skill_levels["Basic"].id,
        tenant_id=tenant.id,
    )
    db.add(indicator)
    await db.commit()
    await db.refresh(indicator)

    out: dict = {
        "mgr_user": mgr_user,
        "hr_user": hr_user,
        "admin_user": admin_user,
        "mine_division": mine,
        "theirs_division": theirs,
        "group": group,
        "competence": competence,
        "indicator": indicator,
    }
    for key, division in (("mine", mine), ("theirs", theirs)):
        pos = Position(
            tenant_id=tenant.id,
            title=f"{key} role {uuid.uuid4().hex[:4]}",
            division_id=division.id,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)
        out[f"{key}_position"] = pos
    return out


def _catalogue_mutations(c: dict) -> list[tuple[str, str, dict | None]]:
    group, comp, ind = c["group"].id, c["competence"].id, c["indicator"].id
    return [
        ("post", "/api/competence-groups", {"title": "G"}),
        ("put", f"/api/competence-groups/{group}", {"title": "G2"}),
        ("patch", f"/api/competence-groups/{group}/activate", None),
        ("patch", f"/api/competence-groups/{group}/deactivate", None),
        ("post", f"/api/competence-groups/{group}/move", {"parent_id": None}),
        ("post", "/api/competences", {"title": "C", "group_id": str(group)}),
        ("put", f"/api/competences/{comp}", {"title": "C2"}),
        ("post", f"/api/competences/{comp}/publish", None),
        ("post", f"/api/competences/{comp}/unpublish", None),
        ("patch", f"/api/competences/{comp}/activate", None),
        ("patch", f"/api/competences/{comp}/deactivate", None),
        ("post", f"/api/competences/{comp}/move", {"group_id": str(group)}),
        ("post", f"/api/competences/{comp}/indicators", {"title": "I"}),
        ("put", f"/api/indicators/{ind}", {"title": "I2"}),
        ("patch", f"/api/indicators/{ind}/activate", None),
        ("patch", f"/api/indicators/{ind}/deactivate", None),
        ("post", f"/api/indicators/{ind}/move", {"competence_id": str(comp)}),
        ("post", f"/api/competences/{comp}/materials", {"title": "M"}),
        ("post", "/api/answer-scales", {"title": "S", "options": []}),
        ("post", "/api/ai/generate-competences", {"specialization": "QA"}),
        ("post", "/api/ai/generate-indicators", {"competence_title": "QA"}),
    ]


class TestCatalogueBelongsToHr:
    async def test_manager_is_refused_across_the_catalogue(
        self, client: AsyncClient, catalogue
    ):
        h = _headers(catalogue["mgr_user"])
        for method, path, body in _catalogue_mutations(catalogue):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_hr_passes_the_gate_everywhere_the_manager_used_to(
        self, client: AsyncClient, catalogue
    ):
        h = _headers(catalogue["hr_user"])
        for method, path, body in _catalogue_mutations(catalogue):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_admin_keeps_the_catalogue(self, client: AsyncClient, catalogue):
        h = _headers(catalogue["admin_user"])
        for method, path, body in _catalogue_mutations(catalogue):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_the_grade_ladder_and_matrices_move_with_it(
        self, client: AsyncClient, catalogue
    ):
        spec = uuid.uuid4()
        routes = [
            ("post", f"/api/specializations/{spec}/grades", {"grade_ids": []}),
            ("patch", f"/api/specializations/{spec}/grades/reorder", {"grade_ids": []}),
            (
                "patch",
                f"/api/specializations/{spec}/grades/{uuid.uuid4()}",
                {"salary_min": 1},
            ),
            ("delete", f"/api/specializations/{spec}/grades/{uuid.uuid4()}", None),
            (
                "put",
                f"/api/specializations/{spec}/matrix",
                {"grade_id": str(uuid.uuid4()), "competence_ids": []},
            ),
            ("put", f"/api/specializations/{spec}/matrix-bulk", {"rows": []}),
        ]
        for method, path, body in routes:
            assert (
                await _call(client, method, path, body, _headers(catalogue["mgr_user"]))
                == 403
            ), f"{method.upper()} {path}"
            assert (
                await _call(client, method, path, body, _headers(catalogue["hr_user"]))
                != 403
            ), f"{method.upper()} {path}"

    async def test_the_catalogue_stays_readable_for_a_manager(
        self, client: AsyncClient, catalogue
    ):
        """Only the writes moved — a manager still builds assessments on it."""
        h = _headers(catalogue["mgr_user"])
        for path in (
            "/api/competence-tree",
            f"/api/competences/{catalogue['competence'].id}",
            "/api/answer-scales",
            "/api/specializations",
        ):
            assert (await client.get(path, headers=h)).status_code == 200, path


class TestPositionsStayWithTheDivisionHead:
    def _mutations(self, c: dict, side: str) -> list[tuple[str, str, dict | None]]:
        pos = c[f"{side}_position"].id
        return [
            ("put", f"/api/positions/{pos}", {"title": "renamed"}),
            ("post", f"/api/positions/{pos}/status", {"lifecycle_status": "on_hold"}),
            ("post", f"/api/positions/{pos}/deactivate", None),
            (
                "post",
                "/api/positions/bulk-action",
                {"ids": [str(pos)], "action": "approve"},
            ),
        ]

    async def test_manager_edits_their_own_division(
        self, client: AsyncClient, catalogue
    ):
        h = _headers(catalogue["mgr_user"])
        for method, path, body in self._mutations(catalogue, "mine"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_manager_is_refused_on_another_division(
        self, client: AsyncClient, catalogue
    ):
        h = _headers(catalogue["mgr_user"])
        for method, path, body in self._mutations(catalogue, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_admin_edits_both(self, client: AsyncClient, catalogue):
        h = _headers(catalogue["admin_user"])
        for method, path, body in self._mutations(catalogue, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_a_new_position_lands_in_the_managers_own_division(
        self, client: AsyncClient, catalogue
    ):
        h = _headers(catalogue["mgr_user"])
        base = {"title": f"New {uuid.uuid4().hex[:6]}"}
        assert (
            await _call(
                client,
                "post",
                "/api/positions",
                {**base, "division_id": str(catalogue["theirs_division"].id)},
                h,
            )
            == 403
        )
        # A position with no division belongs to nobody's subtree, so a
        # scoped caller cannot file one either.
        assert await _call(client, "post", "/api/positions", base, h) == 403
        assert (
            await _call(
                client,
                "post",
                "/api/positions",
                {**base, "division_id": str(catalogue["mine_division"].id)},
                h,
            )
            == 201
        )

    async def test_a_position_cannot_be_moved_out_of_the_subtree(
        self, client: AsyncClient, catalogue
    ):
        assert (
            await _call(
                client,
                "put",
                f"/api/positions/{catalogue['mine_position'].id}",
                {"division_id": str(catalogue["theirs_division"].id)},
                _headers(catalogue["mgr_user"]),
            )
            == 403
        )

    async def test_the_payload_tells_the_ui_which_rows_are_editable(
        self, client: AsyncClient, catalogue
    ):
        """A button that 403s is a regression (HRP-622's rule)."""
        rows = (
            await client.get(
                "/api/positions?limit=200", headers=_headers(catalogue["mgr_user"])
            )
        ).json()["items"]
        by_id = {r["id"]: r["can_manage"] for r in rows}
        assert by_id[str(catalogue["mine_position"].id)] is True
        assert by_id[str(catalogue["theirs_position"].id)] is False

        admin_rows = (
            await client.get(
                "/api/positions?limit=200", headers=_headers(catalogue["admin_user"])
            )
        ).json()["items"]
        assert all(r["can_manage"] for r in admin_rows)


class TestEveryMutatingPositionRouteCarriesAGuard:
    """A position route added later cannot quietly reopen the subtree fence."""

    EXEMPT = {"delete_position"}  # admin-only

    def test_no_unguarded_mutation(self):
        unguarded = []
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            if getattr(endpoint, "__module__", "") != "app.modules.position.router":
                continue
            if not getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}:
                continue
            if endpoint.__name__ in self.EXEMPT:
                continue
            names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
            if "position_scope" in names:
                continue
            source = inspect.getsource(endpoint)
            if (
                "assert_division_in_scope" in source
                or "assert_positions_in_scope" in source
            ):
                continue
            unguarded.append(f"{sorted(route.methods)} {route.path}")
        assert not unguarded, f"position mutations without a scope: {unguarded}"
