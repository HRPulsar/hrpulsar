"""Release-2.0 review M16: the public manager-assessment surface is bounded.

Nine unauthenticated token-in-URL routes used to run with neither a per-IP
rate limit (token grinding, replay) nor a bound on the free text that later
goes into the LLM report prompt.
"""

from __future__ import annotations

import uuid

import pytest
from app.main import app
from app.modules.recruitment.manager_assessment_schemas import MAX_EVALUATOR_TEXT
from app.modules.recruitment.routers.common import recruitment_public_limiter
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

# The PATCH .../name route carries the tightest limit of the nine.
_NAME_LIMIT = 20


async def test_public_route_throttles_per_ip(client: AsyncClient) -> None:
    """The (limit + 1)th call from one IP is refused by the limiter itself,
    whatever the token lookup underneath answered."""
    # The suite disables this limiter for everyone else (shared testclient
    # peer, counters in real Redis) — this is the test that asserts on it.
    previous = recruitment_public_limiter.enabled
    recruitment_public_limiter.enabled = True
    recruitment_public_limiter.reset()
    try:
        # Own transport so the bucket is keyed on an IP no other test shares.
        transport = ASGITransport(app=app, client=("198.51.100.77", 1234))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            url = f"/api/v1/public/assessments/{uuid.uuid4().hex}/name"
            for _ in range(_NAME_LIMIT):
                await c.patch(url, json={"name": "Evaluator"})
            blocked = await c.patch(url, json={"name": "Evaluator"})
    finally:
        recruitment_public_limiter.enabled = previous
        recruitment_public_limiter.reset()

    assert blocked.status_code == 429
    # slowapi's own refusal, not the service-level invalid-token deny list.
    assert "rate limit exceeded" in blocked.text.lower()


async def test_score_comment_is_length_bounded(client: AsyncClient) -> None:
    """Evaluator comments reach the report prompt — over-long text is
    refused at the schema, before any token work."""
    resp = await client.patch(
        f"/api/v1/public/assessments/{uuid.uuid4().hex}"
        f"/competence-scores/{uuid.uuid4()}",
        json={"score_value": 3, "comment": "x" * (MAX_EVALUATOR_TEXT + 1)},
    )
    assert resp.status_code == 422

    long_notes = await client.patch(
        f"/api/v1/public/assessments/{uuid.uuid4().hex}/notes",
        json={"final_notes": "x" * (MAX_EVALUATOR_TEXT + 1)},
    )
    assert long_notes.status_code == 422
