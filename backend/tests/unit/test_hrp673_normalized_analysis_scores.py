"""HRP-673: analysis competence scores are rebased onto the tenant scale.

``analysis_data`` stores the canonical raw 0..1 score; the read path
attaches ``normalized_score`` (raw x scale_max) so the UI never divides a
raw score by the tenant scale again.
"""

from app.modules.recruitment.interview_service import _with_normalized_scores


def test_rebases_scores_onto_tenant_scale() -> None:
    analysis = {
        "verdict": "recommended",
        "competence_assessments": [
            {"competence_id": "x", "score": 0.9, "status": "assessed"},
            {"competence_id": "y", "score": 0.5, "status": "assessed"},
        ],
    }
    out = _with_normalized_scores(analysis, 5)
    assert out["competence_assessments"][0]["normalized_score"] == 4.5
    assert out["competence_assessments"][1]["normalized_score"] == 2.5
    # The raw score stays next to the normalized one.
    assert out["competence_assessments"][0]["score"] == 0.9
    assert out["verdict"] == "recommended"


def test_identity_fallback_without_active_scale() -> None:
    out = _with_normalized_scores({"competence_assessments": [{"score": 0.9}]}, None)
    assert out["competence_assessments"][0]["normalized_score"] == 0.9


def test_none_inputs_propagate() -> None:
    assert _with_normalized_scores(None, 5) is None
    assert _with_normalized_scores({}, 5) == {}
    out = _with_normalized_scores({"competence_assessments": [{"score": None}]}, 5)
    assert out["competence_assessments"][0]["normalized_score"] is None


def test_source_analysis_data_is_not_mutated() -> None:
    # ``_role_filter_analysis`` returns the ORM JSONB dict itself for full
    # roles — enrichment must copy, never write into the session object.
    analysis = {"competence_assessments": [{"score": 0.5}]}
    _with_normalized_scores(analysis, 5)
    assert "normalized_score" not in analysis["competence_assessments"][0]
