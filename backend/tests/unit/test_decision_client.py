"""HRP-936 — optional decision provider: resolver, fallback, clamping, breaker.

No test here reaches the network: Jev calls go through ``httpx.MockTransport``.
"""

import base64
import json
import uuid

import httpx
import pytest
from app.config import settings
from app.core.crypto import encrypt_secret
from app.modules.ai import decision_client as dc
from app.modules.ai import model_registry, providers
from app.modules.recruitment.models import LLMProviderConfig
from app.modules.recruitment.settings_schemas import LLMProviderCreate
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

QUESTIONS: dict[str, dc.Question] = {
    "is_resume": dc.Noul(instructions="Is this a resume?"),
    "speaker": dc.Choice(
        instructions="Who is speaking?",
        criteria={"interviewer": None, "candidate": "The person applying"},
    ),
    "fit": dc.Score(instructions="How good is the fit?", criteria=["Poor", "Good"]),
}


def _jev_response(**answers: dict) -> dict:
    return {
        "model": model_registry.JEV_MODEL,
        "answers": answers,
        "usage": {"input_tokens": 2_000_000, "output_tokens": 20},
    }


GOOD = _jev_response(
    is_resume={"type": "noul", "noul": 0.95},
    speaker={
        "type": "choice",
        "choice": "candidate",
        "probabilities": {"interviewer": 0.1, "candidate": 0.9},
        "confidence": 0.81,
    },
    fit={
        "type": "score",
        "score": 0.6,
        "legend": {"0": "Poor", "1": "Good"},
        "probabilities": {"0": 0.4, "1": 0.6},
        "confidence": 0.3,
    },
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(settings, "jev_api_key", "")
    monkeypatch.setattr(dc, "RETRY_PAUSE_S", 0)
    dc._breakers.clear()
    yield
    dc._breakers.clear()


def _jev(handler) -> tuple[dc.JevProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    provider = dc.JevProvider(
        "k", "https://jev.test", transport=httpx.MockTransport(_record)
    )
    return provider, seen


def _calls(provider: str, outcome: str) -> float:
    return dc.DECISION_CALLS.labels(provider, outcome)._value.get()


async def _add_jev_row(
    db: AsyncSession, tenant_id: uuid.UUID, *, key: str | None, base_url=None
) -> LLMProviderConfig:
    row = LLMProviderConfig(
        tenant_id=tenant_id,
        provider="jev",
        model=model_registry.JEV_MODEL,
        api_key_encrypted=encrypt_secret(key) if key else None,
        settings={"base_url": base_url} if base_url else None,
    )
    db.add(row)
    await db.commit()
    return row


# --- Not configured: the old path, untouched --------------------------------


async def test_no_key_anywhere_returns_none(db: AsyncSession, tenant) -> None:
    before = _calls("none", "not_configured")
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, db=db) is None
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id) is None
    assert _calls("none", "not_configured") == before + 2


async def test_platform_key_resolves(db, monkeypatch, tenant) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "platform")
    provider = await dc.resolve_provider(db, tenant.id)
    assert isinstance(provider, dc.JevProvider)
    assert provider._base_url == settings.jev_base_url


async def test_platform_key_needs_jev_on_the_tenants_list(db, monkeypatch, tenant) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "platform-key")
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    assert await dc.resolve_provider(db, tenant.id) is None


async def test_platform_key_is_not_used_without_a_session(monkeypatch, tenant) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "platform-key")
    assert await dc.resolve_provider(None, tenant.id) is None


async def test_byok_row_wins_and_keeps_its_base_url(
    monkeypatch, db: AsyncSession, tenant
) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "platform")
    await _add_jev_row(db, tenant.id, key="tenant", base_url="https://proxy.test")
    provider = await dc.resolve_provider(db, tenant.id)
    assert isinstance(provider, dc.JevProvider)
    assert (provider._api_key, provider._base_url) == ("tenant", "https://proxy.test")


async def test_platform_key_never_goes_to_a_tenant_base_url(
    monkeypatch, db: AsyncSession, tenant
) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "platform")
    await _add_jev_row(db, tenant.id, key=None, base_url="https://evil.test")
    provider = await dc.resolve_provider(db, tenant.id)
    assert isinstance(provider, dc.JevProvider)
    assert provider._base_url == settings.jev_base_url


async def test_tenant_base_url_is_ssrf_guarded_on_saas(
    monkeypatch, caplog, db: AsyncSession, tenant
) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    # saas refuses the dev fallback key; CI has no ENCRYPTION_KEY.
    monkeypatch.setattr(
        settings, "encryption_key", base64.urlsafe_b64encode(b"k" * 32).decode()
    )
    await _add_jev_row(db, tenant.id, key="tenant", base_url="https://127.0.0.1")
    with caplog.at_level("WARNING", logger=dc.__name__):
        assert await dc.decide("x", QUESTIONS, tenant=tenant.id, db=db) is None
    # The guard refused the address; no connection was attempted.
    assert [r.error for r in caplog.records] == ["AppError"]


async def test_jev_row_is_not_a_generation_target(db: AsyncSession, tenant) -> None:
    await _add_jev_row(db, tenant.id, key="tenant")
    target = await providers.resolve_generation_target(
        db, tenant.id, model_registry.ANTHROPIC_BALANCED
    )
    assert (target.provider, target.source) == ("anthropic", "global")


def test_jev_byok_row_passes_the_settings_schema() -> None:
    row = LLMProviderCreate(provider="jev", model=model_registry.JEV_MODEL, api_key="k")
    assert row.provider == "jev"


# --- Jev wire ----------------------------------------------------------------


async def test_jev_request_shape_and_parsed_answers(tenant) -> None:
    provider, seen = _jev(lambda r: httpx.Response(200, json=GOOD))
    result = await dc.decide(
        {"text": "cv"}, QUESTIONS, tenant=tenant.id, provider=provider
    )

    assert result is not None
    body = json.loads(seen[0].content)
    assert seen[0].url == "https://jev.test/v1/systemone"
    assert seen[0].headers["authorization"] == "Bearer k"
    assert body["model"] == "jev-1.13.0"
    assert body["questions"]["is_resume"] == {
        "type": "noul",
        "instructions": "Is this a resume?",
    }
    assert body["questions"]["speaker"]["criteria"]["interviewer"] is None

    noul = result.answers["is_resume"]
    assert isinstance(noul, dc.NoulAnswer) and noul.probability == 0.95
    score = result.answers["fit"]
    assert isinstance(score, dc.ScoreAnswer) and score.probabilities == {0: 0.4, 1: 0.6}
    assert result.cost_usd == pytest.approx(2 * 0.042)
    assert result.latency_ms >= 0


async def test_probabilities_are_clamped_to_unit_interval(tenant) -> None:
    raw = json.loads(json.dumps(GOOD))
    raw["answers"]["is_resume"]["noul"] = 1.3
    raw["answers"]["speaker"]["probabilities"] = {"interviewer": -0.2, "candidate": 1.2}
    provider = dc.FakeDecisionProvider(response=raw | {"model": "fake-baseline"})
    result = await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider)

    assert result is not None
    assert result.answers["is_resume"].probability == 1.0
    assert result.answers["speaker"].probabilities == {
        "interviewer": 0.0,
        "candidate": 1.0,
    }


async def test_timeout_retries_once_then_falls_back(tenant) -> None:
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider, seen = _jev(_timeout)
    before = _calls("jev", "error")
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None
    assert len(seen) == 2
    assert _calls("jev", "error") == before + 1


async def test_overload_is_retried(tenant) -> None:
    replies = iter([httpx.Response(529), httpx.Response(200, json=GOOD)])
    provider, seen = _jev(lambda r: next(replies))
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider)
    assert len(seen) == 2


@pytest.mark.parametrize("status", [401, 403, 422])
async def test_client_errors_fall_back_without_retry(tenant, status) -> None:
    provider, seen = _jev(lambda r: httpx.Response(status))
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None
    assert len(seen) == 1


@pytest.mark.parametrize(
    "response",
    [
        {"answers": {}},  # no model, no usage
        _jev_response(is_resume={"type": "noul", "noul": 0.9}),  # missing answers
        {**GOOD, "answers": {**GOOD["answers"], "is_resume": {"type": "choice"}}},
        {
            **GOOD,
            "answers": {
                **GOOD["answers"],
                "is_resume": {"type": "noul", "noul": "yes"},
            },
        },
        {
            **GOOD,
            "answers": {
                **GOOD["answers"],
                "speaker": {**GOOD["answers"]["speaker"], "choice": "hr"},
            },
        },
        "not json object",
    ],
)
async def test_broken_schema_falls_back(tenant, response) -> None:
    provider, _ = _jev(lambda r: httpx.Response(200, json=response))
    before = _calls("jev", "invalid_response")
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None
    assert _calls("jev", "invalid_response") == before + 1


async def test_non_json_body_falls_back(tenant) -> None:
    provider, _ = _jev(lambda r: httpx.Response(200, text="<html>blocked</html>"))
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None


async def test_infinite_token_count_falls_back(tenant) -> None:
    provider = dc.FakeDecisionProvider(
        response={**GOOD, "usage": {"input_tokens": float("inf")}}
    )
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None


async def test_failed_key_lookup_falls_back(monkeypatch, tenant) -> None:
    async def _broken(db, tenant_id):
        raise RuntimeError("db is gone")

    monkeypatch.setattr(dc, "resolve_provider", _broken)
    before = _calls("none", "resolve_error")
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id) is None
    assert _calls("none", "resolve_error") == before + 1


async def test_unpinned_model_answer_falls_back(tenant) -> None:
    provider, _ = _jev(
        lambda r: httpx.Response(200, json={**GOOD, "model": "jev-1.14.0"})
    )
    before = _calls("jev", "model_mismatch")
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=provider) is None
    assert _calls("jev", "model_mismatch") == before + 1


# --- Breaker, fake baseline, metrics -----------------------------------------


async def test_breaker_opens_per_tenant_and_closes_after_cooldown(tenant) -> None:
    failing = dc.FakeDecisionProvider(error=RuntimeError("down"))
    for _ in range(dc.BREAKER_FAILURES):
        assert (
            await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=failing) is None
        )
    assert len(failing.calls) == dc.BREAKER_FAILURES

    healthy = dc.FakeDecisionProvider()
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=healthy) is None
    assert healthy.calls == []
    # Another tenant is unaffected.
    assert await dc.decide("x", QUESTIONS, tenant=uuid.uuid4(), provider=healthy)

    # Cooldown over: one failed probe re-opens at once, a success closes it.
    dc._breakers[tenant.id] = (dc.BREAKER_FAILURES, 0.0)
    await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=failing)
    assert dc._breaker_open(tenant.id)
    dc._breakers[tenant.id] = (dc.BREAKER_FAILURES, 0.0)
    assert await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=healthy)
    assert tenant.id not in dc._breakers


async def test_fake_baseline_is_the_uninformative_prior(tenant) -> None:
    fake = dc.FakeDecisionProvider()
    result = await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=fake)

    assert result is not None
    assert (result.cost_usd, result.provider, result.model) == (
        0.0,
        "fake",
        "fake-baseline",
    )
    assert result.answers["is_resume"].probability == 0.5
    assert result.answers["speaker"].probabilities == {
        "interviewer": 0.5,
        "candidate": 0.5,
    }
    assert result.answers["fit"].score == 0.5
    assert fake.calls == [("x", QUESTIONS)]


async def test_low_confidence_answers_are_counted(tenant) -> None:
    def band(kind: str, name: str) -> float:
        return dc.DECISION_ANSWERS.labels("fake", kind, name)._value.get()

    before = (
        band("noul", "confident"),
        band("choice", "confident"),
        band("score", "low"),
    )
    fake = dc.FakeDecisionProvider(
        {
            "is_resume": {"type": "noul", "noul": 0.05},  # certainty 0.95
            "speaker": GOOD["answers"]["speaker"],  # confidence 0.81
        }
    )
    await dc.decide("x", QUESTIONS, tenant=tenant.id, provider=fake)
    after = (
        band("noul", "confident"),
        band("choice", "confident"),
        band("score", "low"),
    )
    assert after == tuple(b + 1 for b in before)
