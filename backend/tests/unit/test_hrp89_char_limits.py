"""HRP-89: tighten Title (<=100) and Description (<=250) limits on
Assessment, Mass Assessment / Assessment Group, PDP, Talent Card, and
Mass Exam. The previous limits were generous holdovers from the column
widths (`String(255)` / `String(1000)` / `String(2000)`); QA needs a
consistent product-wide cap so the UX doesn't render five different
overflow states.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment.schemas import (
    AssessmentCreate,
    AssessmentGroupUpdate,
    AssessmentUpdate,
    MassAssessmentCreate,
    PDPCreate,
    PDPUpdate,
)
from app.modules.exam.schemas import MassExamCreate
from app.modules.talent_market.schemas import TalentCardCreate, TalentCardUpdate
from pydantic import ValidationError


def _emp():
    return uuid.uuid4()


# ---------------------------------------------------------------------
# Title <= 100
# ---------------------------------------------------------------------


class TestTitleHardCap100:
    @pytest.mark.parametrize(
        "schema, payload",
        [
            (AssessmentCreate, lambda t: {"title": t, "employee_id": _emp(), "type_code": "self"}),
            (AssessmentUpdate, lambda t: {"title": t}),
            (
                MassAssessmentCreate,
                lambda t: {"title": t, "employee_ids": [_emp()], "type_code": "self"},
            ),
            (AssessmentGroupUpdate, lambda t: {"title": t}),
            (PDPCreate, lambda t: {"title": t, "employee_id": _emp()}),
            (PDPUpdate, lambda t: {"title": t}),
            (
                TalentCardCreate,
                lambda t: {"title": t, "description": "ok", "card_type": "vacancy"},
            ),
            (TalentCardUpdate, lambda t: {"title": t}),
            (MassExamCreate, lambda t: {"title": t}),
        ],
    )
    def test_exactly_100_chars_accepted(self, schema, payload):
        schema.model_validate(payload("x" * 100))

    @pytest.mark.parametrize(
        "schema, payload",
        [
            (AssessmentCreate, lambda t: {"title": t, "employee_id": _emp(), "type_code": "self"}),
            (AssessmentUpdate, lambda t: {"title": t}),
            (
                MassAssessmentCreate,
                lambda t: {"title": t, "employee_ids": [_emp()], "type_code": "self"},
            ),
            (AssessmentGroupUpdate, lambda t: {"title": t}),
            (PDPCreate, lambda t: {"title": t, "employee_id": _emp()}),
            (PDPUpdate, lambda t: {"title": t}),
            (
                TalentCardCreate,
                lambda t: {"title": t, "description": "ok", "card_type": "vacancy"},
            ),
            (TalentCardUpdate, lambda t: {"title": t}),
            (MassExamCreate, lambda t: {"title": t}),
        ],
    )
    def test_101_chars_rejected(self, schema, payload):
        with pytest.raises(ValidationError) as exc:
            schema.model_validate(payload("x" * 101))
        # Pydantic v2 surfaces the offending field in error.loc.
        assert any(
            "title" in (e.get("loc") or ()) for e in exc.value.errors()
        ), f"expected a `title` validation error, got {exc.value.errors()}"


# ---------------------------------------------------------------------
# Description <= 250 (only schemas that actually have description)
# ---------------------------------------------------------------------


class TestDescriptionHardCap250:
    @pytest.mark.parametrize(
        "schema, payload",
        [
            (
                TalentCardCreate,
                lambda d: {"title": "T", "description": d, "card_type": "vacancy"},
            ),
            (TalentCardUpdate, lambda d: {"description": d}),
            (MassExamCreate, lambda d: {"title": "T", "description": d}),
        ],
    )
    def test_exactly_250_chars_accepted(self, schema, payload):
        schema.model_validate(payload("x" * 250))

    @pytest.mark.parametrize(
        "schema, payload",
        [
            (
                TalentCardCreate,
                lambda d: {"title": "T", "description": d, "card_type": "vacancy"},
            ),
            (TalentCardUpdate, lambda d: {"description": d}),
            (MassExamCreate, lambda d: {"title": "T", "description": d}),
        ],
    )
    def test_251_chars_rejected(self, schema, payload):
        with pytest.raises(ValidationError) as exc:
            schema.model_validate(payload("x" * 251))
        assert any(
            "description" in (e.get("loc") or ()) for e in exc.value.errors()
        ), f"expected a `description` validation error, got {exc.value.errors()}"
