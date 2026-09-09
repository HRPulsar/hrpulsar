"""HRP-571: a child department's mapped specializations reach the parent.

The Specializations tiles on a division page count employees across the
whole subtree (HRP-58), but the mapped catalogue behind them came from
the division's own rows. A specialization therefore only surfaced
through somebody who held it, so a child department that was mapped and
not yet staffed showed nothing at all — the mapping existed and the org
chart above it stayed blank.

``include_sub_divisions`` is the same widening the employee list already
takes, and the flag is off by default so the mapping-management calls
keep answering about one division.
"""

from __future__ import annotations

import uuid

from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate, SpecializationDivisionCreate
from app.modules.dictionary.models import DictionaryItem
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _spec(db: AsyncSession, tenant_id: uuid.UUID, title: str) -> DictionaryItem:
    item = DictionaryItem(type="specialization", title=title, tenant_id=tenant_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _tree(db: AsyncSession, tenant) -> dict:
    """Engineering -> QA -> QA Automation; only the leaf is mapped, and
    nobody works there yet."""
    root = await company_service.create_division(
        db, tenant.id, DivisionCreate(name="Engineering")
    )
    mid = await company_service.create_division(
        db, tenant.id, DivisionCreate(name="QA", parent_id=root["id"])
    )
    leaf = await company_service.create_division(
        db, tenant.id, DivisionCreate(name="QA Automation", parent_id=mid["id"])
    )
    spec = await _spec(db, tenant.id, "QA Automation Engineer")
    await company_service.add_division_specialization(
        db,
        tenant.id,
        leaf["id"],
        SpecializationDivisionCreate(specialization_id=spec.id),
    )
    return {"root": root, "mid": mid, "leaf": leaf, "spec": spec}


class TestDivisionSpecializationSubtree:
    async def test_empty_child_hands_its_mapping_to_the_parent(
        self, db: AsyncSession, tenant
    ):
        t = await _tree(db, tenant)
        items = await company_service.list_division_specializations(
            db, tenant.id, t["root"]["id"], include_sub_divisions=True
        )
        assert [i["specialization_id"] for i in items] == [t["spec"].id]
        # The row names where the mapping actually lives, so the page can
        # narrow back to the division itself without a second request.
        assert items[0]["division_id"] == t["leaf"]["id"]

    async def test_the_default_still_answers_about_one_division(
        self, db: AsyncSession, tenant
    ):
        t = await _tree(db, tenant)
        assert (
            await company_service.list_division_specializations(
                db, tenant.id, t["root"]["id"]
            )
            == []
        )
        own = await company_service.list_division_specializations(
            db, tenant.id, t["leaf"]["id"]
        )
        assert [i["specialization_id"] for i in own] == [t["spec"].id]

    async def test_a_sibling_branch_is_not_pulled_in(
        self, db: AsyncSession, tenant
    ):
        t = await _tree(db, tenant)
        sales = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Sales")
        )
        other = await _spec(db, tenant.id, "Account Executive")
        await company_service.add_division_specialization(
            db,
            tenant.id,
            sales["id"],
            SpecializationDivisionCreate(specialization_id=other.id),
        )
        items = await company_service.list_division_specializations(
            db, tenant.id, t["root"]["id"], include_sub_divisions=True
        )
        assert [i["specialization_id"] for i in items] == [t["spec"].id]

    async def test_the_url_the_division_page_calls(
        self, auth_client: AsyncClient, db: AsyncSession, tenant
    ):
        """Pins the query the frontend sends, verbatim."""
        t = await _tree(db, tenant)
        res = await auth_client.get(
            f"/api/divisions/{t['root']['id']}/specializations"
            "?include_sub_divisions=true"
        )
        assert res.status_code == 200, res.text
        assert [i["specialization_id"] for i in res.json()] == [str(t["spec"].id)]
