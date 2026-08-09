"""Interview-question vocabularies stay aligned (HRP-486).

The same goal / priority / source codes are produced by AI generation,
accepted on manual add, stored as column defaults, sorted by the export
and rendered by the PDF. They used to be redeclared in five places; this
suite fails the moment one of them drifts.
"""

from __future__ import annotations

import typing

from app.modules.recruitment import question_pdf, question_service
from app.modules.recruitment.models import Question
from app.modules.recruitment.prompts_interview import GeneratedQuestion
from app.modules.recruitment.schemas import (
    QuestionCreate2,
    QuestionGoal,
    QuestionPriority,
    QuestionSource,
)

GOALS = set(typing.get_args(QuestionGoal))
PRIORITIES = set(typing.get_args(QuestionPriority))
SOURCES = set(typing.get_args(QuestionSource))


def _field_literals(model: type, field: str) -> set[str]:
    return set(typing.get_args(model.model_fields[field].annotation))


def _column_default(field: str) -> str:
    return Question.__table__.columns[field].default.arg


class TestVocabularyIsCanonical:
    def test_expected_codes(self):
        # Pinned deliberately: a rename here is a wire + DB change and
        # must be a conscious edit, not a side effect.
        assert {
            "verify_skill",
            "clarify_experience",
            "probe_risk",
            "explore_motivation",
            "assess_fit",
        } == GOALS
        assert {"must_ask", "should_ask", "nice_to_ask"} == PRIORITIES
        assert {
            "ai_generated",
            "manual",
            "from_competency_indicator",
            "from_blind_spot",
        } == SOURCES


class TestGenerationMatchesSchema:
    def test_llm_contract_uses_the_same_goals(self):
        assert _field_literals(GeneratedQuestion, "goal") == GOALS

    def test_llm_contract_uses_the_same_priorities(self):
        assert _field_literals(GeneratedQuestion, "priority") == PRIORITIES

    def test_llm_contract_sources_are_a_subset(self):
        # The model never authors ``manual`` — that is a human action.
        assert _field_literals(GeneratedQuestion, "source") <= SOURCES

    def test_system_prompt_lists_the_real_codes(self):
        from app.modules.recruitment.prompts_interview import (
            QUESTION_SET_SYSTEM_PROMPT,
        )

        for code in GOALS | PRIORITIES:
            assert code in QUESTION_SET_SYSTEM_PROMPT, code


class TestManualAddMatchesSchema:
    def test_defaults_are_members_of_the_vocabulary(self):
        created = QuestionCreate2(text="x")
        assert created.goal in GOALS
        assert created.priority in PRIORITIES
        assert created.source in SOURCES

    def test_defaults_match_the_spec(self):
        created = QuestionCreate2(text="x")
        assert created.goal == "verify_skill"
        assert created.priority == "should_ask"

    def test_manual_add_sources_are_a_subset(self):
        assert _field_literals(QuestionCreate2, "source") <= SOURCES


class TestStorageMatchesSchema:
    def test_column_defaults_are_members(self):
        assert _column_default("goal") in GOALS
        assert _column_default("priority") in PRIORITIES
        assert _column_default("source") in SOURCES

    def test_column_defaults_match_the_pydantic_defaults(self):
        created = QuestionCreate2(text="x")
        assert _column_default("goal") == created.goal
        assert _column_default("priority") == created.priority


class TestDisplayMatchesSchema:
    def test_pdf_labels_cover_every_code(self):
        assert set(question_pdf._GOAL) == GOALS
        assert set(question_pdf._PRIORITY) == PRIORITIES
        assert set(question_pdf._SOURCE) == SOURCES

    def test_pdf_labels_are_human_readable(self):
        for label in (
            list(question_pdf._GOAL.values())
            + list(question_pdf._PRIORITY.values())
            + list(question_pdf._SOURCE.values())
        ):
            assert "_" not in label, label
            assert label[0].isupper(), label

    def test_sample_set_uses_the_vocabulary(self):
        for q in question_service.SAMPLE_QUESTION_SET["questions"]:
            assert q["goal"] in GOALS
            assert q["priority"] in PRIORITIES
            assert q["source"] in SOURCES


class TestSortingCoversEveryPriority:
    async def test_priority_sort_ranks_all_codes(self, db, tenant):
        # The export's priority sort keys off a literal dict; a code
        # missing from it silently sorts last.
        import inspect

        src = inspect.getsource(question_service.export_question_set_pdf)
        for code in PRIORITIES:
            assert f'"{code}"' in src, code
