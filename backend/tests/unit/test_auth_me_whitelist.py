"""EMP1: PUT /auth/me strict allowlist.

`UserUpdate` has `extra='forbid'` and only `first_name` / `last_name` are
written by `update_profile`. Privileged fields (status, role_code,
is_active, email, tenant_id, id) must never be settable through this
endpoint. Sending them yields a 422.
"""

import pytest
from httpx import AsyncClient


class TestAuthMeAllowlist:
    async def test_put_me_allows_first_last_name(self, auth_client: AsyncClient):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "Renamed", "last_name": "Person"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_name"] == "Renamed"
        assert body["last_name"] == "Person"

    async def test_put_me_partial_update(self, auth_client: AsyncClient):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "OnlyFirst"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_name"] == "OnlyFirst"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("is_active", False),
            ("email", "hacker@example.com"),
            ("tenant_id", "00000000-0000-0000-0000-000000000000"),
            ("id", "00000000-0000-0000-0000-000000000000"),
            ("role_code", "admin"),
            ("status", "active"),
            ("password_hash", "x"),
            ("avatar_file_id", "00000000-0000-0000-0000-000000000000"),
            ("unknown_field", "anything"),
        ],
    )
    async def test_put_me_rejects_extra_field(
        self, auth_client: AsyncClient, field, value
    ):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "Ok", field: value},
        )
        assert resp.status_code == 422, (
            f"expected 422 for forbidden field {field!r}, got {resp.status_code}: "
            f"{resp.text}"
        )

    async def test_put_me_does_not_change_email_or_role(
        self, auth_client: AsyncClient, user
    ):
        original_email = user.email
        resp = await auth_client.put("/api/auth/me", json={"first_name": "Stays"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == original_email
        # role list is read from DB — sending a role_code can't insert one
        assert body["roles"] == ["admin"]
