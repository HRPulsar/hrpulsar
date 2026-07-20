"""HRP-285: tenants can flip ``is_active`` on origin (Source=System)
dictionary items. The override lives in
``dictionary_item_tenant_overrides`` so it never mutates the shared
origin row, and only ``is_active`` is overridable — every other field
stays frozen for tenants.
"""

import pytest
from app.modules.dictionary import service
from app.modules.dictionary.models import (
    DictionaryItem,
    DictionaryItemTenantOverride,
)
from app.modules.dictionary.schemas import DictionaryItemUpdate
from fastapi import HTTPException
from sqlalchemy import select


class TestHRP285OriginOverride:
    async def _make_origin(self, db, title="Origin Grade", item_type="grade"):
        item = DictionaryItem(
            type=item_type, title=title, sort_index=0, tenant_id=None
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def test_deactivate_origin_writes_override_row(self, db, tenant):
        origin = await self._make_origin(db, title="OriginA")

        result = await service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )
        assert result["is_active"] is False

        row = (
            await db.execute(
                select(DictionaryItemTenantOverride).where(
                    DictionaryItemTenantOverride.item_id == origin.id,
                    DictionaryItemTenantOverride.tenant_id == tenant.id,
                )
            )
        ).scalar_one()
        assert row.is_active is False

        # Shared origin row must not be touched.
        await db.refresh(origin)
        assert origin.is_active is True

    async def test_reactivate_origin_upserts_override(self, db, tenant):
        origin = await self._make_origin(db, title="OriginB")

        await service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )
        await service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=True)
        )

        row = (
            await db.execute(
                select(DictionaryItemTenantOverride).where(
                    DictionaryItemTenantOverride.item_id == origin.id,
                    DictionaryItemTenantOverride.tenant_id == tenant.id,
                )
            )
        ).scalar_one()
        assert row.is_active is True

    async def test_override_isolated_per_tenant(self, db, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Co", slug="other-co-hrp285")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        origin = await self._make_origin(db, title="OriginC")

        await service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )

        listed_self = await service.list_items(db, tenant.id, "grade")
        listed_other = await service.list_items(db, other.id, "grade")

        self_row = next(i for i in listed_self if i["id"] == origin.id)
        other_row = next(i for i in listed_other if i["id"] == origin.id)
        assert self_row["is_active"] is False
        assert other_row["is_active"] is True

    async def test_origin_other_fields_remain_forbidden(self, db, tenant):
        origin = await self._make_origin(db, title="OriginD")
        with pytest.raises(HTTPException) as exc:
            await service.update_item(
                db, tenant.id, origin.id, DictionaryItemUpdate(title="Renamed")
            )
        assert exc.value.status_code == 403

    async def test_origin_combined_payload_still_forbidden(self, db, tenant):
        origin = await self._make_origin(db, title="OriginE")
        with pytest.raises(HTTPException) as exc:
            await service.update_item(
                db,
                tenant.id,
                origin.id,
                DictionaryItemUpdate(title="Renamed", is_active=False),
            )
        assert exc.value.status_code == 403

    async def test_get_item_reflects_override(self, db, tenant):
        origin = await self._make_origin(db, title="OriginF")
        await service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )
        view = await service.get_item(db, tenant.id, origin.id)
        assert view["is_active"] is False
        assert view["tenant_id"] is None  # source still System
