"""HRP-938: the scorer, the threshold fitting and the Jev branch of
``scripts/run_candidate_decisions_review.py``, offline on a tiny dump;
the usage accounting of ``scripts/generate_hrp938_corpus.py`` (HRP-1021)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import uuid
from collections import Counter, OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core import ai_usage_hooks
from app.modules.ai import decision_client as dc
from app.modules.ai import llm_client

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
SCRIPT = SCRIPTS / "run_candidate_decisions_review.py"
if not SCRIPT.exists():
    # Root scripts/ stays out of the public tree (scripts/sync_repos.sh).
    pytest.skip("the measurement script is not part of this checkout", allow_module_level=True)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: pydantic resolves the models' postponed annotations through sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def review():
    return _load_script("run_candidate_decisions_review")


@pytest.fixture(scope="module")
def corpus():
    return _load_script("generate_hrp938_corpus")


def _interview(item_id: str, speakers: list[str], **extra) -> dict:
    return {
        "id": item_id,
        "source": extra.get("source", "synthetic"),
        "language": extra.get("language", "en"),
        "type": "technical",
        "traps": extra.get("traps", []),
        "turns": [{"speaker": s, "text": f"turn {i} with {i + 1} words" if False else " ".join(["w"] * (i + 1))} for i, s in enumerate(speakers)],
    }


def _jev_answer(interviewer: float, candidate: float, unclear: float = 0.0) -> dict:
    top = max(interviewer, candidate, unclear)
    return {
        "probabilities": {"interviewer": interviewer, "candidate": candidate, "unclear": unclear},
        "confidence": (3 * top - 1) / 2,
    }


INTERVIEWS = {
    "a": _interview("a", ["interviewer", "candidate", "interviewer", "candidate"], traps=["candidate_asks"]),
    "b": _interview("b", ["interviewer", "candidate", "candidate", "interviewer"], language="de", source="demo"),
}


def test_roles_scoring_counts_turns_words_and_failures(review):
    llm_items = [
        {"id": "a", "labels": ["interviewer", "candidate", "candidate", "candidate"], "failed": False, "latency_s": 2.0, "cost_usd": 0.01},
        {"id": "b", "labels": None, "failed": True},
    ]
    s = review.score_roles_run(llm_items, INTERVIEWS)
    assert s["turns"] == 8 and s["failed"] == 1
    # a: turn 2 (3 words) wrong, b: all four wrong (no labels).
    assert s["accuracy"] == pytest.approx(3 / 8)
    assert s["accuracy_words"] == pytest.approx((1 + 2 + 4) / (10 + 10))
    assert s["by"]["language"]["de"] == 0.0 and s["by"]["trap"]["candidate_asks"] == pytest.approx(0.75)
    assert s["cost_per_transcript"] == pytest.approx(0.01) and s["turn_latency_p50"] == pytest.approx(0.5)


def test_roles_jev_predictions_strict_and_decided(review):
    item = {
        "id": "a",
        "failed": False,
        "latency_s": 0.5,
        "cost_usd": 0.0004,
        "answers": [
            _jev_answer(0.9, 0.1),
            _jev_answer(0.2, 0.8),
            _jev_answer(0.3, 0.2, 0.5),  # unclear on top, interviewer more likely than candidate
            _jev_answer(0.6, 0.4),  # wrong, low confidence
        ],
    }
    assert review.roles_predictions(item) == ["interviewer", "candidate", None, "interviewer"]
    assert review.roles_predictions(item, threshold=0.5) == ["interviewer", "candidate", None, None]
    assert review.roles_decided(item) == ["interviewer", "candidate", "interviewer", "interviewer"]
    s = review.score_roles_run([item], {"a": INTERVIEWS["a"]})
    assert s["accuracy"] == pytest.approx(2 / 4) and s["accuracy_decided"] == pytest.approx(3 / 4)


def test_roles_threshold_sends_unsure_turns_to_the_llm(review):
    jev = [
        {"id": "a", "failed": False, "answers": [_jev_answer(0.99, 0.01), _jev_answer(0.01, 0.99), _jev_answer(0.45, 0.55), _jev_answer(0.55, 0.45)]},
    ]
    llm = {"a": {"id": "a", "labels": ["candidate", "candidate", "interviewer", "candidate"]}}
    t = review.fit_roles_threshold(jev, llm, INTERVIEWS)
    # Jev is right where confident and wrong where unsure (conf 0.325);
    # the LLM is right on those two turns and wrong on the first.
    assert 0.325 < t <= 0.985
    h = review.hybrid_roles_accuracy(jev, llm, INTERVIEWS, {"A": t, "B": t})
    assert h["accuracy"] == 1.0 and h["llm_share"] == 0.5


def test_gate_threshold_fits_between_the_classes_and_confusion_is_fail_open(review):
    rows = [(True, 0.9), (True, 0.8), (True, 0.7), (False, 0.3), (False, 0.2), (False, 0.1)]
    t = review.fit_gate_threshold(rows)
    assert 0.35 <= t <= 0.7
    c = review.gate_confusion([(label, p >= t) for label, p in rows])
    assert c["accuracy"] == 1.0 and c["garbage_passed"] == 0 and c["good_rejected"] == 0
    c = review.gate_confusion([(False, None), (True, None), (False, True), (True, False)])
    assert c == {"n": 4, "accuracy": 0.25, "garbage_passed": 2, "good_rejected": 1, "no_answer": 2}
    assert review.auc(rows) == 1.0


def test_gate_run_scores_llm_and_jev_items(review):
    llm = [
        {"id": f"is_resume:{i}", "gate": "is_resume", "doc": f"d{i}", "label": i < 2, "answer": [True, None, True, False][i], "failed": i == 1, "latency_s": 1.0, "cost_usd": 0.001}
        for i in range(4)
    ]
    s = review.score_gate_run(llm, "is_resume")
    assert s["accuracy"] == 0.75 and s["garbage_passed"] == 1 and s["good_rejected"] == 0 and s["no_answer"] == 1
    assert s["wrong"] == [("d2", False, True)]
    jev = [
        {"id": f"is_resume:{i}", "gate": "is_resume", "doc": f"d{i}", "label": i % 2 == 0, "probability": p, "failed": False, "latency_s": 0.3, "cost_usd": 0.00001}
        for i, p in enumerate([0.9, 0.2, 0.8, 0.1, 0.7, 0.3, 0.95, 0.05])
    ]
    s = review.score_gate_run(jev, "is_resume")
    assert s["accuracy"] == 1.0 and s["garbage_passed"] == 0 and s["auc"] == 1.0
    assert 0.3 < s["cut_ab"] <= 0.7 and 0.3 < s["cut_ba"] <= 0.7


@pytest.mark.asyncio
async def test_jev_branch_runs_offline_and_redacts_state(review):
    interview = _interview("x", ["interviewer", "candidate"])
    interview["turns"][1]["text"] = "My SSN is 123-45-6789 and I led the migration."
    provider = dc.FakeDecisionProvider(
        answers={"t0": {"type": "choice", "choice": "interviewer", "probabilities": {"interviewer": 0.9, "candidate": 0.1, "unclear": 0.0}, "confidence": 0.85}}
    )
    item = await review.jev_roles(interview, uuid.uuid4(), provider)
    assert not item["failed"] and len(item["answers"]) == 2 and item["cost_usd"] == 0.0
    assert review.roles_predictions(item)[0] == "interviewer"
    state, questions = provider.calls[0]
    assert "123-45-6789" not in json.dumps(state) and "123-45-6789" not in questions["t1"].instructions
    assert set(questions) == {"t0", "t1"}

    case = {"id": "language_matches:00:d", "gate": "language_matches", "doc": "d", "label": True, "expected_language": "de"}
    doc = {"id": "d", "text": "Lebenslauf. Telefon 123-45-6789.", "language": "de"}
    row = await review.jev_gate(case, doc, uuid.uuid4(), provider)
    assert row["probability"] == 0.5 and row["expected_language"] == "de"
    state, questions = provider.calls[1]
    assert state["expected_language"] == "German" and "123-45-6789" not in state["document"]
    assert questions["gate"].type == "noul"


def test_score_reads_dumps_end_to_end(review, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "interviews.json").write_text(json.dumps({"items": list(INTERVIEWS.values())}))
    docs = [{"id": f"d{i}", "group": "resume" if i < 2 else "non_resume", "kind": "k", "language": "en", "text": "t"} for i in range(4)]
    gates = {"is_resume": [["d0", True], ["d1", True], ["d2", False], ["d3", False]], "transcript_usable": [], "language_matches": [["d0", "en", True], ["d1", "de", False]]}
    (data_dir / "precheck.json").write_text(json.dumps({"documents": docs, "gates": gates}))
    _, cases = review.load_precheck(data_dir)
    assert len(cases) == 6 and cases[-1]["expected_language"] == "de"

    def dump(name: str, meta: dict, items: list[dict]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps({"meta": meta, "items": items}))
        return path

    paths = [
        dump("r_speaker_roles_llm_r1.json", {"point": "speaker_roles", "classifier": "llm", "run": 1},
             [{"id": "a", "labels": ["interviewer", "candidate", "interviewer", "candidate"], "failed": False, "latency_s": 2.0, "cost_usd": 0.01},
              {"id": "b", "labels": ["interviewer", "candidate", "candidate", "interviewer"], "failed": False, "latency_s": 2.0, "cost_usd": 0.01}]),
        dump("r_speaker_roles_jev_r1.json", {"point": "speaker_roles", "classifier": "jev", "run": 1},
             [{"id": "a", "failed": False, "latency_s": 0.5, "cost_usd": 0.0004, "answers": [_jev_answer(0.9, 0.1), _jev_answer(0.1, 0.9), _jev_answer(0.9, 0.1), _jev_answer(0.1, 0.9)]},
              {"id": "b", "failed": False, "latency_s": 0.5, "cost_usd": 0.0004, "answers": [_jev_answer(0.9, 0.1), _jev_answer(0.1, 0.9), _jev_answer(0.6, 0.4), _jev_answer(0.9, 0.1)]}]),
        dump("r_pre_check_llm_r1.json", {"point": "pre_check", "classifier": "llm", "run": 1},
             [{**{k: c[k] for k in ("id", "gate", "doc", "label")}, "answer": c["label"], "failed": False, "latency_s": 1.0, "cost_usd": 0.001} for c in cases]),
        dump("r_pre_check_jev_r1.json", {"point": "pre_check", "classifier": "jev", "run": 1},
             [{**{k: c[k] for k in ("id", "gate", "doc", "label")}, "probability": 0.9 if c["label"] else 0.1, "failed": False, "latency_s": 0.2, "cost_usd": 0.00001} for c in cases]),
    ]
    report = review.score(paths, data_dir)
    assert "### Speaker roles" in report and "### Pre-check gates" in report
    assert "| llm | 1 | 2 (0) | 8 | 1.000 |" in report
    assert "| jev | 1 | 2 (0) | 8 | 0.875 |" in report
    assert "#### is_resume" in report and "| jev | 1 | 4 | 1.000 | 0 | 0 | 0 |" in report


# --- HRP-1021 -----------------------------------------------------------------


def test_every_event_loop_gets_its_own_anthropic_client_closed_with_it(review, monkeypatch):
    # Restored at teardown: _client_per_loop patches both process-wide.
    monkeypatch.setattr(asyncio, "run", asyncio.run)
    monkeypatch.setattr(llm_client, "_get_anthropic", llm_client._get_anthropic)
    monkeypatch.setattr(llm_client, "_client_cache", OrderedDict())
    shared = llm_client._get_anthropic
    review._client_per_loop()

    async def borrow():
        # A failing close of one client must not leave the next one open.
        broken = llm_client._get_anthropic("broken-key")
        monkeypatch.setattr(broken, "close", lambda: asyncio.sleep(0, result=1 / 0))
        client = llm_client._get_anthropic("test-key")
        assert llm_client._get_anthropic("test-key") is client and not client.is_closed()
        return client

    first = asyncio.run(borrow())
    # label_speakers_sync: its own asyncio.run inside a worker thread of a running loop.
    second = asyncio.run(asyncio.to_thread(asyncio.run, borrow()))
    assert first is not second
    assert first.is_closed() and second.is_closed()
    # Outside any wrapped loop: the process-wide client, not a TypeError.
    assert llm_client._get_anthropic("test-key") is shared("test-key")


class _JevDown(dc.FakeDecisionProvider):
    """Fails every item; answers the breaker probe unless the whole service is down."""

    def __init__(self, *, outage: bool) -> None:
        super().__init__()
        self.outage = outage

    async def evaluate(self, state, questions):
        if self.outage or "probe" not in questions:
            self.calls.append((state, questions))
            raise RuntimeError("jev error")
        return await super().evaluate(state, questions)


@pytest.fixture
def breaker_clock(monkeypatch):
    """asyncio.sleep without waiting; sleeping BREAKER_OPEN_S expires the open breakers."""
    sleep = asyncio.sleep
    slept: list[float] = []

    async def fake_sleep(seconds, result=None):
        slept.append(seconds)
        if seconds == dc.BREAKER_OPEN_S:
            for tenant, (failures, _) in list(dc._breakers.items()):
                dc._breakers[tenant] = (failures, 0.0)
        return await sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


async def _run_one_gate(review, provider, tenant) -> dict[str, dict]:
    case = {"id": "is_resume:00:d", "gate": "is_resume", "doc": "d", "label": True}
    doc = {"id": "d", "text": "Curriculum vitae", "language": "en"}
    done: dict[str, dict] = {}
    try:
        await review._run_items([case], done, lambda c: review.jev_gate(c, doc, tenant, provider), lambda: None, "t")
    finally:
        dc._breakers.pop(tenant, None)
    return done


@pytest.mark.asyncio
async def test_one_bad_jev_item_is_recorded_failed_and_the_run_goes_on(review, breaker_clock):
    assert review.JEV_ATTEMPTS >= dc.BREAKER_FAILURES
    provider = _JevDown(outage=False)
    done = await _run_one_gate(review, provider, uuid.uuid4())
    # Its own attempts opened the breaker; the probe after the pause passed, so it is the item, not Jev.
    assert done["is_resume:00:d"]["failed"] is True
    probes = sum("probe" in questions for _, questions in provider.calls)
    assert len(provider.calls) - probes == review.JEV_ATTEMPTS and probes == 1 and dc.BREAKER_OPEN_S in breaker_clock


@pytest.mark.asyncio
async def test_a_jev_outage_stops_the_run_at_the_breaker(review, breaker_clock):
    provider = _JevDown(outage=True)
    with pytest.raises(review.JevUnavailable, match="probe"):
        await _run_one_gate(review, provider, tenant := uuid.uuid4())
    assert tenant not in dc._breakers
    # The item's attempts plus the probe, and nothing recorded: a rerun retries the item.
    assert len(provider.calls) == review.JEV_ATTEMPTS + 1


@pytest.mark.asyncio
async def test_env_refuses_a_non_anthropic_llm_provider(review, monkeypatch):
    from app.modules.ai.providers import GenerationTarget

    async def returns(value, *_args):
        return value

    tenant = SimpleNamespace(id=uuid.uuid4())
    db = SimpleNamespace(execute=lambda *_a: returns(SimpleNamespace(scalar_one=lambda: tenant)))
    monkeypatch.setattr(review.ai_settings_service, "get_or_default", lambda *a: returns(None))
    monkeypatch.setattr(review.ai_settings_service, "get_effective_model_async", lambda *a: returns("gpt-x"))
    monkeypatch.setattr(review.ai_providers, "resolve_generation_target", lambda *a: returns(GenerationTarget(provider="openai")))
    with pytest.raises(SystemExit, match="anthropic only"):
        await review._env(db, ["llm"])


def test_gate_wrong_list_has_no_unanswered_cases(review):
    def row(i: int, label: bool, **answer) -> dict:
        return {"id": f"is_resume:{i}", "gate": "is_resume", "doc": f"d{i}", "label": label, "failed": None in answer.values(), "latency_s": 0.5, "cost_usd": None, **answer}

    llm = [row(0, False, answer=None), row(1, True, answer=None), row(2, False, answer=True), row(3, True, answer=True)]
    s = review.score_gate_run(llm, "is_resume")
    assert s["wrong"] == [("d2", False, True)] and s["no_answer"] == 2

    jev = [row(i, label, probability=p) for i, (label, p) in enumerate([(True, 0.9), (False, 0.1), (True, None), (False, None), (True, 0.8), (False, 0.2)])]
    s = review.score_gate_run(jev, "is_resume")
    assert s["no_answer"] == 2
    assert all(value is not None for _, _, value in s["wrong"])
    assert {"d2", "d3"}.isdisjoint(doc for doc, _, _ in s["wrong"])


@pytest.mark.asyncio
async def test_corpus_usage_is_counted_once_per_file(corpus, monkeypatch, tmp_path):
    from anthropic.resources.messages import AsyncMessages
    from app.modules.ai.providers import GenerationTarget

    replies: list[tuple[int, int]] = []

    async def fake_create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Interview type" in prompt:
            n = int(re.search(r"between (\d+) and", prompt).group(1)) + 3
            body = {"turns": [{"speaker": ("interviewer", "candidate")[i % 2], "text": "Fine."} for i in range(n)]}
            usage = (100, 1000)
        else:
            body = {"text": "word " * 30}
            usage = (10, 50)
        replies.append(usage)
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps(body))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
        )

    monkeypatch.setattr(AsyncMessages, "create", fake_create)  # restored over the counting wrapper too
    monkeypatch.setattr(llm_client, "_client_cache", OrderedDict())
    # The EE journal would write a row per mocked call into the shared test database.
    monkeypatch.setattr(ai_usage_hooks, "record_call", lambda _record: asyncio.sleep(0))
    monkeypatch.setattr(corpus, "_usage", Counter())
    corpus._count_usage()
    env = corpus._Env(None, "claude-sonnet-5", GenerationTarget(provider="anthropic", api_key="test-key"))

    interviews = (await corpus.generate_interviews(env, tmp_path / "interviews.json"))["items"]
    await corpus.generate_documents(env, tmp_path / "precheck.json", interviews)

    meta = {name: json.loads((tmp_path / f"{name}.json").read_text())["meta"] for name in ("interviews", "precheck")}
    n_interviews = replies.count((100, 1000))
    n_documents = replies.count((10, 50))
    assert n_interviews == len(corpus.interview_plan()) and n_documents == len(corpus.document_plan())
    assert meta["interviews"]["usage_tokens"] == {"input": 100 * n_interviews, "output": 1000 * n_interviews}
    assert meta["precheck"]["usage_tokens"] == {"input": 10 * n_documents, "output": 50 * n_documents}
    total = {"input": sum(i for i, _ in replies), "output": sum(o for _, o in replies)}
    assert dict(corpus._usage) == total
    assert meta["interviews"]["cost_usd"] + meta["precheck"]["cost_usd"] == pytest.approx(corpus._cost("claude-sonnet-5", Counter(total)), abs=1e-4)

    # A rerun with nothing left to generate adds nothing to either file.
    await corpus.generate_interviews(env, tmp_path / "interviews.json")
    rerun = json.loads((tmp_path / "interviews.json").read_text())["meta"]
    assert rerun["usage_tokens"] == meta["interviews"]["usage_tokens"]
