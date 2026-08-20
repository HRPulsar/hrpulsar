"""Unit tests for R4b recruitment settings hub (scales / providers /
branding / retention)."""

from __future__ import annotations

import uuid

import pytest
from app.core import crypto
from app.core.crypto import decrypt_secret
from app.modules.recruitment import settings_service
from app.modules.recruitment.settings_schemas import (
    BrandingUpdate,
    LLMProviderCreate,
    LLMProviderUpdate,
    RetentionUpdate,
    ScaleConfigCreate,
    ScaleConfigUpdate,
    TranscriptionProviderCreate,
    TranscriptionProviderUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ─── Scales ─────────────────────────────────────────────────────────


class TestScaleConfigs:
    async def test_create_lists_and_active_picker(
        self, db: AsyncSession, tenant
    ) -> None:
        first = await settings_service.create_scale(
            db,
            tenant.id,
            ScaleConfigCreate(name="5-pt", min_value=0, max_value=5),
        )
        second = await settings_service.create_scale(
            db,
            tenant.id,
            ScaleConfigCreate(name="10-pt", min_value=0, max_value=10),
        )

        scales = await settings_service.list_scales(db, tenant.id)
        ids = {s.id for s in scales}
        assert first.id in ids and second.id in ids

        active = await settings_service.get_active_scale(db, tenant.id)
        assert active is not None and active.id == second.id
        # Latest active flipped predecessors off
        await db.refresh(first)
        assert first.is_active is False

    async def test_invalid_range_rejected(self, db: AsyncSession, tenant) -> None:
        with pytest.raises(HTTPException) as exc:
            await settings_service.create_scale(
                db,
                tenant.id,
                ScaleConfigCreate(name="bad", min_value=5, max_value=5),
            )
        assert exc.value.status_code == 422

    async def test_one_active_per_tenant_invariant(
        self, db: AsyncSession, tenant
    ) -> None:
        """The partial unique index (migration r4b2c3d4e5f6) refuses a
        second active scale for the same tenant if the service layer's
        deactivate-others step is bypassed."""
        from app.modules.recruitment.models import ScaleConfig
        from sqlalchemy.exc import IntegrityError

        await settings_service.create_scale(
            db,
            tenant.id,
            ScaleConfigCreate(name="primary", min_value=0, max_value=5),
        )

        # Bypass the service helper and insert a second active row directly.
        db.add(
            ScaleConfig(
                tenant_id=tenant.id,
                name="rogue",
                min_value=0,
                max_value=10,
                step=0.5,
                is_active=True,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_update_and_delete(self, db: AsyncSession, tenant) -> None:
        scale = await settings_service.create_scale(
            db,
            tenant.id,
            ScaleConfigCreate(name="5-pt", min_value=0, max_value=5),
        )
        updated = await settings_service.update_scale(
            db,
            tenant.id,
            scale.id,
            ScaleConfigUpdate(name="renamed"),
        )
        assert updated.name == "renamed"

        await settings_service.delete_scale(db, tenant.id, scale.id)
        scales = await settings_service.list_scales(db, tenant.id)
        assert all(s.id != scale.id for s in scales)


# ─── LLM providers ──────────────────────────────────────────────────


class TestLLMProviders:
    async def test_create_encrypts_and_masks(self, db: AsyncSession, tenant) -> None:
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                api_key="sk-ant-test-supersecret-1234",
            ),
        )

        # Stored value is *not* the plaintext.
        assert cfg.api_key_encrypted != "sk-ant-test-supersecret-1234"
        plain = decrypt_secret(cfg.api_key_encrypted)
        assert plain == "sk-ant-test-supersecret-1234"

        view = settings_service.llm_provider_to_read(cfg)
        assert view["api_key_masked"].endswith("1234")
        assert "supersecret" not in (view["api_key_masked"] or "")

    async def test_update_replaces_or_clears_key(
        self, db: AsyncSession, tenant
    ) -> None:
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="openai",
                model="gpt-4o-mini",
                api_key="initial-key-xyz",
            ),
        )

        # Update without api_key field → key untouched.
        await settings_service.update_llm_provider(
            db,
            tenant.id,
            cfg.id,
            LLMProviderUpdate(model="gpt-4o"),
        )
        await db.refresh(cfg)
        assert decrypt_secret(cfg.api_key_encrypted) == "initial-key-xyz"

        # Replace key.
        await settings_service.update_llm_provider(
            db,
            tenant.id,
            cfg.id,
            LLMProviderUpdate(api_key="new-key-abc"),
        )
        await db.refresh(cfg)
        assert decrypt_secret(cfg.api_key_encrypted) == "new-key-abc"

        # Clear key (empty string sentinel).
        await settings_service.update_llm_provider(
            db,
            tenant.id,
            cfg.id,
            LLMProviderUpdate(api_key=""),
        )
        await db.refresh(cfg)
        assert cfg.api_key_encrypted is None

    async def test_create_rejects_model_from_another_provider(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-498: an {openai, claude-…} pair used to be storable and sat
        inert until the pipeline started dispatching on it."""
        import pydantic

        with pytest.raises(pydantic.ValidationError, match="does not belong"):
            LLMProviderCreate(
                provider="openai",
                model="claude-sonnet-5",
                api_key="sk-test",
            )

    async def test_create_allows_local_model_names(
        self, db: AsyncSession, tenant
    ) -> None:
        # A local server serves arbitrary model names — no provider claims
        # them by prefix, so the pair stays free-form.
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="gigachat",
                model="GigaChat-Pro",
                settings={"base_url": "https://gigachat.example.com/v1"},
            ),
        )
        assert cfg.model == "GigaChat-Pro"

    async def test_create_allows_azure_serving_an_openai_model(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-498 review: azure/yandex/gigachat canonicalize onto
        ``openai_compatible``, which owns no model prefix — so the pair
        {azure, gpt-4o} (the *normal* Azure configuration) was read as a
        mismatch and rejected with 422."""
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="azure",
                model="gpt-4o",
                api_key="sk-azure",
                settings={"base_url": "https://acme.openai.azure.example/v1"},
            ),
        )
        assert cfg.model == "gpt-4o"

    async def test_create_allows_openai_compatible_with_any_model(
        self, db: AsyncSession, tenant
    ) -> None:
        # A LiteLLM/vLLM proxy serves upstream ids verbatim — including
        # Claude ones — so openai_compatible never mismatches.
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="gigachat",
                model="claude-sonnet-5",
                settings={"base_url": "https://proxy.example.com/v1"},
            ),
        )
        assert cfg.model == "claude-sonnet-5"

    async def test_base_url_row_escapes_prefix_ownership(
        self, db: AsyncSession, tenant
    ) -> None:
        # With a base_url the endpoint, not the model name, decides what is
        # served — the same pair without one stays a mismatch.
        import pydantic

        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="openai",
                model="claude-sonnet-5",
                api_key="sk-proxy",
                settings={"base_url": "https://litellm.example.com/v1"},
            ),
        )
        assert cfg.model == "claude-sonnet-5"

        with pytest.raises(pydantic.ValidationError, match="does not belong"):
            LLMProviderCreate(
                provider="openai",
                model="claude-sonnet-5",
                api_key="sk-proxy",
            )

    async def test_create_rejects_undispatchable_yandex_short_name(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-599 review: a keyed short-name Yandex row is silently
        skipped by the dispatcher — refuse it at save time instead of
        letting the tenant's key sit inert on the platform's dime."""
        import pydantic

        with pytest.raises(pydantic.ValidationError, match="gpt://"):
            LLMProviderCreate(
                provider="yandex",
                model="yandexgpt",
                api_key="ya-tenant",
            )

    async def test_create_allows_self_contained_yandex_uri(
        self, db: AsyncSession, tenant
    ) -> None:
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="yandex",
                model="gpt://b1gtenant/yandexgpt/latest",
                api_key="ya-tenant",
            ),
        )
        assert cfg.model == "gpt://b1gtenant/yandexgpt/latest"

    async def test_create_allows_yandex_short_name_behind_gateway(
        self, db: AsyncSession, tenant
    ) -> None:
        # With a base_url the endpoint owns the model namespace.
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="yandex",
                model="yandexgpt",
                settings={"base_url": "https://gateway.example.com/v1"},
            ),
        )
        assert cfg.model == "yandexgpt"

    async def test_update_cannot_strand_a_yandex_row(
        self, db: AsyncSession, tenant
    ) -> None:
        # Dropping the base_url (or shortening the model) via PATCH must
        # hit the same guard as create.
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="yandex",
                model="yandexgpt",
                settings={"base_url": "https://gateway.example.com/v1"},
            ),
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await settings_service.update_llm_provider(
                db,
                tenant.id,
                cfg.id,
                LLMProviderUpdate(settings={}),
            )
        assert exc.value.status_code == 422

    async def test_update_allows_proxy_model_on_a_base_url_row(
        self, db: AsyncSession, tenant
    ) -> None:
        # The PATCH guard reads the row's stored settings, so a proxy row
        # can be repointed at another upstream model.
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="openai",
                model="gpt-4o",
                api_key="sk-proxy",
                settings={"base_url": "https://litellm.example.com/v1"},
            ),
        )
        await settings_service.update_llm_provider(
            db,
            tenant.id,
            cfg.id,
            LLMProviderUpdate(model="claude-sonnet-5"),
        )
        await db.refresh(cfg)
        assert cfg.model == "claude-sonnet-5"

    async def test_update_rejects_model_from_another_provider(
        self, db: AsyncSession, tenant
    ) -> None:
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="openai", model="gpt-4o", api_key="sk-test"
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await settings_service.update_llm_provider(
                db,
                tenant.id,
                cfg.id,
                LLMProviderUpdate(model="claude-sonnet-5"),
            )
        assert exc.value.status_code == 422
        await db.refresh(cfg)
        assert cfg.model == "gpt-4o"

    async def test_graceful_decrypt_failure_marks_key_status(
        self, db: AsyncSession, tenant, monkeypatch
    ) -> None:
        """If the encryption key changes between write and read, the
        settings page must surface ``key_status='decrypt_failed'`` rather
        than 500-ing the whole hub. Regression for R4b.1 review H-3.
        """
        cfg = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                api_key="rotation-target-key",
            ),
        )

        def _broken(_token):
            raise ValueError("InvalidTag")

        monkeypatch.setattr(settings_service, "decrypt_secret", _broken)
        view = settings_service.llm_provider_to_read(cfg)
        assert view["key_status"] == "decrypt_failed"
        assert view["api_key_masked"] == "•••• (decrypt failed)"

        # Sanity: with the real key restored, status is ok.
        monkeypatch.setattr(settings_service, "decrypt_secret", crypto.decrypt_secret)
        view_ok = settings_service.llm_provider_to_read(cfg)
        assert view_ok["key_status"] == "ok"

    async def test_cross_tenant_isolation(self, db: AsyncSession, tenant) -> None:
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        ours = await settings_service.create_llm_provider(
            db,
            tenant.id,
            LLMProviderCreate(
                provider="gemini",
                model="gemini-2.5-flash",
                api_key="ours",
            ),
        )

        rows_other = await settings_service.list_llm_providers(db, other.id)
        assert all(r.id != ours.id for r in rows_other)

        with pytest.raises(HTTPException) as exc:
            await settings_service.update_llm_provider(
                db,
                other.id,
                ours.id,
                LLMProviderUpdate(model="gpt-4o"),
            )
        assert exc.value.status_code == 404


# ─── Transcription providers ────────────────────────────────────────


class TestTranscriptionProviders:
    async def test_crud(self, db: AsyncSession, tenant) -> None:
        cfg = await settings_service.create_transcription_provider(
            db,
            tenant.id,
            TranscriptionProviderCreate(
                provider="deepgram",
                api_key="dg-key-abcdefghij",
            ),
        )
        assert cfg.api_key_encrypted is not None
        view = settings_service.transcription_provider_to_read(cfg)
        assert view["provider"] == "deepgram"
        assert view["api_key_masked"].endswith("ghij")

        rows = await settings_service.list_transcription_providers(db, tenant.id)
        assert any(r.id == cfg.id for r in rows)

        await settings_service.update_transcription_provider(
            db,
            tenant.id,
            cfg.id,
            TranscriptionProviderUpdate(is_active=False),
        )
        await db.refresh(cfg)
        assert cfg.is_active is False

        await settings_service.delete_transcription_provider(db, tenant.id, cfg.id)
        remaining = await settings_service.list_transcription_providers(db, tenant.id)
        assert all(r.id != cfg.id for r in remaining)


# ─── Branding ───────────────────────────────────────────────────────


class TestBranding:
    async def test_round_trip_and_clear(self, db: AsyncSession, tenant) -> None:
        baseline = await settings_service.get_branding(db, tenant.id)
        assert baseline["accent_color"] is None

        await settings_service.update_branding(
            db,
            tenant.id,
            BrandingUpdate(accent_color="#0066ff", watermark_text="HRPulsar"),
        )
        result = await settings_service.get_branding(db, tenant.id)
        assert result["accent_color"] == "#0066ff"
        assert result["watermark_text"] == "HRPulsar"

        # Setting accent_color to null clears just that key.
        await settings_service.update_branding(
            db, tenant.id, BrandingUpdate(accent_color=None)
        )
        result = await settings_service.get_branding(db, tenant.id)
        assert result["accent_color"] is None
        assert result["watermark_text"] == "HRPulsar"


class TestUISettings:
    """HRP-205 REDO: read-only UI flags slice for non-admin roles."""

    async def test_defaults_false(self, db: AsyncSession, tenant) -> None:
        result = await settings_service.get_ui_settings(db, tenant.id)
        assert result == {
            "hm_questions_above_resume": False,
            "invited_evaluator_can_play_media": False,
        }

    async def test_reads_flags_from_branding_extra(
        self, db: AsyncSession, tenant
    ) -> None:
        await settings_service.update_branding(
            db,
            tenant.id,
            BrandingUpdate(extra={"hm_questions_above_resume": True}),
        )
        result = await settings_service.get_ui_settings(db, tenant.id)
        assert result["hm_questions_above_resume"] is True
        assert result["invited_evaluator_can_play_media"] is False


# ─── Retention ──────────────────────────────────────────────────────


class TestRetention:
    async def test_defaults_then_partial_update(self, db: AsyncSession, tenant) -> None:
        baseline = await settings_service.get_retention(db, tenant.id)
        assert baseline == {
            "interviews_days": 365,
            "resumes_days": 365,
            "consents_days": 365,
            "reports_days": 365,
        }

        await settings_service.update_retention(
            db, tenant.id, RetentionUpdate(interviews_days=90)
        )
        updated = await settings_service.get_retention(db, tenant.id)
        assert updated["interviews_days"] == 90
        assert updated["resumes_days"] == 365
