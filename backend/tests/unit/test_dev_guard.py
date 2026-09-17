"""Release-2.0 review M17: every dev/E2E surface uses the same tier gate.

``E2E_MODE`` alone was enough to open the recruitment seed routes, so a
deployed environment carrying a stray ``E2E_MODE=true`` exposed them. The
auth dev endpoints already checked the tier — the check now lives in
``app.core.dev_guard`` and both sides call it.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import settings
from app.core.dev_guard import dev_endpoints_enabled
from fastapi import HTTPException
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("env", ["production", "staging", "PRODUCTION"])
async def test_seed_route_404s_on_a_deployed_tier(
    auth_client: AsyncClient, monkeypatch, env: str
) -> None:
    monkeypatch.setattr(settings, "e2e_mode", True)
    monkeypatch.setattr(settings, "sentry_environment", env)

    resp = await auth_client.post(
        "/api/recruitment/_test/seed-parsed-files",
        json={"files": [{"file_id": str(uuid.uuid4())}]},
    )
    assert resp.status_code == 404
    assert dev_endpoints_enabled() is False


async def test_seed_route_open_off_a_deployed_tier(
    auth_client: AsyncClient, monkeypatch
) -> None:
    """Sanity: the 404 above is the tier gate, not a missing route."""
    monkeypatch.setattr(settings, "e2e_mode", True)
    monkeypatch.setattr(settings, "sentry_environment", "development")

    resp = await auth_client.post(
        "/api/recruitment/_test/seed-parsed-files",
        json={"files": [{"file_id": str(uuid.uuid4())}]},
    )
    # The unknown file id is rejected by the handler — it ran.
    assert resp.status_code != 404
    assert dev_endpoints_enabled() is True


async def test_auth_dev_guard_shares_the_same_rule(monkeypatch) -> None:
    from app.modules.auth.router import _require_dev_endpoint

    monkeypatch.setattr(settings, "e2e_mode", True)
    monkeypatch.setattr(settings, "sentry_environment", "production")
    with pytest.raises(HTTPException) as exc:
        _require_dev_endpoint()
    assert exc.value.status_code == 404
