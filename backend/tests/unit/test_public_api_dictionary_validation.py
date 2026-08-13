"""HRP-382: `/v1/dictionaries/{item_type}` must reject an unknown type.

Before this, any string reached the query and matched nothing, so an
integration with a typo got ``200 {"items": [], "total": 0}`` — identical
to a tenant that legitimately has no items of that type.
"""

import uuid

import pytest
from app.main import app
from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import VALID_TYPES
from app.modules.public_api import service as public_api_service
from fastapi import HTTPException

DICTIONARIES_PATH = "/api/v1/dictionaries/{item_type}"


async def _api_key(db, tenant_id, user_id):
    created = await public_api_service.create_api_key(
        db, tenant_id, user_id, f"HRP382 {uuid.uuid4().hex[:6]}"
    )
    return created["key"]


class TestPublicDictionaryTypeValidation:
    async def test_unknown_type_is_rejected(self, db, client, tenant, user):
        """A typo'd item_type gets 400, not an empty page."""
        key = await _api_key(db, tenant.id, user.id)

        resp = await client.get(
            "/api/v1/dictionaries/speciality",  # typo for "specialization"
            headers={"X-API-Key": key},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "invalid_dictionary_type"

    async def test_error_lists_valid_types_machine_readable(
        self, db, client, tenant, user
    ):
        """The payload carries the accepted types as data, not just prose.

        An integration must be able to react to the error without parsing a
        localised sentence.
        """
        key = await _api_key(db, tenant.id, user.id)

        resp = await client.get(
            "/api/v1/dictionaries/not_a_type", headers={"X-API-Key": key}
        )

        detail = resp.json()["detail"]
        assert detail["valid_types"] == sorted(VALID_TYPES)
        assert "not_a_type" in detail["message"]

    @pytest.mark.parametrize("item_type", sorted(VALID_TYPES))
    async def test_every_valid_type_still_returns_a_page(
        self, db, client, tenant, user, item_type
    ):
        """Validation must not narrow the set of types that already worked."""
        key = await _api_key(db, tenant.id, user.id)

        resp = await client.get(
            f"/api/v1/dictionaries/{item_type}?limit=1", headers={"X-API-Key": key}
        )

        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_valid_type_returns_its_items(self, db, client, tenant, user):
        """A real item of a valid type is still served after the guard."""
        item = DictionaryItem(
            type="office_location",
            title=f"HRP382 Office {uuid.uuid4().hex[:6]}",
            sort_index=0,
            tenant_id=tenant.id,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        key = await _api_key(db, tenant.id, user.id)

        skip, found = 0, None
        while found is None:
            resp = await client.get(
                f"/api/v1/dictionaries/office_location?skip={skip}&limit=100",
                headers={"X-API-Key": key},
            )
            assert resp.status_code == 200
            data = resp.json()
            found = next(
                (i for i in data["items"] if i["id"] == str(item.id)),
                None,
            )
            skip += 100
            if skip >= data["total"]:
                break

        assert found is not None

    async def test_anonymous_caller_is_rejected_before_type_validation(self, client):
        """Validation must not become an unauthenticated oracle for the route.

        Without a key the caller is turned away by the auth dependency (422
        for the missing header, 401/403 for a bad one) and never learns
        whether the type was valid.
        """
        resp = await client.get("/api/v1/dictionaries/not_a_type")

        assert resp.status_code in (401, 403, 422)
        assert resp.json().get("code") != "invalid_dictionary_type"


class TestRouteContract:
    def test_router_registers_the_path_clients_call(self):
        """The registered path is exactly the one the tests/integrations use.

        Guards against the endpoint being renamed while callers keep the old
        URL — which would resurface as a 404 rather than the 400 above.
        """
        paths = {getattr(route, "path", None) for route in app.routes}
        assert DICTIONARIES_PATH in paths

    def test_valid_types_are_documented_on_the_endpoint(self):
        """The public OpenAPI description lists the accepted types."""
        route = next(
            r
            for r in app.routes
            if getattr(r, "path", None) == DICTIONARIES_PATH
            and "GET" in getattr(r, "methods", set())
        )
        description = route.description or ""
        for item_type in VALID_TYPES:
            assert item_type in description


class TestSharedValidator:
    """The internal and public routes must reject the same set of types."""

    def test_validator_accepts_every_valid_type(self):
        for item_type in VALID_TYPES:
            dictionary_service.validate_item_type(item_type)

    def test_validator_rejects_unknown_type_with_400(self):
        with pytest.raises(HTTPException) as exc_info:
            dictionary_service.validate_item_type("nope")
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "invalid_dictionary_type"
