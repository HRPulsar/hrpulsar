"""Tenant-level AI generation settings.

Per-tenant overrides for content language, model, effort tier, and prompt
context. All AI tasks (`generate_competences`, `generate_indicators`,
`suggest_pdp`, `generate_positions`) read these settings via
`service.get_or_default(...)` and apply them through `llm_client.generate`
and `prompts.build_system_*`.
"""
