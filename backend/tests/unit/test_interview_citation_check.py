"""HRP-981: a saved AI citation is always a fragment of the transcript.

The model answers with citations it claims to have taken from the
transcript; nothing used to check that. ``check_analysis_citations``
re-anchors every citation on the segment it quotes and drops the rest,
and the analysis task runs it before anything is persisted.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.modules.recruitment.models import AIAssessment, InterviewSegment
from app.modules.recruitment.prompts_interview import (
    InterviewAnalysisResult,
    check_analysis_citations,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp492_full_run_progress import (  # noqa: F401 — fixtures
    _fresh_runs,
    _setup,
    dispatched,
    worker_db,
)

SEGMENTS = [
    {
        "id": "seg-1",
        "start_sec": 12.0,
        "end_sec": 40.0,
        "text": "We keyed every transfer on an idempotency key.",
    },
    {
        "id": "seg-2",
        "start_sec": 40.0,
        "end_sec": 75.0,
        "text": "Then a reconciliation loop compares the ledger every night.",
    },
]


def _analysis(*citations: dict) -> dict:
    return {
        "competence_assessments": [
            {
                "competence_id": "distributed-systems",
                "status": "assessed",
                "citations": list(citations),
            }
        ],
        "process_findings": [],
    }


def test_an_invented_quote_is_dropped():
    analysis = _analysis(
        {"segment_id": "seg-1", "quote": "I designed Kafka at LinkedIn."},
        {"segment_id": None, "quote": "I designed Kafka at LinkedIn."},
    )
    stats = check_analysis_citations(analysis, SEGMENTS, "irrelevant")
    assert analysis["competence_assessments"][0]["citations"] == []
    assert stats == {"total": 2, "dropped": 2, "dropped_ratio": 1.0}


def test_a_missing_segment_id_is_dropped_even_when_the_text_exists():
    analysis = _analysis({"segment_id": "seg-404", "quote": "idempotency key"})
    stats = check_analysis_citations(analysis, SEGMENTS, "")
    assert analysis["competence_assessments"][0]["citations"] == []
    assert stats["dropped"] == 1


@pytest.mark.parametrize("segment_id", ["seg-1", "seg-2", None])
def test_a_quote_across_the_seam_spans_both_segments(segment_id):
    """Review B6: the model quotes speech, not rows - a sentence cut by the
    segmenter is found in the two neighbours joined."""
    analysis = _analysis(
        {"segment_id": segment_id, "quote": "idempotency key. Then a reconciliation"}
    )
    stats = check_analysis_citations(analysis, SEGMENTS, "")
    [kept] = analysis["competence_assessments"][0]["citations"]
    assert (kept["segment_id"], kept["start_sec"], kept["end_sec"]) == (
        "seg-1",
        12.0,
        75.0,
    )
    assert stats["dropped"] == 0


def test_timecodes_come_from_the_segment_not_the_model():
    analysis = _analysis(
        {
            "segment_id": "seg-2",
            "start_sec": 999.0,
            "end_sec": 1000.0,
            "quote": "  A RECONCILIATION loop\ncompares the ledger ",
        }
    )
    stats = check_analysis_citations(analysis, SEGMENTS, "")
    [kept] = analysis["competence_assessments"][0]["citations"]
    assert (kept["segment_id"], kept["start_sec"], kept["end_sec"]) == (
        "seg-2",
        40.0,
        75.0,
    )
    # The quote is stored as the model wrote it — whitespace and case
    # only decide whether it matches.
    assert kept["quote"] == "  A RECONCILIATION loop\ncompares the ledger "
    assert stats == {"total": 1, "dropped": 0, "dropped_ratio": 0.0}


def test_a_quote_without_a_segment_is_anchored_on_the_one_that_holds_it():
    analysis = _analysis({"segment_id": None, "quote": "idempotency key"})
    check_analysis_citations(analysis, SEGMENTS, "")
    [kept] = analysis["competence_assessments"][0]["citations"]
    assert (kept["segment_id"], kept["start_sec"]) == ("seg-1", 12.0)


def test_without_segments_only_the_transcript_text_can_back_a_quote():
    analysis = _analysis(
        {"segment_id": None, "start_sec": 3.0, "quote": "reconciliation loop"},
        {"segment_id": None, "quote": "something never said"},
    )
    check_analysis_citations(
        analysis, [], "Then a reconciliation loop compares the ledger."
    )
    [kept] = analysis["competence_assessments"][0]["citations"]
    assert kept["start_sec"] is None and kept["segment_id"] is None


def test_process_finding_citations_are_checked_too():
    analysis = {
        "competence_assessments": [],
        "process_findings": [
            {"citations": [{"segment_id": "seg-1", "quote": "not in the segment"}]}
        ],
    }
    stats = check_analysis_citations(analysis, SEGMENTS, "")
    assert analysis["process_findings"][0]["citations"] == []
    assert stats["dropped_ratio"] == 1.0


@pytest.mark.asyncio
@pytest.mark.usefixtures("dispatched", "worker_db")
async def test_the_analysis_task_saves_only_checked_citations(
    db: AsyncSession, monkeypatch
):
    from app.modules.recruitment import interview_service
    from app.modules.recruitment.models import Interview
    from app.modules.recruitment.tasks import analyze_interview_task

    interview, tenant, _profile = await _setup(db)
    segment = InterviewSegment(
        tenant_id=tenant.id,
        interview_id=interview.id,
        speaker="Candidate",
        start_sec=30.0,
        end_sec=55.0,
        text="We keyed every transfer on an idempotency key.",
    )
    db.add(segment)
    await db.commit()
    result = await interview_service.enqueue_analyze(db, tenant.id, interview.id)
    run_id = uuid.UUID(result["run_id"])

    async def _answer(*args, **kwargs):
        return InterviewAnalysisResult.model_validate(
            {
                "data_completeness": "partial",
                "verdict_summary": "Fine.",
                "competence_assessments": [
                    {
                        "competence_id": "distributed-systems",
                        "status": "assessed",
                        "score": 0.8,
                        "citations": [
                            {
                                "segment_id": str(segment.id),
                                "start_sec": 1.0,
                                "end_sec": 2.0,
                                "quote": "an idempotency key",
                            },
                            {"segment_id": str(uuid.uuid4()), "quote": "idempotency"},
                            {"segment_id": None, "quote": "I invented Kafka."},
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("app.modules.ai.llm_client.generate_json", _answer)
    out = await asyncio.to_thread(
        analyze_interview_task.run, str(interview.id), str(tenant.id)
    )
    assert out["status"] == "completed"

    [row] = (
        (
            await db.execute(
                select(AIAssessment)
                .where(AIAssessment.interview_id == interview.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert row.citations == [
        {
            "segment_id": str(segment.id),
            "start_sec": 30.0,
            "end_sec": 55.0,
            "quote": "an idempotency key",
        }
    ]
    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    expected = {"total": 3, "dropped": 2, "dropped_ratio": 0.667}
    assert refreshed.analysis_data["citation_check"] == expected
    runs = await _fresh_runs(db, interview.candidate_vacancy_id)
    assert runs[run_id].analysis_data["citation_check"] == expected


def test_typographic_quotes_and_an_ellipsis_around_a_quote_are_forgiven():
    """The model and the transcriber mix straight and curly forms; that is
    not a different quote. Kept in step with ``normalizeQuote`` on the page."""
    segments = [
        {"id": "s", "start_sec": 1.0, "end_sec": 2.0, "text": "I think she's right."}
    ]
    analysis = _analysis(
        {"segment_id": "s", "quote": "she’s right"},
        {"segment_id": "s", "quote": "«…she’s right…»"},
        {"segment_id": "s", "quote": '"...I think she\'s..."'},
    )
    stats = check_analysis_citations(analysis, segments, "")
    assert stats["dropped"] == 0
    # Lower-casing, not case folding: the page compares with JS
    # ``toLowerCase``, which leaves the German sharp s alone.
    assert (
        check_analysis_citations(
            _analysis({"segment_id": "s", "quote": "STRASSE"}),
            [{**segments[0], "text": "Die Straße."}],
            "",
        )["dropped"]
        == 1
    )


def test_reanchoring_moves_cached_citations_onto_this_interviews_segments():
    from app.modules.recruitment.prompts_interview import reanchor_analysis_citations

    analysis = _analysis(
        {
            "segment_id": "other-interview-seg",
            "start_sec": 5.0,
            "quote": "idempotency key",
        },
        {"segment_id": "seg-2", "quote": "reconciliation loop"},
    )
    reanchor_analysis_citations(analysis, SEGMENTS, "")
    cited = analysis["competence_assessments"][0]["citations"]
    assert [(c["segment_id"], c["start_sec"]) for c in cited] == [
        ("seg-1", 12.0),
        ("seg-2", 40.0),
    ]


@pytest.mark.asyncio
async def test_a_cache_hit_cites_the_target_interviews_own_segments(db: AsyncSession):
    """HRP-981 review: the cache replays an analysis made on another
    interview with the same transcript; its segment ids are not ours."""
    from app.modules.recruitment.analysis_cache_service import apply_cached_analysis
    from app.modules.recruitment.common import normalize_competence_id
    from app.modules.recruitment.models import InterviewAnalysisCache

    from tests.unit.test_hrp275_cached_analysis_matrix import _SLUGS
    from tests.unit.test_hrp275_cached_analysis_matrix import _setup as _matrix_setup

    tenant, _vacancy, interview = await _matrix_setup(db)
    segment = InterviewSegment(
        tenant_id=tenant.id,
        interview_id=interview.id,
        speaker="Candidate",
        start_sec=40.0,
        end_sec=60.0,
        text=f"Candidate: evidence for {_SLUGS[0]}.",
    )
    db.add(segment)
    cited = {
        "segment_id": str(uuid.uuid4()),
        "start_sec": 3.0,
        "end_sec": 4.0,
        "quote": f"evidence for {_SLUGS[0]}",
    }
    cached = InterviewAnalysisCache(
        tenant_id=tenant.id,
        cache_key=f"hrp981-{uuid.uuid4().hex}"[:64],
        analysis_data={
            "verdict_summary": "Strong hire",
            "competence_assessments": [
                {"competence_id": _SLUGS[0], "status": "assessed", "citations": [cited]}
            ],
        },
        assessments=[
            {
                "competence_id": str(normalize_competence_id(_SLUGS[0])),
                "score": 0.8,
                "status": "assessed",
                "citations": [cited],
            }
        ],
    )
    db.add(cached)
    await db.commit()

    await apply_cached_analysis(db, tenant.id, interview, cached)
    await db.commit()

    expected = [
        {**cited, "segment_id": str(segment.id), "start_sec": 40.0, "end_sec": 60.0}
    ]
    [row] = (
        (
            await db.execute(
                select(AIAssessment).where(AIAssessment.interview_id == interview.id)
            )
        )
        .scalars()
        .all()
    )
    assert row.citations == expected
    assert interview.analysis_data["competence_assessments"][0]["citations"] == expected
    # The cache row itself is not rewritten.
    assert cached.assessments[0]["citations"] == [cited]
