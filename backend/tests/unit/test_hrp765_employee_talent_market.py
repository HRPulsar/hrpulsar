"""HRP-765: the Talent Market section is an employee surface again.

The menu entry was admin/manager-only, so the one role the board is
about could not open it. The API side was already scoped but scoped
twice — the list route and the detail route each carried their own copy
of the rule and had already drifted (a role-employee user without an
Employee row read every published card from the list and got 404 on the
same card's detail). Both now ask
``talent_market.scope.employee_read_filter``:

(a) candidate on a card that has left Draft, or
(b) candidate as ``appointed`` — the card's own status then does not
    matter, because that is a pre-publish nomination.

Anything else is 404, the way this module hides a card. And the payload
carries the viewer's own row only: an employee reads the card for their
own sake, not to see the shortlist they are ranked in.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
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
    """Four cards around one employee, one per branch of the rule."""
    author = await _user(db, tenant, "admin")
    emp_user = await _user(db, tenant, "employee")
    other_user = await _user(db, tenant, "employee")
    stranger_user = await _user(db, tenant, "employee")

    emp = Employee(user_id=emp_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    other = Employee(
        user_id=other_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    db.add_all([emp, other])
    await db.commit()
    await db.refresh(emp)
    await db.refresh(other)

    def _card(title: str, status: str) -> TalentCard:
        return TalentCard(
            tenant_id=tenant.id,
            title=title,
            card_type="vacancy",
            author_id=author.id,
            start_date=date(2026, 1, 1),
            status=status,
            is_published=status == "published",
            published_at=(
                datetime.now(timezone.utc) if status == "published" else None
            ),
        )

    published = _card("published, I am on it", "published")
    draft_appointed = _card("draft, I am appointed", "draft")
    draft_nominated = _card("draft, I am only nominated", "draft")
    published_elsewhere = _card("published, not my card", "published")
    db.add_all([published, draft_appointed, draft_nominated, published_elsewhere])
    await db.commit()
    for c in (published, draft_appointed, draft_nominated, published_elsewhere):
        await db.refresh(c)

    db.add_all(
        [
            TalentCandidate(
                card_id=published.id, employee_id=emp.id, status="matched"
            ),
            # A colleague on the same card — the employee must not read them.
            TalentCandidate(
                card_id=published.id, employee_id=other.id, status="matched"
            ),
            TalentCandidate(
                card_id=draft_appointed.id, employee_id=emp.id, status="appointed"
            ),
            TalentCandidate(
                card_id=draft_nominated.id, employee_id=emp.id, status="matched"
            ),
            TalentCandidate(
                card_id=published_elsewhere.id, employee_id=other.id, status="matched"
            ),
        ]
    )
    await db.commit()

    return {
        "emp_user": emp_user,
        "emp": emp,
        "other": other,
        # `stranger_user` carries the employee role and no Employee row —
        # the case the two copies of the rule used to answer differently.
        "stranger_user": stranger_user,
        "published": published,
        "draft_appointed": draft_appointed,
        "draft_nominated": draft_nominated,
        "published_elsewhere": published_elsewhere,
    }


async def _list_ids(client: AsyncClient, user: User) -> set[str]:
    res = await client.post(
        "/api/talent-market/search", headers=_headers(user), json={"limit": 50}
    )
    assert res.status_code == 200, res.text
    return {item["id"] for item in res.json()["items"]}


class TestEmployeeTalentMarketAccess:
    async def test_list_shows_published_and_appointed_only(
        self, client: AsyncClient, board
    ):
        ids = await _list_ids(client, board["emp_user"])
        assert str(board["published"].id) in ids
        assert str(board["draft_appointed"].id) in ids
        assert str(board["draft_nominated"].id) not in ids
        assert str(board["published_elsewhere"].id) not in ids

    async def test_detail_opens_on_both_visible_branches(
        self, client: AsyncClient, board
    ):
        h = _headers(board["emp_user"])
        for key in ("published", "draft_appointed"):
            res = await client.get(f"/api/talent-market/{board[key].id}", headers=h)
            assert res.status_code == 200, f"{key} -> {res.status_code}"
            # Read-only: the UI hides every managing action behind this.
            assert res.json()["can_manage"] is False

    async def test_detail_refuses_a_draft_without_an_appointment(
        self, client: AsyncClient, board
    ):
        res = await client.get(
            f"/api/talent-market/{board['draft_nominated'].id}",
            headers=_headers(board["emp_user"]),
        )
        assert res.status_code == 404

    async def test_detail_refuses_a_card_the_employee_is_not_on(
        self, client: AsyncClient, board
    ):
        res = await client.get(
            f"/api/talent-market/{board['published_elsewhere'].id}",
            headers=_headers(board["emp_user"]),
        )
        assert res.status_code == 404

    async def test_the_employee_reads_their_own_row_only(
        self, client: AsyncClient, board
    ):
        res = await client.get(
            f"/api/talent-market/{board['published'].id}",
            headers=_headers(board["emp_user"]),
        )
        assert res.status_code == 200, res.text
        candidates = res.json()["candidates"]
        assert [c["employee_id"] for c in candidates] == [str(board["emp"].id)]
        assert candidates[0]["is_me"] is True

    async def test_the_match_breakdown_answers_only_for_readable_cards(
        self, client: AsyncClient, board
    ):
        """The drawer behind the Match cell used to check only "is this row
        mine": the employee's own id plus any card id read that card's
        requirements, levels, specializations and threshold — a draft they
        were never on included."""
        h = _headers(board["emp_user"])
        emp_id = board["emp"].id

        ok = await client.get(
            f"/api/talent-market/{board['published'].id}/candidates/{emp_id}/breakdown",
            headers=h,
        )
        assert ok.status_code == 200, ok.text

        for key in ("draft_nominated", "published_elsewhere"):
            res = await client.get(
                f"/api/talent-market/{board[key].id}/candidates/{emp_id}/breakdown",
                headers=h,
            )
            assert res.status_code == 404, f"{key} -> {res.status_code}"

    async def test_the_breakdown_still_refuses_a_colleagues_row(
        self, client: AsyncClient, board
    ):
        """The older rule stands on a card the employee may read."""
        res = await client.get(
            f"/api/talent-market/{board['published'].id}"
            f"/candidates/{board['other'].id}/breakdown",
            headers=_headers(board["emp_user"]),
        )
        assert res.status_code == 403

    async def test_a_user_without_an_employee_row_sees_nothing(
        self, client: AsyncClient, board
    ):
        """List and detail used to disagree here — the list handed over
        every published card, the detail route refused the same card."""
        assert await _list_ids(client, board["stranger_user"]) == set()
        res = await client.get(
            f"/api/talent-market/{board['published'].id}",
            headers=_headers(board["stranger_user"]),
        )
        assert res.status_code == 404
