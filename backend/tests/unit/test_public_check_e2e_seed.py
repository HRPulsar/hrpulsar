"""HRP-932: the E2E-only seeds of the public check - 404 outside E2E, and in
E2E the states the Playwright specs start from: a ready check without a
model call, the token of a letter, the login of the approval letter, a
spent per-IP budget that the real intake then refuses."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from app.config import settings
from app.modules.ai import llm_client
from app.modules.public_check import router, service
from app.modules.public_check.models import PublicCheck
from sqlalchemy import func, select

from tests.unit.test_public_check import _no_call, seeded  # noqa: F401 - fixture

pytestmark = pytest.mark.asyncio

SEED = "/api/public-check/_test"
CHECKS = "/api/public-check/checks"
ROUTES = ("checks", "email-token", "magic-login", "spend-ip-budget")


def _body() -> dict:
    return {
        "description": f"We answer requests and file returns. {uuid.uuid4()}",
        "answers": {"hourly_rate": 50},
    }


def _visitor() -> dict[str, str]:
    # A fresh documentation address per test: the throttle counts in Redis,
    # which outlives a run.
    return {"X-Forwarded-For": f"203.0.113.{uuid.uuid4().int % 250 + 1}"}


@pytest.fixture(autouse=True)
def _service(monkeypatch):
    monkeypatch.setattr(settings, "public_check_enabled", True)
    monkeypatch.setattr(service, "SANDBOX_SLUG", f"pc_seed_{uuid.uuid4().hex[:10]}")
    monkeypatch.setattr(router.limiter, "enabled", False)
    monkeypatch.setattr(settings, "public_check_turnstile_secret", "")
    monkeypatch.setattr(settings, "public_check_paused", False)
    monkeypatch.setattr(settings, "public_check_daily_limit", 0)


@pytest.fixture
def e2e(monkeypatch):
    monkeypatch.setattr(settings, "e2e_mode", True)
    monkeypatch.setattr(settings, "sentry_environment", "test")


async def _seed(client) -> dict:
    with patch.object(llm_client, "generate_json", side_effect=_no_call):
        resp = await client.post(f"{SEED}/checks", json=_body())
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("route", ROUTES)
async def test_every_seed_is_404_outside_e2e(client, db, monkeypatch, route):
    monkeypatch.setattr(settings, "e2e_mode", False)
    before = await db.scalar(select(func.count()).select_from(PublicCheck))
    resp = await client.post(f"{SEED}/{route}", json={**_body(), "email": "a@b.co"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not found"  # no code to fingerprint
    assert await db.scalar(select(func.count()).select_from(PublicCheck)) == before


async def test_a_deployed_tier_hides_the_seeds_even_with_e2e_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "e2e_mode", True)
    monkeypatch.setattr(settings, "sentry_environment", "production")
    assert (await client.post(f"{SEED}/checks", json=_body())).status_code == 404


async def test_the_seeds_are_not_in_any_openapi():
    # The full schema, before the public filter drops the public-check tag.
    from app.main import app
    from fastapi.openapi.utils import get_openapi

    paths = get_openapi(title="t", version="0", routes=app.routes)["paths"]
    assert any(p.startswith("/api/public-check/") for p in paths)
    assert not any("/_test/" in p for p in paths if "public-check" in p)


@pytest.mark.usefixtures("seeded")
async def test_a_seeded_check_is_ready_without_a_model_call(client, e2e):
    seed = await _seed(client)
    assert seed["status"] == "ready" and seed["owner_key"]
    body = (await client.get(f"{CHECKS}/{seed['token']}")).json()
    assert body["status"] == "ready" and body["expires_at"] is not None
    result = body["result"]
    assert result["shares"] == {"moves": 25.0, "to_review": 50.0, "stays": 25.0}
    assert result["money"]["total"] == 2400.0
    titles = {k: [s["title"] for s in v] for k, v in result["buckets"].items()}
    assert titles == {
        "moves": ["Read the request"],
        "to_review": ["Draft the reply", "File the return"],
        "stays": ["Decide on the exception"],
    }
    assert [s["title"] for s in result["out_of_scope"]] == ["Carry the box"]


@pytest.mark.usefixtures("seeded")
async def test_letter_tokens_follow_the_address_through_confirmation(client, e2e):
    email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
    assert (
        await client.post(f"{SEED}/email-token", json={"email": email})
    ).status_code == 404
    seed = await _seed(client)
    saved = await client.post(
        f"{CHECKS}/{seed['token']}/save",
        json={"email": email, "consent": True, "owner_key": seed["owner_key"]},
    )
    assert saved.json() == {"status": "confirm"}

    issued = (await client.post(f"{SEED}/email-token", json={"email": email})).json()
    assert issued["kind"] == "confirm"
    assert (
        await client.post(f"/api/public-check/confirm/{issued['token']}")
    ).status_code == 200

    issued = (
        await client.post(f"{SEED}/email-token", json={"email": email.upper()})
    ).json()
    assert issued["kind"] == "magic"
    mine = (await client.get(f"/api/public-check/mine/{issued['token']}")).json()
    assert [c["id"] for c in mine["checks"]] == [str(seed["id"])]

    # A check saved after the confirmation waits for its own letter.
    later = await _seed(client)
    await client.post(
        f"{CHECKS}/{later['token']}/save",
        json={"email": email, "consent": True, "owner_key": later["owner_key"]},
    )
    letter = (
        await client.post(
            f"{SEED}/email-token", json={"email": email, "kind": "confirm"}
        )
    ).json()
    assert letter["kind"] == "confirm"
    assert (
        await client.post(f"/api/public-check/confirm/{letter['token']}")
    ).status_code == 200
    mine = (await client.get(f"/api/public-check/mine/{issued['token']}")).json()
    assert {c["id"] for c in mine["checks"]} == {str(seed["id"]), str(later["id"])}


async def test_the_approval_login_signs_the_user_in(client, user, e2e):
    unknown = await client.post(
        f"{SEED}/magic-login", json={"email": "nobody@example.com"}
    )
    assert unknown.status_code == 404
    token = (
        await client.post(f"{SEED}/magic-login", json={"email": user.email.upper()})
    ).json()["token"]
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == user.email


@pytest.mark.usefixtures("seeded")
async def test_a_spent_ip_budget_meets_the_real_429(client, e2e, monkeypatch):
    monkeypatch.setattr(router.limiter, "enabled", True)
    monkeypatch.setattr(settings, "public_check_rate_limit", "3/hour;50/day")
    visitor = _visitor()
    spent = await client.post(f"{SEED}/spend-ip-budget", headers=visitor)
    assert spent.json() == {"hits": 3}

    refused = await client.post(CHECKS, json=_body(), headers=visitor)
    assert refused.status_code == 429
    assert refused.json()["code"] == "public_check_rate_limited"
    assert int(refused.headers["Retry-After"]) > 0
    # Another visitor behind the same proxy has a budget of their own.
    with patch("app.core.task_enqueue.enqueue_task"):
        neighbour = await client.post(CHECKS, json=_body(), headers=_visitor())
    assert neighbour.status_code == 202
