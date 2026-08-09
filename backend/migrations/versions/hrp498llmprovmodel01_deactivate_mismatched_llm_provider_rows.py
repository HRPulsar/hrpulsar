"""Deactivate LLM provider rows whose model belongs to another provider

HRP-498: the BYOK form pre-filled a Claude model while the provider
dropdown moved independently and nothing cross-validated the pair, so
rows like ``{provider: "openai", model: "claude-…"}`` were saved. They sat
inert until the recruitment pipeline began dispatching on the tenant's
most recently updated active row — from then on every resume parse,
vacancy profile and interview analysis would 404 against a provider that
never served that model.

Rows are deactivated, not deleted: the stored key stays recoverable and
the tenant can fix the pair in the settings UI. Dispatch then falls back
to the platform credentials, which is what those tenants effectively used
before the row became live.

Revision ID: hrp498llmprovmodel01
Revises: 933b005f65e8
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp498llmprovmodel01"
down_revision: str | Sequence[str] | None = "933b005f65e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Prefix ownership mirrors ``ai.providers.PROVIDERS[*].classify_prefixes``
# and ``PROVIDER_ALIASES``; a model no provider claims by prefix (local
# server names) is free-form and left alone.
#
# Two carve-outs mirror ``ai.providers.model_matches_provider`` — without
# them this backfill switched off every legitimate proxy row on prod:
#   * canonical ``openai_compatible`` (openai_compatible itself plus the
#     azure/yandex/gigachat aliases) owns no prefix at all and serves
#     upstream model ids verbatim — {azure, gpt-4o} is the normal Azure
#     configuration, not a mismatch;
#   * any row carrying a ``base_url`` points at a proxy/local server
#     (LiteLLM, vLLM, Ollama) where the endpoint, not the model name,
#     decides what is served.
_MISMATCHED = """
    WITH classified AS (
        SELECT
            id,
            CASE
                WHEN model LIKE 'claude%' THEN 'anthropic'
                WHEN model LIKE 'gpt%'
                     OR model LIKE 'o1%'
                     OR model LIKE 'o3%'
                     OR model LIKE 'o4%'
                     OR model LIKE 'text-embedding%' THEN 'openai'
                WHEN model LIKE 'gemini%' THEN 'gemini'
                ELSE NULL
            END AS owner,
            CASE lower(provider)
                WHEN 'claude' THEN 'anthropic'
                WHEN 'azure' THEN 'openai_compatible'
                WHEN 'yandex' THEN 'openai_compatible'
                WHEN 'gigachat' THEN 'openai_compatible'
                ELSE lower(provider)
            END AS canonical,
            coalesce(settings ->> 'base_url', '') AS base_url
        FROM llm_provider_configs
        WHERE is_active
    )
    UPDATE llm_provider_configs AS c
    SET is_active = false,
        updated_at = now()
    FROM classified AS x
    WHERE c.id = x.id
      AND x.owner IS NOT NULL
      AND x.canonical <> 'openai_compatible'
      AND x.base_url NOT LIKE 'http%'
      AND x.owner <> x.canonical
"""


def upgrade() -> None:
    op.execute(_MISMATCHED)


def downgrade() -> None:
    # Irreversible by design: the migration cannot tell rows it deactivated
    # from rows an operator had already switched off.
    pass
