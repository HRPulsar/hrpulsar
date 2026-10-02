"""HRP-921 (c): how stable the breakdown is - the library's processes run
several times each, the runs compared with one another.

Every run makes the worker's two calls directly (``tasks.split_steps`` /
``tasks.classify_steps``) with the demo tenant's AI settings, the way
``scripts/run_decomposition_review.py`` does: no session rows, and the
result cache is not in the way - it sits in the Celery worker, not here.
The provider's prompt cache (HRP-951) is: the shared prefix is read from it
after the first call.

Inputs: the library carries prose for sixteen of its 39 processes - the six
few-shot examples (``work/_examples.py``) and the ten held-out cases of the
review script. ``--from-titles`` adds the other 23 as a numbered list of
the library's own step titles: a probe of the classification, not of the
split. Nothing is sent without ``--go``; without it the script prints the
number of model calls and the cost at the measured price per breakdown.

Scoring, per process and over any two runs: the step count is the same;
the share of positions whose normalised titles are the same; the share of
positions whose verdicts (code set, responsibility, output type) are the
same. Positions are aligned by index. Acceptance proposed: composition and
verdicts agree on 95 % of steps or more for every process.

Run from the repository root with the target environment::

    set -a && . ./.env && set +a && \\
    .venv/bin/python backend/scripts/measure_breakdown_stability.py --from-titles
    .venv/bin/python backend/scripts/measure_breakdown_stability.py --go --out /tmp/stability.json
    .venv/bin/python backend/scripts/measure_breakdown_stability.py --score /tmp/stability.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import unicodedata
from itertools import combinations
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.database import async_session, import_all_models  # noqa: E402

import_all_models()

import run_decomposition_review as review  # noqa: E402
from app.modules.work import prompts, tasks  # noqa: E402
from app.modules.work._examples import EXAMPLES  # noqa: E402

LIBRARY = ROOT / "docs" / "plans" / "process-library"
# The six examples, in the order ``work/_examples.py`` lists them.
EXAMPLE_IDS = [
    "legal-1-contract-review",
    "4.4.2-goods-receipt",
    "11.2.2-kyc-cdd-onboarding",
    "8.5.4-feature-development",
    "2.3.2-ab-test",
    "brand-1-rebranding",
]
# Measured on the two-call breakdown (HRP-948 brainstorm, 2026-09-25).
COST_PER_BREAKDOWN_USD = 0.103
THRESHOLD = 0.95


def _cases(from_titles: bool) -> tuple[list[dict], list[str]]:
    """The processes with an input text, and the ids left out."""
    prose = {c["id"]: c for c in review.CASES}
    assert len(EXAMPLE_IDS) == len(EXAMPLES)
    for case_id, (question, _answer) in zip(EXAMPLE_IDS, EXAMPLES, strict=True):
        prose.setdefault(case_id, {"id": case_id, **question})
    cases, skipped = [], []
    for path in sorted(LIBRARY.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        case_id = path.stem
        if case_id in prose:
            cases.append(prose[case_id])
        elif from_titles:
            library = yaml.safe_load(path.read_text())
            listing = "\n".join(f"{s['n']}. {s['title']}" for s in library["steps"])
            cases.append(
                {
                    "id": case_id,
                    "type": "process",
                    "title": library["title"],
                    "description": f"The process consists of these steps:\n{listing}",
                    "goal": None,
                    "from_titles": True,
                }
            )
        else:
            skipped.append(case_id)
    return cases, skipped


def _norm(text: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def _verdict(step: dict) -> tuple:
    return (
        frozenset(step.get("primitives") or []),
        step.get("responsibility"),
        step.get("output_type"),
    )


def score_case(runs: list[list[dict]]) -> dict:
    """Pairwise over the runs: same step count; titles and verdicts the same
    at the same position, as a share of the shorter run."""
    pairs = list(combinations(runs, 2))
    counts_same = sum(len(a) == len(b) for a, b in pairs)
    titles: list[float] = []
    verdicts: list[float] = []
    for a, b in pairs:
        n = min(len(a), len(b))
        if n == 0:
            titles.append(0.0)
            verdicts.append(0.0)
            continue
        titles.append(
            sum(
                _norm(x["title"]) == _norm(y["title"])
                for x, y in zip(a, b, strict=False)
            )
            / n
        )
        verdicts.append(
            sum(_verdict(x) == _verdict(y) for x, y in zip(a, b, strict=False)) / n
        )
    return {
        "runs": len(runs),
        "step_counts": [len(r) for r in runs],
        "same_count_share": counts_same / len(pairs) if pairs else 1.0,
        "title_share": min(titles) if titles else 1.0,
        "verdict_share": min(verdicts) if verdicts else 1.0,
    }


def _report(dump: dict) -> None:
    print(f"## Breakdown stability: {dump['model']}, {dump['prompt_version']}\n")
    print("| process | steps per run | same count | titles | verdicts | verdict |")
    print("|---|---|---|---|---|---|")
    failed = 0
    for case in dump["cases"]:
        s = score_case(case["runs"])
        ok = (
            s["same_count_share"] == 1.0
            and min(s["title_share"], s["verdict_share"]) >= THRESHOLD
        )
        failed += not ok
        print(
            f"| {case['id']}{' (titles)' if case['input'].get('from_titles') else ''} "
            f"| {'/'.join(map(str, s['step_counts']))} | {s['same_count_share']:.2f} "
            f"| {s['title_share']:.2f} | {s['verdict_share']:.2f} | {'ok' if ok else 'below'} |"
        )
    print(
        f"\n{len(dump['cases']) - failed} of {len(dump['cases'])} processes at or above {THRESHOLD:.0%}."
    )


async def _generate(env, case: dict) -> list[dict]:
    steps = await tasks.split_steps(case, **env.call)
    classes = await tasks.classify_steps(case, steps, **env.call)
    merged = [{**s, **c} for s, c in zip(steps, classes, strict=True)]
    return tasks._normalise(merged, {p.code for p in env.primitives})["steps"]


async def _measure(cases: list[dict], runs: int, out: Path) -> None:
    async with async_session() as db:
        env = await review._env(db)
    dump = {"model": env.model, "prompt_version": prompts.PROMPT_VERSION, "cases": []}
    for case in cases:
        results = []
        for run in range(1, runs + 1):
            results.append(await _generate(env, case))
            print(f"{case['id']} run {run}: {len(results[-1])} steps", flush=True)
        dump["cases"].append({"id": case["id"], "input": case, "runs": results})
        out.write_text(json.dumps(dump, ensure_ascii=False, indent=2))
    print(f"written {out}", flush=True)
    _report(dump)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs", type=int, default=3, help="runs per process (default 3)"
    )
    parser.add_argument(
        "--from-titles",
        action="store_true",
        help="add the 23 processes without prose as a list of their step titles",
    )
    parser.add_argument(
        "--go",
        action="store_true",
        help="actually call the model; without it, a dry run",
    )
    parser.add_argument("--out", type=Path, help="JSON dump of every run (with --go)")
    parser.add_argument(
        "--score", type=Path, help="report on an existing dump, no calls"
    )
    args = parser.parse_args()
    if args.score:
        _report(json.loads(args.score.read_text()))
        return 0
    cases, skipped = _cases(args.from_titles)
    breakdowns = len(cases) * args.runs
    print(
        f"processes with an input: {len(cases)} ({len(skipped)} without prose left out"
        f"{'' if args.from_titles else ' - add them with --from-titles'})"
    )
    print(
        f"runs per process: {args.runs} -> {breakdowns} breakdowns, {breakdowns * 2} model calls"
    )
    print(
        f"estimated cost: ${breakdowns * COST_PER_BREAKDOWN_USD:.2f} at ${COST_PER_BREAKDOWN_USD} per breakdown"
    )
    if not args.go:
        print("dry run - nothing was sent; add --go --out <file> to run")
        return 0
    if not args.out:
        parser.error("--out is required with --go")
    asyncio.run(_measure(cases, args.runs, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
