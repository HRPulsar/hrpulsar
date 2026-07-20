"""Unit tests for service._role_filter_analysis (RECRUITING_MODULE.md §9.5)."""

from types import SimpleNamespace

from app.modules.recruitment.common import resolve_user_role
from app.modules.recruitment.interview_service import _role_filter_analysis


def _sample_payload() -> dict:
    return {
        "data_completeness": "full",
        "verdict_summary": "Strong fit",
        "competence_assessments": [
            {
                "competence_id": "c1",
                "score": 4.5,
                "status": "assessed",
                "citations": [{"quote": "I have 8 years of Python"}],
                "reasoning": "Detailed reasoning that hiring manager should not see",
            }
        ],
        "process_findings": [
            {
                "finding_type": "leading_question",
                "severity": "moderate",
                "citations": [{"quote": "You probably did X, right?"}],
                "positive_reframe": "Try open-ended questions next time.",
                "full_description": "Interviewer used a leading question that biased the answer.",
            }
        ],
        "blind_spots": [
            {"competence_id": "c2", "human_score": None, "suggested_question": "?"}
        ],
        "red_flags": [
            {
                "flag_type": "evasion",
                "severity": "minor",
                "evidence": [],
                "description": "Avoided salary discussion",
            }
        ],
    }


def test_role_filter_returns_full_payload_for_recruiter():
    payload = _sample_payload()
    out = _role_filter_analysis(payload, "recruiter")
    assert out is payload


def test_role_filter_returns_full_payload_for_admin_hr_hrd():
    payload = _sample_payload()
    for role in ["admin", "HR", "Hrd"]:
        assert _role_filter_analysis(payload, role) is payload


def test_role_filter_strips_red_flags_for_hiring_manager():
    out = _role_filter_analysis(_sample_payload(), "hiring_manager")
    assert "red_flags" not in out


def test_role_filter_reduces_process_findings_to_positive_reframe():
    out = _role_filter_analysis(_sample_payload(), "hiring_manager")
    findings = out["process_findings"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["positive_reframe"]
    assert "severity" not in finding
    assert "citations" not in finding
    assert "full_description" not in finding


def test_role_filter_drops_competence_reasoning_for_hiring_manager():
    out = _role_filter_analysis(_sample_payload(), "hiring_manager")
    assessments = out["competence_assessments"]
    assert len(assessments) == 1
    assert "reasoning" not in assessments[0]
    assert assessments[0]["score"] == 4.5
    assert assessments[0]["citations"]


def test_role_filter_returns_none_for_unknown_role():
    out = _role_filter_analysis(_sample_payload(), "invited_evaluator")
    assert out is None


def test_role_filter_handles_none_payload():
    assert _role_filter_analysis(None, "recruiter") is None


def test_role_filter_handles_missing_findings_field():
    payload = {"verdict_summary": "ok"}
    out = _role_filter_analysis(payload, "hiring_manager")
    assert out["verdict_summary"] == "ok"
    assert out["process_findings"] == []
    assert out["competence_assessments"] == []


def _user_with_codes(*codes: str):
    return SimpleNamespace(
        roles=[SimpleNamespace(code=code) for code in codes]
    )


def test_resolve_user_role_admin_wins_over_others():
    user = _user_with_codes("admin", "hiring_manager")
    assert resolve_user_role(user) == "admin"


def test_resolve_user_role_returns_recruiter_when_no_admin():
    user = _user_with_codes("recruiter", "hiring_manager")
    assert resolve_user_role(user) == "recruiter"


def test_resolve_user_role_falls_back_to_hiring_manager():
    assert resolve_user_role(_user_with_codes("hiring_manager")) == "hiring_manager"


def test_resolve_user_role_unknown_role_returns_none():
    assert resolve_user_role(_user_with_codes("employee")) is None


def test_resolve_user_role_no_roles_returns_none():
    assert resolve_user_role(SimpleNamespace(roles=[])) is None


def test_resolve_user_role_handles_missing_attribute():
    assert resolve_user_role(SimpleNamespace()) is None
