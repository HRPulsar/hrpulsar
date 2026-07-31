"""Phase CR11 — prompt builders + llm_client schema parameter."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from app.modules.ai import llm_client
from app.modules.ai_competence_generation import prompts
from app.modules.ai_competence_generation.schemas import (
    GeneratedIndicatorsSchema,
    GeneratedTreeSchema,
)


class TestTreePrompt:
    def test_carries_specializations_and_company(self) -> None:
        system, user = prompts.build_tree_prompt(
            specializations=["Backend", "QA"],
            divisions=["Engineering"],
            projects=["Payments"],
            company="Acme",
            source_tree={"groups": []},
            with_indicators=True,
            refinement=None,
            required_elements=["SQL", "API design"],
        )
        assert "Backend" in user
        assert "QA" in user
        assert "Engineering" in user
        assert "Acme" in user
        assert "SQL" in user
        assert "indicators" in system.lower()

    def test_with_indicators_false_disables_indicators(self) -> None:
        system, _ = prompts.build_tree_prompt(
            specializations=["Backend"],
            divisions=[],
            projects=[],
            company=None,
            source_tree={"groups": []},
            with_indicators=False,
            refinement=None,
        )
        assert "Do not include indicators" in system

    def test_refinement_block_included(self) -> None:
        _, user = prompts.build_tree_prompt(
            specializations=["Backend"],
            divisions=[],
            projects=[],
            company=None,
            source_tree={"groups": []},
            with_indicators=True,
            refinement="Add cloud platforms",
        )
        assert "Add cloud platforms" in user

    def test_few_shot_example_present_in_system(self) -> None:
        system, _ = prompts.build_tree_prompt(
            specializations=["Backend"],
            divisions=[],
            projects=[],
            company=None,
            source_tree={"groups": []},
            with_indicators=True,
            refinement=None,
        )
        assert "Example 1 input" in system
        assert "Example 1 output" in system


class TestMinIndicatorsRule:
    """HRP-144: every tree-scope prompt that opts into indicators must
    instruct the LLM to produce at least 3 indicators per skill level.
    Standalone indicator scope already carried that rule via
    ``_INDICATOR_RULES``; tree + group + matrix now include it too."""

    def test_tree_prompt_with_indicators_carries_minimum_rule(self) -> None:
        system, _ = prompts.build_tree_prompt(
            specializations=["Backend"],
            divisions=[],
            projects=[],
            company=None,
            source_tree={"groups": []},
            with_indicators=True,
            refinement=None,
        )
        assert "Indicator rules" in system
        assert "AT LEAST 3 indicators" in system

    def test_tree_prompt_without_indicators_skips_indicator_rules(self) -> None:
        system, _ = prompts.build_tree_prompt(
            specializations=["Backend"],
            divisions=[],
            projects=[],
            company=None,
            source_tree={"groups": []},
            with_indicators=False,
            refinement=None,
        )
        # No indicators requested → full ``_INDICATOR_RULES`` block (with
        # the level-calibration breakdown) is omitted to save tokens. The
        # short HRP-144 mention inside ``_TREE_RULES`` stays so the model
        # is aware the next call will be indicators with the 3-per-level
        # minimum.
        assert "Indicator rules" not in system
        assert "Basic level" not in system

    def test_group_prompt_with_indicators_carries_minimum_rule(self) -> None:
        system, _ = prompts.build_group_prompt(
            group_title="Communication",
            group_description=None,
            source_tree={"groups": []},
            with_indicators=True,
            refinement=None,
        )
        assert "Indicator rules" in system
        assert "AT LEAST 3 indicators" in system

    def test_indicators_prompt_explicit_minimum(self) -> None:
        system, _ = prompts.build_indicators_prompt(
            competence_title="Code review",
            competence_type="soft_skill",
            skill_levels=["basic", "intermediate", "advanced"],
            parents=["Engineering"],
            existing_indicators=[],
            refinement=None,
        )
        assert "AT LEAST 3 indicators" in system
        # Level-calibration guidance lands in the system prompt.
        assert "Basic level" in system
        assert "Advanced" in system

    def test_matrix_prompt_carries_minimum_rule(self) -> None:
        system, _ = prompts.build_specialization_matrix_prompt(
            specialization="Backend Engineer",
            grades=["Junior", "Middle", "Senior"],
            skill_levels=["basic", "intermediate", "advanced"],
            company=None,
            existing_matrix={},
            responsibilities=None,
            daily_tasks=None,
            weekly_tasks=None,
            kpi=None,
            requirements_text=None,
            parsed_files=None,
            refinement=None,
        )
        assert "AT LEAST 3 indicators per level" in system


class TestGroupPrompt:
    def test_targets_specific_group(self) -> None:
        system, user = prompts.build_group_prompt(
            group_title="Communication",
            group_description="Soft skills",
            source_tree={"groups": []},
            with_indicators=True,
            refinement=None,
            specialization="Support Lead",
        )
        assert "Communication" in system
        assert "Support Lead" in user


class TestIndicatorsPrompt:
    def test_renders_levels_and_existing(self) -> None:
        system, user = prompts.build_indicators_prompt(
            competence_title="Code review",
            competence_type="soft_skill",
            skill_levels=["basic", "intermediate"],
            parents=["Engineering", "Collaboration"],
            existing_indicators=[
                {"title": "Reads diff carefully", "skill_level": "basic"}
            ],
            refinement=None,
        )
        assert "Code review" in system
        assert "basic" in user
        assert "intermediate" in user
        assert "Reads diff carefully" in user
        assert "Indicator rules" in system

    def test_specialization_context_included_when_provided(self) -> None:
        # HRP-102: when an indicator session is launched from a matrix cell
        # the prompt should mention the spec + grades + sibling competences
        # so the LLM can calibrate level difficulty and avoid overlap.
        system, user = prompts.build_indicators_prompt(
            competence_title="Code review",
            competence_type="soft_skill",
            skill_levels=["basic", "intermediate"],
            parents=["Engineering"],
            existing_indicators=[],
            refinement=None,
            specialization_context={
                "specialization_title": "Backend Engineer",
                "grades": [
                    {"grade_title": "Junior"},
                    {"grade_title": "Middle"},
                    {"grade_title": "Senior"},
                ],
                "sibling_competences": ["SQL", "API design"],
            },
        )
        assert "Backend Engineer" in system
        assert "calibrate" in system.lower()
        assert "Backend Engineer" in user
        assert "Junior" in user
        assert "Senior" in user
        assert "SQL" in user
        assert "API design" in user

    def test_no_specialization_context_keeps_prompt_clean(self) -> None:
        system, user = prompts.build_indicators_prompt(
            competence_title="Code review",
            competence_type="soft_skill",
            skill_levels=["basic"],
            parents=[],
            existing_indicators=[],
            refinement=None,
        )
        assert "specialization" not in system.lower()
        assert "specialization_context" not in user


class TestSpecializationMatrixPrompt:
    """HRP-119 AC2: indicators_for_existing flag injects the extend-existing branch."""

    def _common(self) -> dict:
        return {
            "specialization": "Backend Engineer",
            "grades": ["Junior", "Middle", "Senior"],
            "skill_levels": ["basic", "intermediate", "advanced"],
            "company": "Acme Corp",
            "existing_matrix": {"specialization": {"title": "Backend Engineer"}},
            "responsibilities": None,
            "daily_tasks": None,
            "weekly_tasks": None,
            "kpi": None,
            "requirements_text": None,
            "parsed_files": None,
            "refinement": None,
        }

    def test_default_omits_extend_existing_branch(self) -> None:
        system, _ = prompts.build_specialization_matrix_prompt(**self._common())
        assert "existing_matrix" not in system

    def test_flag_adds_extend_existing_instruction(self) -> None:
        system, _ = prompts.build_specialization_matrix_prompt(
            **self._common(), indicators_for_existing=True
        )
        # The new branch mentions existing_matrix, NEW indicators, and the
        # invariants (no title / type / grade_levels changes).
        assert "existing_matrix" in system
        assert "NEW indicators" in system
        assert "do not change" in system.lower()

    def test_hrp159_context_blocks_inlined_into_user_payload(self) -> None:
        # HRP-159: when positions / divisions / existing_competences /
        # specialization_description are provided they MUST land in the
        # user payload (the LLM sees them) but stay out of the system
        # prompt (which only carries rules + task).
        params = self._common()
        params["refinement"] = "Bias towards security."
        system, user = prompts.build_specialization_matrix_prompt(
            **params,
            specialization_description="Designs payment APIs.",
            positions=[
                {"title": "Senior Backend", "description": "Owns the SDK"},
                {"title": "Tech Lead", "description": None},
            ],
            divisions=["Platform", "Payments"],
            existing_competences=[
                {"title": "SQL", "description": "Designs queries"},
            ],
        )
        assert "Senior Backend" in user
        assert "Platform" in user
        assert "Payments" in user
        assert "SQL" in user
        assert "Designs payment APIs." in user
        assert "Bias towards security." in user
        # Context data does not leak into the system prompt — keep
        # rules vs inputs cleanly separated.
        assert "Senior Backend" not in system
        assert "Bias towards security." not in system

    def test_hrp159_context_blocks_dropped_when_none(self) -> None:
        # With every HRP-159 block omitted, the prompt stays in its
        # legacy shape — no spurious empty arrays or null fields land in
        # the user payload.
        system, user = prompts.build_specialization_matrix_prompt(
            **self._common()
        )
        assert "positions" not in user
        assert "existing_competences" not in user
        assert "specialization_description" not in user
        # ``divisions`` is added only when callers pass a non-empty list;
        # confirm the legacy prompt does not carry the key either.
        assert '"divisions"' not in user


# ---------------------------------------------------------------------------
# llm_client.generate_json with schema=...
# ---------------------------------------------------------------------------


class TestLLMClientSchemaParam:
    async def test_schema_appended_to_system_and_validated(self) -> None:
        captured: dict = {}

        async def fake_anthropic(prompt, system, model, temperature, max_tokens, **kwargs):
            captured["system"] = system
            return json.dumps({"groups": []})

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            result = await llm_client.generate_json(
                "test",
                system="base",
                model="claude-sonnet-5",
                schema=GeneratedTreeSchema,
            )

        assert isinstance(result, GeneratedTreeSchema)
        assert "JSON Schema" in captured["system"]
        assert "base" in captured["system"]

    async def test_schema_validation_error_propagates(self) -> None:
        from pydantic import ValidationError

        async def fake_anthropic(prompt, system, model, temperature, max_tokens, **kwargs):
            return json.dumps({"groups": [{"foo": "bar"}]})  # bad shape

        with (
            patch.object(llm_client, "_generate_anthropic", new=fake_anthropic),
            pytest.raises(ValidationError),
        ):
            await llm_client.generate_json(
                "test",
                model="claude-sonnet-5",
                schema=GeneratedTreeSchema,
            )

    async def test_indicators_schema_validates_round_trip(self) -> None:
        async def fake_anthropic(prompt, system, model, temperature, max_tokens, **kwargs):
            return json.dumps(
                {"indicators": [{"title": "Knows the spec", "skill_level": "basic"}]}
            )

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            result = await llm_client.generate_json(
                "test",
                model="claude-sonnet-5",
                schema=GeneratedIndicatorsSchema,
            )
        assert isinstance(result, GeneratedIndicatorsSchema)
        assert result.indicators[0].title == "Knows the spec"

    async def test_no_schema_returns_raw_dict(self) -> None:
        async def fake_anthropic(prompt, system, model, temperature, max_tokens, **kwargs):
            return json.dumps([{"a": 1}])

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            result = await llm_client.generate_json("test", model="claude-sonnet-5")
        assert result == [{"a": 1}]
