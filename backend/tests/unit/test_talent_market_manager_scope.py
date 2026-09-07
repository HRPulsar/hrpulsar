"""HRP-639: a division head owns their own talent cards, not the board.

Eighteen mutating routes stood on ``require_role("admin", "manager")``
with nothing asking whose card it was, so a head of one department could
publish, re-scope, close and staff another's. Reading was as open: a
manager with a subtree got no list filter at all and saw every
department's drafts.
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
from app.modules.employee.models import Employee
from app.modules.talent_market.models import TalentCandidate, TalentCard
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


@pytest_asyncio.fixture
async def board(db: AsyncSession, tenant) -> dict:
    """One card per division, each with a candidate; plus one published."""
    mgr_user = await _user(db, tenant, "manager")
    lonely_user = await _user(db, tenant, "manager")
    admin_user = await _user(db, tenant, "admin")

    mgr_emp = Employee(
        user_id=mgr_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    lonely_emp = Employee(
        user_id=lonely_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    db.add_all([mgr_emp, lonely_emp])
    await db.commit()
    await db.refresh(mgr_emp)
    await db.refresh(lonely_emp)

    mine = Division(
        tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}", manager_id=mgr_emp.id
    )
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    await db.refresh(mine)
    await db.refresh(theirs)

    out: dict = {
        "mgr_user": mgr_user,
        "lonely_user": lonely_user,
        "admin_user": admin_user,
        "mine_division": mine,
        "theirs_division": theirs,
    }
    for key, division in (("mine", mine), ("theirs", theirs)):
        emp_user = await _user(db, tenant, "employee")
        emp = Employee(
            user_id=emp_user.id,
            tenant_id=tenant.id,
            division_id=division.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        card = TalentCard(
            tenant_id=tenant.id,
            title=f"{key} card",
            card_type="vacancy",
            author_id=admin_user.id,
            division_id=division.id,
            start_date=date(2026, 1, 1),
        )
        db.add(card)
        await db.commit()
        await db.refresh(card)

        candidate = TalentCandidate(card_id=card.id, employee_id=emp.id)
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

        out[f"{key}_employee"] = emp
        out[f"{key}_card"] = card
        out[f"{key}_candidate"] = candidate

    published = TalentCard(
        tenant_id=tenant.id,
        title="published elsewhere",
        card_type="vacancy",
        author_id=admin_user.id,
        division_id=theirs.id,
        start_date=date(2026, 1, 1),
        status="published",
        is_published=True,
    )
    db.add(published)
    await db.commit()
    await db.refresh(published)
    out["published_card"] = published
    return out


def _mutations(b: dict, side: str) -> list[tuple[str, str, dict | None]]:
    card = b[f"{side}_card"].id
    emp = b[f"{side}_employee"].id
    cand = b[f"{side}_candidate"].id
    link = uuid.uuid4()
    return [
        ("put", f"/api/talent-market/{card}", {"title": "renamed"}),
        ("post", f"/api/talent-market/{card}/publish", None),
        ("post", f"/api/talent-market/{card}/complete", None),
        ("post", f"/api/talent-market/{card}/cancel", None),
        ("post", f"/api/talent-market/{card}/requirements", {"title": "req"}),
        (
            "post",
            f"/api/talent-market/{card}/required-specializations",
            {"specialization_id": str(uuid.uuid4())},
        ),
        (
            "put",
            f"/api/talent-market/{card}/required-specializations/{link}",
            {"min_experience_years": 1},
        ),
        ("delete", f"/api/talent-market/{card}/required-specializations/{link}", None),
        (
            "post",
            f"/api/talent-market/{card}/required-competences",
            {"items": []},
        ),
        (
            "put",
            f"/api/talent-market/{card}/required-competences/{link}",
            {"skill_level_id": str(uuid.uuid4())},
        ),
        ("delete", f"/api/talent-market/{card}/required-competences/{link}", None),
        ("get", f"/api/talent-market/{card}/candidate-pool", None),
        (
            "post",
            f"/api/talent-market/{card}/candidates",
            {"employee_id": str(emp)},
        ),
        (
            "post",
            f"/api/talent-market/{card}/candidates/bulk",
            {"employee_ids": [str(emp)]},
        ),
        ("post", f"/api/talent-market/{card}/candidates/{cand}/appoint", None),
        ("delete", f"/api/talent-market/{card}/candidates/{emp}", None),
        ("post", f"/api/talent-market/{card}/recompute", None),
    ]


async def _call(client: AsyncClient, method: str, path: str, body, headers) -> int:
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return (await getattr(client, method)(path, **kwargs)).status_code


class TestManagerTalentCardScope:
    async def test_manager_refused_on_a_neighbouring_division(
        self, client: AsyncClient, board
    ):
        h = _headers(board["mgr_user"])
        for method, path, body in _mutations(board, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_manager_passes_the_fence_on_their_own_division(
        self, client: AsyncClient, board
    ):
        h = _headers(board["mgr_user"])
        for method, path, body in _mutations(board, "mine"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_manager_without_subordinates_is_refused(
        self, client: AsyncClient, board
    ):
        h = _headers(board["lonely_user"])
        for side in ("mine", "theirs"):
            for method, path, body in _mutations(board, side):
                code = await _call(client, method, path, body, h)
                assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_admin_keeps_the_whole_board(self, client: AsyncClient, board):
        h = _headers(board["admin_user"])
        for method, path, body in _mutations(board, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_a_card_cannot_be_filed_into_another_division(
        self, client: AsyncClient, board
    ):
        h = _headers(board["mgr_user"])
        payload = {
            "title": "Smuggled",
            "card_type": "vacancy",
            "division_id": str(board["theirs_division"].id),
        }
        assert (
            await client.post("/api/talent-market", headers=h, json=payload)
        ).status_code == 403

        payload["division_id"] = str(board["mine_division"].id)
        created = await client.post("/api/talent-market", headers=h, json=payload)
        assert created.status_code == 201, created.text

        # …nor moved there afterwards, which authorship would otherwise allow.
        moved = await client.put(
            f"/api/talent-market/{created.json()['id']}",
            headers=h,
            json={"division_id": str(board["theirs_division"].id)},
        )
        assert moved.status_code == 403

    async def test_author_keeps_a_card_with_no_division(
        self, client: AsyncClient, board
    ):
        h = _headers(board["mgr_user"])
        created = await client.post(
            "/api/talent-market",
            headers=h,
            json={"title": "Unfiled", "card_type": "vacancy"},
        )
        assert created.status_code == 201, created.text
        assert (
            await _call(
                client,
                "put",
                f"/api/talent-market/{created.json()['id']}",
                {"title": "still mine"},
                h,
            )
            == 200
        )


class TestTalentBoardReads:
    async def test_the_list_hides_another_division_draft(
        self, client: AsyncClient, board
    ):
        resp = await client.post(
            "/api/talent-market/search",
            headers=_headers(board["mgr_user"]),
            json={},
        )
        assert resp.status_code == 200, resp.text
        ids = {c["id"] for c in resp.json()["items"]}
        assert str(board["mine_card"].id) in ids
        assert str(board["published_card"].id) in ids, "published cards stay public"
        assert str(board["theirs_card"].id) not in ids

    async def test_the_detail_hides_another_division_draft(
        self, client: AsyncClient, board
    ):
        h = _headers(board["mgr_user"])
        assert (
            await _call(
                client, "get", f"/api/talent-market/{board['theirs_card'].id}", None, h
            )
            == 404
        )
        assert (
            await _call(
                client, "get", f"/api/talent-market/{board['mine_card'].id}", None, h
            )
            == 200
        )
        assert (
            await _call(
                client,
                "get",
                f"/api/talent-market/{board['published_card'].id}",
                None,
                h,
            )
            == 200
        )

    async def test_admin_still_sees_every_draft(self, client: AsyncClient, board):
        resp = await client.post(
            "/api/talent-market/search",
            headers=_headers(board["admin_user"]),
            json={},
        )
        ids = {c["id"] for c in resp.json()["items"]}
        assert {
            str(board["mine_card"].id),
            str(board["theirs_card"].id),
        } <= ids


class TestEveryMutatingRouteCarriesAGuard:
    """A card route added later cannot quietly reopen this fence."""

    # `react` derives the candidate from the viewer's own employee record
    # and the service refuses anyone without a TalentCandidate row, so the
    # card id in the URL grants nothing; `delete_card` is admin-only;
    # `search` is a read that happens to be a POST — it carries the board's
    # own read filter instead. HRP-714's plan request is `react`'s twin:
    # employee-facing, acting only on the caller's own candidate row, and
    # a manager scope would lock the employee out of their own card.
    EXEMPT = {
        "react_to_card",
        "request_development_plan",
        "delete_card",
        "search_cards",
    }

    def test_no_unguarded_mutation(self):
        unguarded = []
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            module = getattr(endpoint, "__module__", "")
            if module != "app.modules.talent_market.router":
                continue
            if not getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}:
                continue
            if endpoint.__name__ in self.EXEMPT:
                continue
            names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
            if "card_scope" in names:
                continue
            if "assert_division_in_scope" in inspect.getsource(endpoint):
                continue
            unguarded.append(f"{sorted(route.methods)} {route.path}")
        assert not unguarded, f"talent-market mutations without a scope: {unguarded}"
