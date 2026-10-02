"""HRP-938: the scorer, the threshold fitting and the Jev branch of
``scripts/run_candidate_decisions_review.py``, offline on a tiny dump."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from app.modules.ai import decision_client as dc

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_candidate_decisions_review.py"
if not SCRIPT.exists():
    # Root scripts/ stays out of the public tree (scripts/sync_repos.sh).
    pytest.skip("the measurement script is not part of this checkout", allow_module_level=True)


@pytest.fixture(scope="module")
def review():
    spec = importlib.util.spec_from_file_location("run_candidate_decisions_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
