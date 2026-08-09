"""AI Insights analysis notifications (HRP-494).

The only analysis notice was ``recruitment.interview_analysis_ready``,
fired with ``candidate_name=None`` — the recruiter got an email whose
subject read literally "AI analysis ready: None" and whose body offered
no way back into the product.

Covered here: the four new codes exist for both locales with the
ticket's subjects, every body deep-links into AI Insights, the deep
link itself points at the right block, and the legacy template no
longer prints "None".
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

from app.modules.recruitment.notifications import (
    EVENT_TEMPLATE,
    _add_absolute_link,
)
from app.modules.recruitment.resume_analysis_service import (
    candidate_ai_insights_deep_link,
)
from jinja2 import Template

CANDIDATE = uuid.UUID("11111111-1111-1111-1111-111111111111")
VACANCY = uuid.UUID("22222222-2222-2222-2222-222222222222")

NEW_CODES = {
    "recruitment.resume_analysis_ready",
    "recruitment.resume_analysis_failed",
    "recruitment.full_analysis_ready",
    "recruitment.full_analysis_failed",
}


def _migration():
    # The test database is built from model metadata, so migration seeds
    # never run against it — assert on the migration's own tables.
    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "hrp494ainotify01_ai_insights_analysis_notifications.py"
    )
    spec = importlib.util.spec_from_file_location("hrp494ainotify01", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDeepLink:
    def test_points_at_the_candidate_card(self):
        link = candidate_ai_insights_deep_link(CANDIDATE, VACANCY)
        assert link.startswith(f"/recruitment/candidates/{CANDIDATE}")

    def test_carries_the_vacancy_context(self):
        # AI Insights is per (candidate, vacancy) — without this key the
        # section would open on whichever application sorts first.
        assert f"vacancyId={VACANCY}" in candidate_ai_insights_deep_link(
            CANDIDATE, VACANCY
        )

    def test_anchors_on_the_ai_insights_block(self):
        assert candidate_ai_insights_deep_link(CANDIDATE, VACANCY).endswith(
            "#ai-insights"
        )

    def test_email_gets_an_absolute_url(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        ctx = {"link": candidate_ai_insights_deep_link(CANDIDATE, VACANCY)}
        _add_absolute_link(ctx)
        assert ctx["link_url"].startswith("https://app.example.com/recruitment/")
        assert ctx["link_url"].endswith("#ai-insights")


class TestEventMapping:
    def test_all_four_codes_are_routed(self):
        mapped = {
            EVENT_TEMPLATE[event]
            for event in (
                "recruitment.candidate.resume_analysis_ready",
                "recruitment.candidate.resume_analysis_failed",
                "recruitment.candidate.full_analysis_ready",
                "recruitment.candidate.full_analysis_failed",
            )
        }
        assert mapped == NEW_CODES

    def test_legacy_interview_mapping_is_preserved(self):
        """The interview-page cache-hit path still publishes it."""
        assert (
            EVENT_TEMPLATE["recruitment.interview.analysis_ready"]
            == "recruitment.interview_analysis_ready"
        )


class TestSeededTemplates:
    def test_every_code_ships_en_and_de(self):
        pairs = {(code, locale) for code, locale, _, _ in _migration().TEMPLATES}
        assert pairs == {(c, loc) for c in NEW_CODES for loc in ("en", "de")}

    def test_subjects_match_the_ticket(self):
        subjects = {
            (code, locale): subject
            for code, locale, subject, _ in _migration().TEMPLATES
        }
        assert (
            subjects[("recruitment.resume_analysis_ready", "en")]
            == "Resume analysis ready for {{ candidate_name }}"
        )
        assert (
            subjects[("recruitment.full_analysis_ready", "en")]
            == "Interview analysis ready for {{ candidate_name }}"
        )

    def test_every_body_deep_links_into_ai_insights(self):
        for code, locale, _, body in _migration().TEMPLATES:
            assert "{{ link_url }}" in body, f"{code}/{locale}"
            assert "<a href=" in body, f"{code}/{locale}"

    def test_every_body_names_the_candidate(self):
        for code, locale, subject, body in _migration().TEMPLATES:
            assert "{{ candidate_name }}" in subject, f"{code}/{locale}"
            assert "{{ candidate_name }}" in body, f"{code}/{locale}"

    def test_resume_and_full_wordings_are_distinguishable(self):
        """The recruiter must be able to tell which mode they paid for."""
        bodies = {
            (code, locale): body
            for code, locale, _, body in _migration().TEMPLATES
        }
        resume_en = bodies[("recruitment.resume_analysis_ready", "en")]
        full_en = bodies[("recruitment.full_analysis_ready", "en")]
        assert "resume-only" in resume_en
        assert "interview" in full_en
        assert resume_en != full_en

    def test_rendered_subject_carries_the_real_name(self):
        subjects = {
            (code, locale): subject
            for code, locale, subject, _ in _migration().TEMPLATES
        }
        rendered = Template(
            subjects[("recruitment.full_analysis_ready", "en")]
        ).render(candidate_name="Viktoriya Koptsova")
        assert rendered == "Interview analysis ready for Viktoriya Koptsova"
        assert "None" not in rendered


class TestLegacyTemplateNoLongerPrintsNone:
    def test_guarded_update_targets_the_currently_seeded_text(self):
        for locale, old_subject, old_body, _, _ in _migration().LEGACY:
            assert "{% if" not in old_subject, locale
            assert "{% if" not in old_body, locale

    def test_missing_name_no_longer_renders_none(self):
        for locale, _, _, new_subject, new_body in _migration().LEGACY:
            subject = Template(new_subject).render(candidate_name=None)
            body = Template(new_body).render(candidate_name=None)
            assert "None" not in subject, locale
            assert "None" not in body, locale
            assert subject.strip()

    def test_present_name_still_renders(self):
        for locale, _, _, new_subject, new_body in _migration().LEGACY:
            subject = Template(new_subject).render(candidate_name="Nina Orlova")
            body = Template(new_body).render(candidate_name="Nina Orlova")
            assert "Nina Orlova" in subject, locale
            assert "Nina Orlova" in body, locale


class _FakeSession:
    """Stand-in for the *sync* session the Celery failure path holds."""

    def __init__(self, rows: dict):
        self._rows = rows

    def get(self, model, pk):
        return self._rows.get((model, pk))


class TestFailureNoticeCandidateName:
    """HRP-494 REDO — the name comes from ``Candidate.full_name``.

    ``_candidate_name_for_cv`` read ``candidate.person`` only. A
    resume-sourced candidate has no Person row (``person_id`` is optional
    since HRP-181 REDO), which is the ordinary case for these two failure
    notices — so they went out as "Resume analysis failed for " with a
    hole where the name belongs.
    """

    def test_resume_sourced_candidate_is_named(self):
        from app.modules.recruitment.models import Candidate, CandidateVacancy
        from app.modules.recruitment.tasks.analysis import _candidate_name_for_cv

        cv_id, cand_id = uuid.uuid4(), uuid.uuid4()
        db = _FakeSession(
            {
                (CandidateVacancy, cv_id): CandidateVacancy(
                    id=cv_id, candidate_id=cand_id
                ),
                (Candidate, cand_id): Candidate(
                    id=cand_id, full_name="Nadezhda Voronova"
                ),
            }
        )
        assert _candidate_name_for_cv(db, cv_id) == "Nadezhda Voronova"

    def test_missing_rows_stay_none(self):
        from app.modules.recruitment.tasks.analysis import _candidate_name_for_cv

        assert _candidate_name_for_cv(_FakeSession({}), None) is None
        assert _candidate_name_for_cv(_FakeSession({}), uuid.uuid4()) is None


class _Recorder:
    """Captures the SQL a migration issues, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement, params=None):  # noqa: ANN001
        self.statements.append(" ".join(str(statement).split()))
        return None


class TestDowngradeSurvivesSentNotifications:
    """``notifications.template_id`` is an FK with no ON DELETE clause.

    Dropping the seeded templates without clearing the in-app rows first
    made the downgrade fail on any installation that had already sent one
    of these four notices — exactly the installations that would want to
    roll back. ``hrp373evaltmpl01`` already does it in the right order.
    """

    def test_children_are_cleared_before_the_template(self, monkeypatch):
        module = _migration()

        class _FakeOp:
            @staticmethod
            def get_bind():
                return recorder

        recorder = _Recorder()
        monkeypatch.setattr(module, "op", _FakeOp)
        module.downgrade()

        deletes = [s for s in recorder.statements if s.startswith("DELETE FROM")]
        template_deletes = [
            i
            for i, s in enumerate(deletes)
            if s.startswith("DELETE FROM notification_templates")
        ]
        assert len(template_deletes) == len(module.TEMPLATES)
        for idx in template_deletes:
            assert idx > 0, "a template row is dropped before its notifications"
            assert deletes[idx - 1].startswith("DELETE FROM notifications")
