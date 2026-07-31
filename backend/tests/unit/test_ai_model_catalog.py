"""HRP-466 — dynamic AI model catalog: seed, discovery classification,
multiplier inheritance, dedup, resilience, and the approved-only tenant
filter."""

import uuid
from unittest.mock import patch

import pytest
from app.config import settings
from app.modules.ai import (
    llm_client,
    model_catalog_service,
    model_registry,
    provider_discovery,
)
from app.modules.ai.models import ModelCatalogEntry
from app.modules.ai_settings import service as ai_settings_service
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _registry_guard():
    """Restore the in-memory whitelist mutated by upsert_allowed_model."""
    snapshot = ai_settings_service.list_allowed_models()
    yield
    ai_settings_service.register_models(snapshot)


class TestNormalization:
    async def test_provider_specific_version_suffixes(self) -> None:
        normalize = model_catalog_service.normalize_model_id
        assert normalize("claude-haiku-4-5-20251001", "anthropic") == "claude-haiku-4-5"
        assert normalize("claude-sonnet-5", "anthropic") == "claude-sonnet-5"
        assert normalize("gpt-4o-2024-08-06", "openai") == "gpt-4o"
        assert normalize("gpt-4o", "openai") == "gpt-4o"
        assert normalize("gemini-1.5-pro-002", "gemini") == "gemini-1.5-pro"
        assert normalize("gemini-embedding-001", "gemini") == "gemini-embedding"
        assert normalize("gemini-2.5-pro", "gemini") == "gemini-2.5-pro"

    async def test_preview_and_exp_ids_stay_distinct(self) -> None:
        # Previews change behavior — they go through moderation as new
        # models instead of inheriting the family approval.
        normalize = model_catalog_service.normalize_model_id
        assert (
            normalize("gemini-2.5-flash-preview-05-20", "gemini")
            == "gemini-2.5-flash-preview-05-20"
        )
        assert normalize("gemini-exp-1206", "gemini") == "gemini-exp-1206"

    async def test_suffixes_never_leak_across_providers(self) -> None:
        normalize = model_catalog_service.normalize_model_id
        assert normalize("gpt-4o-2024-08-06", "anthropic") == "gpt-4o-2024-08-06"
        assert normalize("claude-haiku-4-5-20251001", "openai") == (
            "claude-haiku-4-5-20251001"
        )
        assert normalize("some-model-123", "unknown") == "some-model-123"


class TestSeed:
    async def test_seed_is_idempotent_and_covers_tiers(self, db: AsyncSession) -> None:
        # The shared test DB may already carry the seed from earlier tests —
        # only the second run is guaranteed to be a no-op.
        await model_catalog_service.seed_from_registry(db)
        added_second = await model_catalog_service.seed_from_registry(db)
        assert added_second == 0

        rows = await model_catalog_service.list_catalog(db)
        by_id = {row.model_id: row for row in rows}
        assert model_registry.ANTHROPIC_BALANCED in by_id
        assert by_id[model_registry.ANTHROPIC_BALANCED].tier == "balanced"
        assert by_id[model_registry.ANTHROPIC_FAST].tier == "fast"
        # The flagship is pickable but deliberately tier-less.
        assert by_id[model_registry.ANTHROPIC_FABLE].tier is None
        # Scope to seed rows: moderation tests elsewhere in the suite leave
        # their own pending discovered rows in the shared test DB.
        assert all(row.status == "approved" for row in rows if row.source == "seed")

    async def test_concurrent_seed_race_returns_zero(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        # Two uvicorn workers can race the read-then-insert from the lazy
        # GET-handler seed — the loser's commit hits the unique constraint
        # and must fold into "already seeded", not a 500.
        unique = f"claude-race-{uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            model_catalog_service,
            "_seed_rows",
            lambda: [{"provider": "anthropic", "model_id": unique, "tier": None}],
        )

        async def failing_commit() -> None:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        monkeypatch.setattr(db, "commit", failing_commit)
        added = await model_catalog_service.seed_from_registry(db)
        assert added == 0


class TestDiscoveryClassification:
    async def test_redated_snapshot_inherits_registry_multiplier(
        self, db: AsyncSession, _registry_guard
    ) -> None:
        # A curated-style family: catalog row carries NULL, the price lives
        # in the in-memory registry under the dateless id. The snapshot must
        # materialize the effective multiplier — otherwise it would bill 1.0.
        base_id = f"claude-family-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": base_id, "label": base_id}]
            )
        ai_settings_service.upsert_allowed_model(
            {
                "provider": "anthropic",
                "model": base_id,
                "label": base_id,
                "credit_multiplier": 2.2,
            }
        )
        snap_id = f"{base_id}-20260901"
        with patch.object(settings, "deployment_mode", "saas"):
            stats = await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": snap_id, "label": "snap"}]
            )
        assert stats["new_versions"] == 1
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        snapshot = rows[snap_id]
        assert snapshot.status == "approved"
        assert snapshot.tier == rows[base_id].tier
        assert snapshot.source == "discovered"
        assert snapshot.credit_multiplier == pytest.approx(2.2)

    async def test_snapshot_of_unpriced_family_is_pending_under_saas(
        self, db: AsyncSession
    ) -> None:
        # Family approved but priced nowhere (row NULL, not in the registry):
        # auto-approving the snapshot would bill at a silent 1.0 — it must
        # go through moderation as a new model instead.
        base_id = f"claude-unpriced-fam-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": base_id, "label": base_id}]
            )
        snap_id = f"{base_id}-20260901"
        with patch.object(settings, "deployment_mode", "saas"):
            stats = await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": snap_id, "label": "snap"}]
            )
        assert stats["new_models"] == 1
        assert stats["new_versions"] == 0
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        assert rows[snap_id].status == "pending"
        assert rows[snap_id].enabled is False

    async def test_snapshot_of_unpriced_family_auto_approves_onprem(
        self, db: AsyncSession
    ) -> None:
        # Community: nothing to price, family inheritance applies as-is.
        base_id = f"claude-onprem-fam-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": base_id, "label": base_id}]
            )
            stats = await model_catalog_service.upsert_discovered(
                db,
                "anthropic",
                [{"model_id": f"{base_id}-20260901", "label": "snap"}],
            )
        assert stats["new_versions"] == 1

    async def test_new_model_is_pending_under_saas(self, db: AsyncSession) -> None:
        model_id = f"claude-newmodel-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "saas"):
            stats = await model_catalog_service.upsert_discovered(
                db,
                "anthropic",
                [{"model_id": model_id, "label": "Sonnet Next"}],
            )
        assert stats["new_models"] == 1
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        entry = rows[model_id]
        assert entry.status == "pending"
        assert entry.enabled is False
        assert entry.credit_multiplier is None
        # Tenants never see it.
        approved = await model_catalog_service.approved_models(db)
        assert model_id not in {r.model_id for r in approved}

    async def test_new_model_is_auto_approved_onprem(self, db: AsyncSession) -> None:
        model_id = f"claude-newmodel-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db,
                "anthropic",
                [{"model_id": model_id, "label": "Sonnet Next"}],
            )
        approved = await model_catalog_service.approved_models(db)
        assert model_id in {r.model_id for r in approved}

    async def test_known_model_only_bumps_last_seen(self, db: AsyncSession) -> None:
        await model_catalog_service.seed_from_registry(db)
        before = {
            r.model_id: r.last_seen
            for r in await model_catalog_service.list_catalog(db)
        }
        stats = await model_catalog_service.upsert_discovered(
            db,
            "anthropic",
            [{"model_id": model_registry.ANTHROPIC_BALANCED, "label": "x"}],
        )
        assert stats == {"seen": 1, "new_versions": 0, "new_models": 0, "rejected": 0}
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        assert (
            rows[model_registry.ANTHROPIC_BALANCED].last_seen
            >= before[model_registry.ANTHROPIC_BALANCED]
        )


class TestFamilyDeterminism:
    async def test_canonical_dateless_row_wins(self, db: AsyncSession) -> None:
        # Family with a canonical dateless row AND a dated row that carry
        # different tier/multiplier values: inheritance must come from the
        # canonical row, whatever order the SELECT returns them in.
        base = f"claude-det-{uuid.uuid4().hex[:6]}"
        db.add(
            ModelCatalogEntry(
                provider="anthropic",
                model_id=base,
                label=base,
                tier="balanced",
                status="approved",
                enabled=True,
                credit_multiplier=3.0,
                source="discovered",
            )
        )
        db.add(
            ModelCatalogEntry(
                provider="anthropic",
                model_id=f"{base}-20250101",
                label="old snap",
                tier="fast",
                status="approved",
                enabled=True,
                credit_multiplier=2.0,
                source="discovered",
            )
        )
        await db.commit()

        snap_id = f"{base}-20260301"
        with patch.object(settings, "deployment_mode", "saas"):
            stats = await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": snap_id, "label": "snap"}]
            )
        assert stats["new_versions"] == 1
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        assert rows[snap_id].tier == "balanced"
        assert rows[snap_id].credit_multiplier == pytest.approx(3.0)

    async def test_priced_row_wins_over_newer_unpriced_snapshot(
        self, db: AsyncSession
    ) -> None:
        base = f"claude-det2-{uuid.uuid4().hex[:6]}"
        db.add(
            ModelCatalogEntry(
                provider="anthropic",
                model_id=f"{base}-20250101",
                label="priced snap",
                tier="fast",
                status="approved",
                enabled=True,
                credit_multiplier=2.0,
                source="discovered",
            )
        )
        db.add(
            ModelCatalogEntry(
                provider="anthropic",
                model_id=f"{base}-20260101",
                label="newer unpriced snap",
                tier="thorough",
                status="approved",
                enabled=True,
                credit_multiplier=None,
                source="discovered",
            )
        )
        await db.commit()

        snap_id = f"{base}-20260601"
        with patch.object(settings, "deployment_mode", "saas"):
            stats = await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": snap_id, "label": "snap"}]
            )
        assert stats["new_versions"] == 1
        rows = {r.model_id: r for r in await model_catalog_service.list_catalog(db)}
        assert rows[snap_id].tier == "fast"
        assert rows[snap_id].credit_multiplier == pytest.approx(2.0)


class TestDiscoveryFilters:
    async def test_openai_filter_keeps_only_chat_models(self, monkeypatch) -> None:
        listed = [
            "gpt-4o",
            "gpt-4o-2024-08-06",
            "o3-mini",
            "gpt-4o-audio-preview",
            "gpt-4o-realtime-preview",
            "gpt-4o-transcribe",
            "gpt-4o-mini-tts",
            "gpt-image-1",
            "gpt-3.5-turbo-instruct",
            "gpt-4o-search-preview",
            "text-embedding-3-small",
            "omni-moderation-latest",
            "dall-e-3",
            "whisper-1",
            "chatgpt-4o-latest",
        ]

        class FakeModel:
            def __init__(self, model_id: str) -> None:
                self.id = model_id

        class FakeModels:
            def list(self):
                async def gen():
                    for model_id in listed:
                        yield FakeModel(model_id)

                return gen()

        class FakeClient:
            models = FakeModels()

        monkeypatch.setattr(llm_client, "_get_openai", lambda key: FakeClient())
        out = await provider_discovery.discover_openai("key")
        assert {m["model_id"] for m in out} == {
            "gpt-4o",
            "gpt-4o-2024-08-06",
            "o3-mini",
        }

    async def test_gemini_filter_requires_generate_content(self, monkeypatch) -> None:
        listed = [
            ("models/gemini-2.5-pro", ["generateContent", "countTokens"]),
            ("models/gemini-2.5-flash", ["generateContent"]),
            ("models/gemini-embedding-001", ["embedContent"]),
            ("models/gemini-2.5-flash-preview-tts", ["generateSpeech"]),
            ("models/gemini-2.0-flash-live-001", ["bidiGenerateContent"]),
            ("models/imagen-3.0-generate-002", ["predict"]),
        ]

        class FakeModel:
            def __init__(self, name: str, actions: list[str]) -> None:
                self.name = name
                self.supported_actions = actions
                self.display_name = name

        class FakeAioModels:
            async def list(self):
                async def gen():
                    for name, actions in listed:
                        yield FakeModel(name, actions)

                return gen()

        class FakeAio:
            models = FakeAioModels()

        class FakeClient:
            aio = FakeAio()

        monkeypatch.setattr(llm_client, "_get_gemini", lambda key: FakeClient())
        out = await provider_discovery.discover_gemini("key")
        assert {m["model_id"] for m in out} == {"gemini-2.5-pro", "gemini-2.5-flash"}


class TestDiscoverySweepResilience:
    async def test_provider_failure_preserves_catalog(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        await model_catalog_service.seed_from_registry(db)
        before = len(await model_catalog_service.list_catalog(db))

        new_id = f"gemini-next-{uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            provider_discovery,
            "discoverable_providers",
            lambda: [("anthropic", "k"), ("gemini", "k")],
        )

        async def fake_discover(provider: str, api_key: str):
            if provider == "anthropic":
                raise RuntimeError("api down")
            return [{"model_id": new_id, "label": "Gemini Next"}]

        monkeypatch.setattr(provider_discovery, "discover", fake_discover)

        with patch.object(settings, "deployment_mode", "onprem"):
            summary = await model_catalog_service.run_discovery_sweep(db)

        assert summary["anthropic"] == {"error": "RuntimeError"}
        assert summary["gemini"]["new_models"] == 1
        rows = await model_catalog_service.list_catalog(db)
        # Nothing lost: the failed provider's rows are all still there.
        assert len(rows) == before + 1

    async def test_upsert_failure_is_isolated_per_provider(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        # A DB error inside the upsert (not just the HTTP discovery) must
        # not kill the sweep for the remaining providers.
        await model_catalog_service.seed_from_registry(db)
        new_id = f"gemini-next-{uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            provider_discovery,
            "discoverable_providers",
            lambda: [("anthropic", "k"), ("gemini", "k")],
        )

        async def fake_discover(provider: str, api_key: str):
            return [{"model_id": new_id, "label": "Gemini Next"}]

        monkeypatch.setattr(provider_discovery, "discover", fake_discover)

        real_upsert = model_catalog_service.upsert_discovered

        async def failing_upsert(session, provider, models):
            if provider == "anthropic":
                raise RuntimeError("db down")
            return await real_upsert(session, provider, models)

        monkeypatch.setattr(model_catalog_service, "upsert_discovered", failing_upsert)

        with patch.object(settings, "deployment_mode", "onprem"):
            summary = await model_catalog_service.run_discovery_sweep(db)

        assert summary["anthropic"] == {"error": "RuntimeError"}
        assert summary["gemini"]["new_models"] == 1

    async def test_seed_failure_does_not_kill_sweep(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        new_id = f"gemini-next-{uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            provider_discovery,
            "discoverable_providers",
            lambda: [("gemini", "k")],
        )

        async def fake_discover(provider: str, api_key: str):
            return [{"model_id": new_id, "label": "Gemini Next"}]

        monkeypatch.setattr(provider_discovery, "discover", fake_discover)

        async def failing_seed(session):
            raise RuntimeError("db hiccup")

        monkeypatch.setattr(model_catalog_service, "seed_from_registry", failing_seed)

        with patch.object(settings, "deployment_mode", "onprem"):
            summary = await model_catalog_service.run_discovery_sweep(db)

        assert summary["gemini"]["new_models"] == 1


class TestReadProjection:
    async def test_saas_withholds_approved_rows_without_multiplier(
        self, db: AsyncSession
    ) -> None:
        model_id = f"claude-unpriced-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Unpriced"}]
            )
        rows = await model_catalog_service.approved_models(db)

        # Community: unpriced models render at the cosmetic 1.0.
        with patch.object(settings, "deployment_mode", "onprem"):
            community = model_catalog_service.to_read_dicts(rows)
        assert model_id in {m["model"] for m in community}

        # SaaS: an approved model that somehow has no multiplier anywhere
        # is withheld instead of billed at a silent default.
        with patch.object(settings, "deployment_mode", "saas"):
            saas = model_catalog_service.to_read_dicts(rows)
        assert model_id not in {m["model"] for m in saas}

    async def test_registry_multiplier_wins_over_row(self, db: AsyncSession) -> None:
        await model_catalog_service.seed_from_registry(db)
        rows = await model_catalog_service.approved_models(db)
        balanced = next(
            m
            for m in model_catalog_service.to_read_dicts(rows)
            if m["model"] == model_registry.ANTHROPIC_BALANCED
        )
        registry_entry = ai_settings_service._model_lookup(
            model_registry.ANTHROPIC_BALANCED
        )
        assert registry_entry is not None
        assert balanced["credit_multiplier"] == pytest.approx(
            float(registry_entry["credit_multiplier"])
        )

    async def test_snapshots_collapse_to_one_picker_entry(
        self, db: AsyncSession
    ) -> None:
        # A year of re-dated snapshots must not fill the picker with
        # duplicates — one entry per family, anchored on the canonical row.
        base = f"claude-dedup-{uuid.uuid4().hex[:6]}"
        for model_id, multiplier in [
            (base, 1.5),
            (f"{base}-20250101", 1.5),
            (f"{base}-20260101", 1.5),
        ]:
            db.add(
                ModelCatalogEntry(
                    provider="anthropic",
                    model_id=model_id,
                    label=model_id,
                    tier=None,
                    status="approved",
                    enabled=True,
                    credit_multiplier=multiplier,
                    source="discovered",
                )
            )
        await db.commit()

        rows = await model_catalog_service.approved_models(db)
        with patch.object(settings, "deployment_mode", "saas"):
            dicts = model_catalog_service.to_read_dicts(rows)
        mine = [m for m in dicts if m["model"].startswith(base)]
        assert len(mine) == 1
        assert mine[0]["model"] == base
        assert mine[0]["credit_multiplier"] == pytest.approx(1.5)


class TestUpdateValidationUnion:
    async def test_catalog_approved_model_is_pickable(
        self, db: AsyncSession, tenant
    ) -> None:
        from app.modules.ai_settings.schemas import AISettingsUpdate

        model_id = f"claude-picked-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Picked"}]
            )
        row = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(llm_model=model_id)
        )
        assert row.llm_model == model_id

    async def test_pending_model_is_rejected(self, db: AsyncSession, tenant) -> None:
        from app.modules.ai_settings.schemas import AISettingsUpdate
        from fastapi import HTTPException

        model_id = f"claude-pending-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "saas"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Pending"}]
            )
        with pytest.raises(HTTPException) as exc:
            await ai_settings_service.update(
                db, tenant.id, AISettingsUpdate(llm_model=model_id)
            )
        assert exc.value.status_code == 422

    async def test_disabled_catalog_row_beats_whitelist(
        self, db: AsyncSession, tenant, _registry_guard
    ) -> None:
        # Kill-switch: the catalog is authoritative when a row exists —
        # a disabled row blocks the model even while the in-memory
        # whitelist (rebuilt from YAML on every boot) still carries it.
        from app.modules.ai_settings.schemas import AISettingsUpdate
        from fastapi import HTTPException

        model_id = f"claude-killswitch-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Curated"}]
            )
        ai_settings_service.upsert_allowed_model(
            {
                "provider": "anthropic",
                "model": model_id,
                "label": "Curated",
                "credit_multiplier": 1.0,
            }
        )
        entry = await model_catalog_service.get_entry(db, model_id)
        assert entry is not None
        entry.enabled = False
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await ai_settings_service.update(
                db, tenant.id, AISettingsUpdate(llm_model=model_id)
            )
        assert exc.value.status_code == 422

    async def test_whitelist_fallback_when_catalog_has_no_row(
        self, db: AsyncSession, tenant, _registry_guard
    ) -> None:
        # Models the catalog has never seen (local/BYOK names published via
        # register_models) still validate against the in-memory whitelist.
        from app.modules.ai_settings.schemas import AISettingsUpdate

        model_id = f"custom-local-{uuid.uuid4().hex[:6]}"
        ai_settings_service.upsert_allowed_model(
            {
                "provider": "openai_compatible",
                "model": model_id,
                "label": "Local",
                "credit_multiplier": 1.0,
            }
        )
        assert await model_catalog_service.get_entry(db, model_id) is None
        row = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(llm_model=model_id)
        )
        assert row.llm_model == model_id


class TestEffectiveMultiplierAsync:
    async def test_catalog_row_fallback_when_registry_misses(
        self, db: AsyncSession, tenant, _registry_guard
    ) -> None:
        # Multi-worker scenario: the approval upserted the registry only in
        # a sibling worker — this worker must still bill the moderated
        # value from the catalog row, not 1.0.
        model_id = f"claude-billing-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Moderated"}]
            )
        entry = await model_catalog_service.get_entry(db, model_id)
        assert entry is not None
        entry.credit_multiplier = 2.5
        await db.commit()

        row = await ai_settings_service.get_or_default(db, tenant.id)
        row.llm_model = model_id
        assert ai_settings_service._model_lookup(model_id) is None
        value = await ai_settings_service.get_effective_credit_multiplier_async(
            db, row
        )
        assert value == pytest.approx(2.5)

    async def test_registry_wins_over_catalog_row(
        self, db: AsyncSession, tenant, _registry_guard
    ) -> None:
        model_id = f"claude-billing-{uuid.uuid4().hex[:6]}"
        await model_catalog_service.seed_from_registry(db)
        with patch.object(settings, "deployment_mode", "onprem"):
            await model_catalog_service.upsert_discovered(
                db, "anthropic", [{"model_id": model_id, "label": "Moderated"}]
            )
        entry = await model_catalog_service.get_entry(db, model_id)
        assert entry is not None
        entry.credit_multiplier = 2.5
        await db.commit()
        ai_settings_service.upsert_allowed_model(
            {
                "provider": "anthropic",
                "model": model_id,
                "label": "Moderated",
                "credit_multiplier": 3.0,
            }
        )

        row = await ai_settings_service.get_or_default(db, tenant.id)
        row.llm_model = model_id
        value = await ai_settings_service.get_effective_credit_multiplier_async(
            db, row
        )
        assert value == pytest.approx(3.0)

    async def test_defaults_to_one_when_unknown_everywhere(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await ai_settings_service.get_or_default(db, tenant.id)
        row.llm_model = f"ghost-model-{uuid.uuid4().hex[:6]}"
        value = await ai_settings_service.get_effective_credit_multiplier_async(
            db, row
        )
        assert value == pytest.approx(1.0)
