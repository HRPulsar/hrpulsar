"""HRP-380: public API read endpoints (/v1/specializations, /v1/grades,
/v1/dictionaries/{item_type}) must serialize the tenant-effective
``is_active`` — a System (origin) item deactivated by the tenant via
``dictionary_item_tenant_overrides`` (HRP-285/HRP-337) must not surface to
integrations as ``"is_active": true``.
"""

import uuid

from app.modules.company.models import Tenant
from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import DictionaryItemUpdate
from app.modules.public_api import service as public_api_service


async def _make_origin_item(db, item_type, title):
    item = DictionaryItem(type=item_type, title=title, sort_index=0, tenant_id=None)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _api_key(db, tenant_id, user_id):
    created = await public_api_service.create_api_key(
        db, tenant_id, user_id, f"HRP380 {uuid.uuid4().hex[:6]}"
    )
    return created["key"]


async def _fetch_item(client, path, api_key, item_id):
    """Page through a public API list endpoint until item_id is found.

    The shared test DB accumulates dictionary rows from other tests, so the
    target item is not guaranteed to land on the first page.
    """
    skip = 0
    while True:
        resp = await client.get(
            f"{path}?skip={skip}&limit=100", headers={"X-API-Key": api_key}
        )
        assert resp.status_code == 200
        data = resp.json()
        for it in data["items"]:
            if it["id"] == str(item_id):
                return it
        skip += 100
        if skip >= data["total"]:
            return None


class TestHRP380PublicAPIEffectiveActive:
    async def test_specializations_show_effective_flag(self, db, client, tenant, user):
        origin = await _make_origin_item(
            db, "specialization", "HRP380 Spec Deactivated"
        )
        await dictionary_service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )
        key = await _api_key(db, tenant.id, user.id)

        item = await _fetch_item(client, "/api/v1/specializations", key, origin.id)
        assert item is not None
        assert item["is_active"] is False

        # The shared origin row itself stays untouched.
        await db.refresh(origin)
        assert origin.is_active is True

    async def test_grades_show_effective_flag(self, db, client, tenant, user):
        origin = await _make_origin_item(db, "grade", "HRP380 Grade Deactivated")
        await dictionary_service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )
        key = await _api_key(db, tenant.id, user.id)

        item = await _fetch_item(client, "/api/v1/grades", key, origin.id)
        assert item is not None
        assert item["is_active"] is False
        assert item["sort_index"] == 0

    async def test_dictionaries_override_scoped_to_its_tenant(
        self, db, client, tenant, user
    ):
        origin = await _make_origin_item(db, "specialization", "HRP380 Scoped Spec")
        await dictionary_service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=False)
        )

        other = Tenant(
            name=f"Other Co HRP380 {uuid.uuid4().hex[:6]}",
            slug=f"other-hrp380-{uuid.uuid4().hex[:8]}",
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        deactivating_key = await _api_key(db, tenant.id, user.id)
        # create_api_key does not check user membership; reusing the first
        # tenant's user keeps the fixture small — only tenant_id matters here.
        other_key = await _api_key(db, other.id, user.id)

        path = "/api/v1/dictionaries/specialization"
        item = await _fetch_item(client, path, deactivating_key, origin.id)
        assert item is not None
        assert item["is_active"] is False

        other_item = await _fetch_item(client, path, other_key, origin.id)
        assert other_item is not None
        assert other_item["is_active"] is True

    async def test_custom_item_unaffected(self, db, client, tenant, user):
        custom = DictionaryItem(
            type="specialization",
            title="HRP380 Custom Active",
            sort_index=0,
            tenant_id=tenant.id,
        )
        db.add(custom)
        await db.commit()
        await db.refresh(custom)
        key = await _api_key(db, tenant.id, user.id)

        item = await _fetch_item(client, "/api/v1/specializations", key, custom.id)
        assert item is not None
        assert item["is_active"] is True
