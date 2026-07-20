"""HRP-23: shared validator rejects deadlines in the past.

QA flagged that Assessment / PDP / Exam forms were saving dates from the
prior year. The fix lives in ``app.core.validators.not_past_deadline`` and is
wired into every Pydantic schema that accepts a deadline (Assessment create
/ update, MassAssessment create, PDP create / update, MassExam create).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.validators import not_past_deadline
from app.modules.assessment.schemas import (
    AssessmentCreate,
    AssessmentUpdate,
    MassAssessmentCreate,
    PDPCreate,
    PDPUpdate,
)
from app.modules.exam.schemas import MassExamCreate
from pydantic import ValidationError


class TestNotPastDeadlineHelper:
    def test_accepts_none(self) -> None:
        assert not_past_deadline(None) is None

    def test_accepts_today_utc_midnight(self) -> None:
        today_midnight = datetime.combine(
            datetime.now(UTC).date(),
            datetime.min.time(),
            tzinfo=UTC,
        )
        assert not_past_deadline(today_midnight) == today_midnight

    def test_accepts_future(self) -> None:
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        assert not_past_deadline(tomorrow) == tomorrow

    def test_accepts_yesterday_for_tz_budget(self) -> None:
        # The validator carries a one-day buffer so users in UTC-{8..12} don't
        # get 422'd when they pick "today" in their local timezone.
        yesterday = datetime.now(UTC) - timedelta(days=1)
        assert not_past_deadline(yesterday) == yesterday

    def test_rejects_two_days_ago(self) -> None:
        deep_past = datetime.now(UTC) - timedelta(days=2)
        with pytest.raises(ValueError, match="deadline cannot be in the past"):
            not_past_deadline(deep_past)

    def test_rejects_naive_two_days_ago(self) -> None:
        # frontend sends date-only → pydantic parses as naive midnight
        naive_deep_past = datetime.combine(
            (datetime.now(UTC) - timedelta(days=2)).date(),
            datetime.min.time(),
        )
        with pytest.raises(ValueError, match="deadline cannot be in the past"):
            not_past_deadline(naive_deep_past)


class TestSchemaWiring:
    """Smoke check that every schema using the helper actually raises 422."""

    def test_assessment_create_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            AssessmentCreate(
                employee_id="00000000-0000-0000-0000-000000000001",
                type_code="self",
                ended_at=datetime.now(UTC) - timedelta(days=3),
            )

    def test_assessment_update_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            AssessmentUpdate(ended_at=datetime.now(UTC) - timedelta(days=3))

    def test_assessment_update_allows_explicit_null_clear(self) -> None:
        # tri-state: clearing deadline must still work
        m = AssessmentUpdate(ended_at=None)
        assert m.ended_at is None
        assert "ended_at" in m.model_fields_set

    def test_mass_assessment_create_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            MassAssessmentCreate(
                title="Q1",
                employee_ids=["00000000-0000-0000-0000-000000000001"],
                type_code="self",
                ended_at=datetime.now(UTC) - timedelta(days=3),
            )

    def test_pdp_create_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            PDPCreate(
                title="My plan",
                employee_id="00000000-0000-0000-0000-000000000001",
                deadline=datetime.now(UTC) - timedelta(days=3),
            )

    def test_pdp_update_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            PDPUpdate(deadline=datetime.now(UTC) - timedelta(days=3))

    def test_mass_exam_create_rejects_past(self) -> None:
        with pytest.raises(ValidationError):
            MassExamCreate(
                title="Onboarding",
                ended_at=datetime.now(UTC) - timedelta(days=3),
            )
