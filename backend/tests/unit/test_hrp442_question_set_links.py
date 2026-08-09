"""Question-set notifications carry a deep link (HRP-442, HRP-460).

The ready/failed notices used to name the candidate but gave no way to
reach the set. Both now ship a link to the candidate card, anchored on
the Interview questions block; the ready one also names the set so the
tab-bar opens it.
"""

from __future__ import annotations

import uuid

from app.modules.recruitment.notifications import _add_absolute_link
from app.modules.recruitment.question_service import candidate_question_deep_link

CANDIDATE = uuid.UUID("11111111-1111-1111-1111-111111111111")
VACANCY = uuid.UUID("22222222-2222-2222-2222-222222222222")
QSET = uuid.UUID("33333333-3333-3333-3333-333333333333")


class TestDeepLink:
    def test_points_at_the_candidate_card(self):
        link = candidate_question_deep_link(CANDIDATE, VACANCY)
        assert link.startswith(f"/recruitment/candidates/{CANDIDATE}")

    def test_carries_the_vacancy_context(self):
        # The candidate page reads this exact query key.
        assert f"vacancyId={VACANCY}" in candidate_question_deep_link(
            CANDIDATE, VACANCY
        )

    def test_anchors_on_the_interview_questions_block(self):
        assert candidate_question_deep_link(CANDIDATE, VACANCY).endswith(
            "#interview-questions"
        )

    def test_names_the_set_when_one_exists(self):
        link = candidate_question_deep_link(CANDIDATE, VACANCY, QSET)
        assert f"questionSet={QSET}" in link
        assert link.endswith("#interview-questions")

    def test_omits_the_set_when_generation_failed(self):
        assert "questionSet" not in candidate_question_deep_link(CANDIDATE, VACANCY)


class TestAbsoluteLinkForEmail:
    def test_relative_link_gets_the_frontend_base(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        ctx = {"link": "/recruitment/candidates/x#interview-questions"}
        _add_absolute_link(ctx)
        assert ctx["link_url"] == (
            "https://app.example.com/recruitment/candidates/x#interview-questions"
        )

    def test_absolute_link_is_left_alone(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        ctx = {"link": "https://elsewhere.test/page"}
        _add_absolute_link(ctx)
        assert ctx["link_url"] == "https://elsewhere.test/page"

    def test_missing_link_adds_nothing(self):
        ctx: dict = {}
        _add_absolute_link(ctx)
        assert "link_url" not in ctx

    def test_existing_link_url_wins(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        ctx = {"link": "/a", "link_url": "https://pinned.test/a"}
        _add_absolute_link(ctx)
        assert ctx["link_url"] == "https://pinned.test/a"


def _migration_bodies():
    # The test database is built from model metadata, so migration seeds
    # never run against it — assert on the migration's own table.
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "hrp442qslinks01_question_set_notification_links.py"
    )
    spec = importlib.util.spec_from_file_location("hrp442qslinks01", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BODIES


class TestTemplatesRenderTheLink:
    def test_every_locale_of_both_codes_is_covered(self):
        bodies = _migration_bodies()
        pairs = {(code, locale) for code, locale, _, _ in bodies}
        assert pairs == {
            ("recruitment.question_set_ready", "en"),
            ("recruitment.question_set_ready", "de"),
            ("recruitment.question_set_failed", "en"),
            ("recruitment.question_set_failed", "de"),
        }

    def test_new_bodies_reference_the_absolute_link(self):
        for code, locale, _, with_link in _migration_bodies():
            assert "{{ link_url }}" in with_link, f"{code}/{locale}"
            assert "<a href=" in with_link, f"{code}/{locale}"

    def test_old_bodies_have_no_link_so_the_guard_is_meaningful(self):
        # Each UPDATE is guarded by the pre-migration body; if that guard
        # already contained the link the migration would be a no-op.
        for code, locale, without, _ in _migration_bodies():
            assert "link_url" not in without, f"{code}/{locale}"
