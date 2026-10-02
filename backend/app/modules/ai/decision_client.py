"""Optional decision provider: typed questions, calibrated answers (HRP-936).

A decision provider answers narrow typed questions about a ``state`` with a
probability instead of generated text: yes/no (:class:`Noul`), one option
out of a set (:class:`Choice`), a level on an ordered scale (:class:`Score`).
The only real provider is Jev (TypeSafe AI), a hosted US API without
self-host, so the mechanism is strictly optional: :func:`decide` returns
``None`` when no key is configured and on any failure, and the caller keeps
the path it had before. Nothing here raises to the caller, and there is no
user-facing error.

Domain modules use the types and :func:`decide` from this module and never
see the vendor wire format. Every call reports its latency and cost, which
the with/without comparisons (HRP-937, HRP-938) are built on.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

import httpx
from prometheus_client import Counter, Histogram
from pydantic import AfterValidator, BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import select

from app.config import settings
from app.core import url_guard
from app.modules.ai import model_registry
from app.modules.ai.providers import base_url_from_settings, decrypt_row_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Same cut as ``work.coverage.TENTATIVE_BELOW``: an answer less certain
# than this counts as low-confidence in the metrics.
LOW_CONFIDENCE_BELOW = 0.8

# Jev answers in 70-500 ms; the timeout is per attempt, one retry on top.
TIMEOUT_S = 5.0
RETRY_PAUSE_S = 0.5
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})

# ponytail: per-process breaker state, so each worker trips on its own;
# move it to Redis if one tenant's failures must stop every worker at once.
BREAKER_FAILURES = 3
BREAKER_OPEN_S = 60.0
_breakers: dict[uuid.UUID, tuple[int, float]] = {}

DECISION_CALLS = Counter(
    "hrpulsar_decision_calls_total",
    "Decision provider calls; any outcome but ok is a fallback to the old path",
    ["provider", "outcome"],
)
DECISION_LATENCY = Histogram(
    "hrpulsar_decision_latency_seconds",
    "Decision provider round-trip latency, retries included",
    ["provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
DECISION_ANSWERS = Counter(
    "hrpulsar_decision_answers_total",
    "Answers by certainty band (low = below LOW_CONFIDENCE_BELOW)",
    ["provider", "type", "band"],
)


# --- Questions ---------------------------------------------------------------

# A string, or JSON structure whose fields the question names in backticks.
Instructions = str | dict[str, Any] | list[Any]


class Noul(BaseModel):
    """Yes/no question; answered with the probability of yes."""

    type: Literal["noul"] = "noul"
    instructions: Instructions
    # Optional descriptions of what a yes and a no mean.
    criteria: dict[Literal["true", "false"], Instructions] | None = None


class Choice(BaseModel):
    """Pick one option; answered with a probability per option."""

    type: Literal["choice"] = "choice"
    instructions: Instructions
    # option -> description, None when the option needs none.
    criteria: dict[str, Instructions | None] = Field(min_length=2, max_length=255)


class Score(BaseModel):
    """Rate on ordered levels (lowest first); answered with a distribution."""

    type: Literal["score"] = "score"
    instructions: Instructions
    criteria: list[Instructions] = Field(min_length=2, max_length=10)


Question = Annotated[Noul | Choice | Score, Field(discriminator="type")]


# --- Answers -----------------------------------------------------------------


def _clamp_unit(value: float) -> float:
    return min(1.0, max(0.0, value))


Probability = Annotated[float, Field(allow_inf_nan=False), AfterValidator(_clamp_unit)]


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    probability: Probability  # of yes

    @property
    def certainty(self) -> float:
        return max(self.probability, 1.0 - self.probability)


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability

    @property
    def certainty(self) -> float:
        return self.confidence


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    # Probability-weighted level index; can land between levels.
    score: float = Field(allow_inf_nan=False)
    probabilities: dict[int, Probability]  # level index -> probability
    confidence: Probability

    @property
    def certainty(self) -> float:
        return self.confidence


Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]
_ANSWERS = TypeAdapter(dict[str, Answer])


class DecisionAnswers(BaseModel):
    """One answer per question id, plus what the call cost."""

    answers: dict[str, Answer]
    provider: str
    model: str
    input_tokens: int
    cost_usd: float
    latency_ms: float


# --- Providers ---------------------------------------------------------------


class DecisionProvider(Protocol):
    """Returns the wire response: ``{"model", "answers", "usage"}`` in the
    Jev shape (docs.typesafe.ai/api), validated by :func:`decide`."""

    name: str
    model: str
    usd_per_mtok_input: float

    async def evaluate(self, state: Any, questions: dict[str, Question]) -> Any: ...


class JevProvider:
    name = "jev"
    model = model_registry.JEV_MODEL
    usd_per_mtok_input = model_registry.JEV_USD_PER_MTOK_INPUT

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        tenant_endpoint: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        # A tenant-chosen base_url goes through the SSRF-guarded client.
        self._tenant_endpoint = tenant_endpoint
        self._transport = transport  # tests only

    async def evaluate(self, state: Any, questions: dict[str, Question]) -> Any:
        body = {
            "state": state,
            "model": self.model,
            "questions": {
                qid: {k: v for k, v in q.model_dump().items() if v is not None}
                for qid, q in questions.items()
            },
        }
        client = None
        if self._tenant_endpoint:
            client = url_guard.tenant_endpoint_http_client(
                self._base_url,
                error_code="llm_base_url_not_public",
                timeout=httpx.Timeout(TIMEOUT_S),
            )
        client = client or httpx.AsyncClient(
            timeout=TIMEOUT_S, transport=self._transport
        )
        url = self._base_url.rstrip("/") + "/v1/systemone"
        async with client:
            for attempt in (1, 2):
                try:
                    resp = await client.post(
                        url,
                        json=body,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    continue
                if resp.status_code in _RETRY_STATUSES and attempt == 1:
                    await asyncio.sleep(RETRY_PAUSE_S)
                    continue
                resp.raise_for_status()
                return resp.json()
        raise AssertionError("unreachable")


class FakeDecisionProvider:
    """Offline provider for tests, and the no-information baseline in the
    HRP-937/938 measurements.

    By default every question gets the uninformative prior: P(yes) = 0.5, a
    uniform distribution over options or levels, zero confidence. ``answers``
    overrides single question ids with wire-format answers, ``response``
    replaces the whole wire response, ``error`` is raised instead.
    """

    name = "fake"
    model = "fake-baseline"
    usd_per_mtok_input = 0.0

    def __init__(
        self,
        answers: dict[str, dict[str, Any]] | None = None,
        *,
        response: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.answers = answers or {}
        self.response = response
        self.error = error
        self.calls: list[tuple[Any, dict[str, Question]]] = []

    async def evaluate(self, state: Any, questions: dict[str, Question]) -> Any:
        self.calls.append((state, questions))
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return {
            "model": self.model,
            "answers": {
                qid: self.answers.get(qid) or _prior(q) for qid, q in questions.items()
            },
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


def _prior(q: Noul | Choice | Score) -> dict[str, Any]:
    if isinstance(q, Noul):
        return {"type": "noul", "noul": 0.5}
    if isinstance(q, Choice):
        options = list(q.criteria)
        return {
            "type": "choice",
            "choice": options[0],
            "probabilities": {o: 1 / len(options) for o in options},
            "confidence": 0.0,
        }
    n = len(q.criteria)
    return {
        "type": "score",
        "score": (n - 1) / 2,
        "probabilities": {str(i): 1 / n for i in range(n)},
        "confidence": 0.0,
    }


async def resolve_provider(
    db: AsyncSession | None, tenant_id: uuid.UUID
) -> DecisionProvider | None:
    """The tenant's configured provider, or None — the normal case.

    A tenant BYOK row (``LLMProviderConfig``, provider ``jev``) wins over the
    platform key. A row's ``base_url`` only ever travels with the row's own
    key: the platform key is never sent to a tenant-chosen endpoint.
    """
    if db is not None:
        from app.modules.recruitment.models import LLMProviderConfig

        row = (
            await db.execute(
                select(LLMProviderConfig)
                .where(
                    LLMProviderConfig.tenant_id == tenant_id,
                    LLMProviderConfig.provider == "jev",
                    LLMProviderConfig.is_active.is_(True),
                )
                .order_by(LLMProviderConfig.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        key = decrypt_row_key(row) if row is not None else None
        if row is not None and key:
            base_url = base_url_from_settings(row.settings)
            return JevProvider(
                key,
                base_url or settings.jev_base_url,
                tenant_endpoint=base_url is not None,
            )
    # HRP-1005: the platform key reaches only tenants with jev on their
    # processor list — without a session the list cannot be read.
    if settings.jev_api_key and db is not None:
        from app.modules.ai import processors

        if "jev" in await processors.allowed_processors(db, tenant_id):
            return JevProvider(settings.jev_api_key, settings.jev_base_url)
    return None


# --- Entry point -------------------------------------------------------------


async def decide(
    state: Any,
    questions: dict[str, Question],
    *,
    tenant: uuid.UUID,
    db: AsyncSession | None = None,
    provider: DecisionProvider | None = None,
) -> DecisionAnswers | None:
    """Ask ``questions`` about ``state``; None means "take the old path".

    ``provider`` bypasses the resolver (tests, offline measurements); without
    ``db`` only an explicit provider is used.
    """
    if provider is None:
        try:
            provider = await resolve_provider(db, tenant)
        except Exception as exc:  # noqa: BLE001 - a failed key lookup means the old path
            DECISION_CALLS.labels("none", "resolve_error").inc()
            logger.warning(
                "decision.fallback",
                extra={
                    "tenant_id": str(tenant),
                    "reason": "resolve_error",
                    "error": type(exc).__name__,
                },
            )
            return None
    if provider is None:
        DECISION_CALLS.labels("none", "not_configured").inc()
        return None
    if _breaker_open(tenant):
        _fallback(provider, tenant, "circuit_open")
        return None

    started = time.perf_counter()
    try:
        raw = await provider.evaluate(state, questions)
    except Exception as exc:  # noqa: BLE001 - any failure means the old path
        _breaker_record(tenant, ok=False)
        _fallback(provider, tenant, "error", exc)
        return None
    latency_s = time.perf_counter() - started
    DECISION_LATENCY.labels(provider.name).observe(latency_s)

    try:
        result = _parse(raw, questions, provider, latency_s)
    except (
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,  # int() of an Infinity token count
    ) as exc:
        _breaker_record(tenant, ok=False)
        _fallback(provider, tenant, "invalid_response", exc)
        return None
    if result.model != provider.model:
        # Thresholds are tuned per pinned version; another model's
        # probabilities would be read against the wrong cut.
        _breaker_record(tenant, ok=False)
        _fallback(provider, tenant, "model_mismatch")
        return None

    _breaker_record(tenant, ok=True)
    DECISION_CALLS.labels(provider.name, "ok").inc()
    low = 0
    for answer in result.answers.values():
        band = "low" if answer.certainty < LOW_CONFIDENCE_BELOW else "confident"
        low += band == "low"
        DECISION_ANSWERS.labels(provider.name, answer.type, band).inc()
    logger.info(
        "decision.ok",
        extra={
            "tenant_id": str(tenant),
            "provider": provider.name,
            "model": result.model,
            "questions": len(questions),
            "low_confidence": low,
            "input_tokens": result.input_tokens,
            "latency_ms": round(result.latency_ms, 1),
        },
    )
    return result


def _parse(
    raw: Any,
    questions: dict[str, Question],
    provider: DecisionProvider,
    latency_s: float,
) -> DecisionAnswers:
    wire = raw["answers"]
    # The wire names the Noul value after its type; ours is ``probability``.
    answers = _ANSWERS.validate_python(
        {
            qid: {"type": "noul", "probability": a.get("noul")}
            if a.get("type") == "noul"
            else a
            for qid, a in wire.items()
        }
    )
    for qid, q in questions.items():
        answer = answers.get(qid)
        if answer is None or answer.type != q.type:
            raise ValueError(f"no {q.type} answer for {qid!r}")
        if (
            isinstance(answer, ChoiceAnswer)
            and isinstance(q, Choice)
            and answer.choice not in q.criteria
        ):
            raise ValueError(f"choice outside the options for {qid!r}")
    input_tokens = int(raw["usage"]["input_tokens"])
    return DecisionAnswers(
        answers=answers,
        provider=provider.name,
        model=str(raw["model"]),
        input_tokens=input_tokens,
        cost_usd=input_tokens * provider.usd_per_mtok_input / 1_000_000,
        latency_ms=latency_s * 1000,
    )


def _fallback(
    provider: DecisionProvider,
    tenant: uuid.UUID,
    reason: str,
    exc: Exception | None = None,
) -> None:
    DECISION_CALLS.labels(provider.name, reason).inc()
    # The exception type only: messages can echo the request (state = PII).
    logger.warning(
        "decision.fallback",
        extra={
            "tenant_id": str(tenant),
            "provider": provider.name,
            "reason": reason,
            "error": type(exc).__name__ if exc is not None else None,
        },
    )


def _breaker_open(tenant: uuid.UUID) -> bool:
    failures, open_until = _breakers.get(tenant, (0, 0.0))
    return failures >= BREAKER_FAILURES and time.monotonic() < open_until


def _breaker_record(tenant: uuid.UUID, *, ok: bool) -> None:
    if ok:
        _breakers.pop(tenant, None)
        return
    failures = _breakers.get(tenant, (0, 0.0))[0] + 1
    _breakers[tenant] = (failures, time.monotonic() + BREAKER_OPEN_S)
