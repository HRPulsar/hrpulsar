"""HRP-1240: every model the registry makes pickable has its own output cap."""

from __future__ import annotations

import pytest
from app.modules.ai import model_registry

_CAP_MAPS = {
    "anthropic": model_registry.ANTHROPIC_OUTPUT_CAPS,
    "openai": model_registry.OPENAI_OUTPUT_CAPS,
    "gemini": model_registry.GEMINI_OUTPUT_CAPS,
}
_REGISTRY_MODELS = sorted(
    {
        (provider, model)
        for tier in (
            model_registry.FAST_MODELS,
            model_registry.BALANCED_MODELS,
            model_registry.THOROUGH_MODELS,
        )
        for provider, model in tier.items()
        if provider in _CAP_MAPS
    }
    | {("anthropic", model_registry.ANTHROPIC_FABLE)}
    | {(provider, model) for provider, model, _tier in model_registry.PREVIOUS_MODELS}
)


class TestRegistryModelsHaveTheirOwnCap:
    # HRP-1240: a pickable model left to the fallback cap is cut short (or
    # rejected); every tier, flagship and previous model is listed.
    @pytest.mark.parametrize(("provider", "model"), _REGISTRY_MODELS)
    def test_cap_entry_covers_the_model(self, provider: str, model: str) -> None:
        assert any(model.startswith(prefix) for prefix in _CAP_MAPS[provider])

    def test_longest_prefix_wins(self) -> None:
        caps = {"claude-x-5": 1000, "claude-x-5-5": 2000, "claude-x": 10}
        assert model_registry.output_cap(caps, "claude-x-5-5", 1) == 2000
        assert model_registry.output_cap(caps, "claude-x-5", 1) == 1000
        assert model_registry.output_cap(caps, "claude-y", 1) == 1
