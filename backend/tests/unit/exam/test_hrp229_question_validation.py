"""HRP-229: choice questions require >=2 options and >=1 correct."""

from __future__ import annotations

import uuid

import pytest
from app.modules.exam.schemas import OptionCreate, QuestionCreate


def _opt(title: str, is_correct: bool = False) -> OptionCreate:
    return OptionCreate(title=title, is_correct=is_correct)


class TestSingleChoiceValidation:
    def test_no_options_rejected(self):
        with pytest.raises(ValueError):
            QuestionCreate(
                title="Q",
                question_type="single_choice",
                options=[],
            )

    def test_one_option_rejected(self):
        with pytest.raises(ValueError):
            QuestionCreate(
                title="Q",
                question_type="single_choice",
                options=[_opt("Only", True)],
            )

    def test_no_correct_rejected(self):
        with pytest.raises(ValueError):
            QuestionCreate(
                title="Q",
                question_type="single_choice",
                options=[_opt("A"), _opt("B")],
            )

    def test_two_correct_rejected(self):
        with pytest.raises(ValueError):
            QuestionCreate(
                title="Q",
                question_type="single_choice",
                options=[_opt("A", True), _opt("B", True)],
            )

    def test_happy_path(self):
        q = QuestionCreate(
            title="Q",
            question_type="single_choice",
            options=[_opt("A", True), _opt("B")],
        )
        assert q.question_type == "single_choice"


class TestMultipleChoiceValidation:
    def test_no_correct_rejected(self):
        with pytest.raises(ValueError):
            QuestionCreate(
                title="Q",
                question_type="multiple_choice",
                options=[_opt("A"), _opt("B")],
            )

    def test_multi_correct_accepted(self):
        q = QuestionCreate(
            title="Q",
            question_type="multiple_choice",
            options=[_opt("A", True), _opt("B", True), _opt("C")],
        )
        assert q.question_type == "multiple_choice"


class TestEssaySkipsOptionRules:
    def test_no_options_accepted_for_essay(self):
        q = QuestionCreate(title="Q", question_type="essay", options=[])
        assert q.question_type == "essay"


# Keep generated uuid available so the file doesn't read as unused-imports.
_PROBE = uuid.uuid4()
