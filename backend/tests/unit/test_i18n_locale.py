"""i18n F0 (HRP-474): locale foundation.

Covers the four pieces of the interface-locale chain:
- Settings validator for AVAILABLE_LOCALES / DEFAULT_LOCALE;
- pure resolution helpers in app/core/i18n.py
  (user > tenant > Accept-Language > deployment default);
- per-user ``language`` via PUT /auth/me (+ /auth/me echo);
- tenant ``default_locale`` via PUT /settings/company-profile.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.config import Settings, settings
from app.core import i18n as i18n_module
from app.core.i18n import (
    format_date,
    normalize_locale,
    parse_accept_language,
    resolve_locale,
    translate,
)
from fastapi import Request
from httpx import AsyncClient


def _make_request(accept_language: str | None = None) -> Request:
    headers = []
    if accept_language is not None:
        headers.append((b"accept-language", accept_language.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture
def locales_de_en(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "en")


# --- Settings validator ---


class TestLocaleSettingsValidator:
    def _settings(self, **overrides):
        base = {
            "deployment_mode": "onprem",
            "demo_enabled": False,
            "sentry_environment": "development",
        }
        base.update(overrides)
        return Settings(**base)

    def test_default_must_be_listed_in_available(self):
        with pytest.raises(ValueError, match="DEFAULT_LOCALE"):
            self._settings(available_locales="en", default_locale="de")

    def test_rejects_non_iso_code(self):
        with pytest.raises(ValueError, match="ISO 639-1"):
            self._settings(available_locales="en,deu", default_locale="en")

    def test_rejects_empty_list(self):
        with pytest.raises(ValueError, match="at least one locale"):
            self._settings(available_locales=" , ", default_locale="en")

    def test_normalizes_case_and_whitespace(self):
        s = self._settings(available_locales=" De , EN ", default_locale="DE")
        assert s.available_locales_list == ["de", "en"]
        assert s.default_locale == "de"

    def test_blank_values_coalesce_to_defaults(self):
        # Compose passes locale envs as ${VAR:-} — blank means "unset",
        # not a boot failure.
        s = self._settings(available_locales="", default_locale="")
        assert s.available_locales_list == ["en"]
        assert s.default_locale == "en"

    def test_blank_default_falls_back_to_first_available(self):
        s = self._settings(available_locales="de,en", default_locale="")
        assert s.default_locale == "de"


# --- Pure helpers ---


class TestParseAcceptLanguage:
    def test_orders_by_quality(self):
        assert parse_accept_language("en;q=0.5, de, fr;q=0.8") == [
            "de",
            "fr",
            "en",
        ]

    def test_skips_wildcard_and_zero_quality(self):
        assert parse_accept_language("*, de;q=0, en;q=0.1") == ["en"]

    def test_malformed_quality_drops_tag(self):
        # A broken q-value reads as rejection, not top preference.
        assert parse_accept_language("de;q=broken, en;q=0.9") == ["en"]
        assert parse_accept_language("de;q=0.0000, en") == ["en"]

    def test_quality_param_case_insensitive(self):
        assert parse_accept_language("en;Q=0.1, de;q=0.9") == ["de", "en"]

    def test_empty_header(self):
        assert parse_accept_language(None) == []
        assert parse_accept_language("") == []


class TestNormalizeLocale:
    def test_matches_primary_subtag(self, locales_de_en):
        assert normalize_locale("de-DE") == "de"
        assert normalize_locale("de_AT") == "de"
        assert normalize_locale("EN") == "en"

    def test_unsupported_returns_none(self, locales_de_en):
        assert normalize_locale("fr") is None
        assert normalize_locale("") is None
        assert normalize_locale(None) is None


class TestResolveLocale:
    def test_user_language_wins(self, locales_de_en):
        assert (
            resolve_locale(
                user_language="de",
                tenant_default="en",
                accept_language="en",
            )
            == "de"
        )

    def test_tenant_default_over_header(self, locales_de_en):
        assert resolve_locale(tenant_default="de", accept_language="en") == "de"

    def test_accept_language_fallback(self, locales_de_en):
        assert resolve_locale(accept_language="fr, de;q=0.8") == "de"

    def test_deployment_default_last(self, locales_de_en):
        assert resolve_locale(accept_language="fr") == "en"
        assert resolve_locale() == "en"

    def test_stale_unsupported_values_fall_through(self, locales_de_en):
        # e.g. a locale later removed from the deployment
        assert resolve_locale(user_language="ru", tenant_default="fr") == "en"


# --- translate() catalog lookup (F3) ---


class TestTranslateCatalog:
    @pytest.fixture
    def catalogs(self, monkeypatch, tmp_path):
        (tmp_path / "en.json").write_text(
            '{"errors": {"greet": "Hello {name}", "plain": "Plain"}}',
            encoding="utf-8",
        )
        (tmp_path / "de.json").write_text(
            '{"errors": {"greet": "Hallo {name}"}}', encoding="utf-8"
        )
        monkeypatch.setattr(i18n_module, "_I18N_DIR", tmp_path)
        i18n_module._load_catalog.cache_clear()
        yield
        i18n_module._load_catalog.cache_clear()

    def test_locale_then_en_then_key(self, catalogs):
        assert translate("errors.greet", "de", name="Max") == "Hallo Max"
        # de lacks the key → falls back to en
        assert translate("errors.plain", "de") == "Plain"
        # nowhere → the key itself
        assert translate("errors.unknown", "de") == "errors.unknown"

    def test_missing_params_do_not_crash(self, catalogs):
        # No params supplied → raw template returned, not a KeyError
        assert translate("errors.greet", "en") == "Hello {name}"


class TestFormatDate:
    """i18n F7: catalog-driven long email date (real catalogs)."""

    def test_en_matches_legacy_strftime(self):
        # The en pattern must reproduce the historic strftime("%B %d, %Y")
        # byte-for-byte — the en email snapshots pin that shape.
        d = date(2026, 7, 5)
        assert format_date(d, "en") == d.strftime("%B %d, %Y") == "July 05, 2026"

    def test_de_long_form(self):
        assert format_date(date(2026, 7, 5), "de") == "05. Juli 2026"
        assert format_date(date(2026, 3, 31), "de") == "31. März 2026"

    def test_unknown_locale_falls_back_to_en(self):
        assert format_date(date(2026, 1, 1), "fr") == "January 01, 2026"


# --- PUT /auth/me language ---


class TestUserLanguageAPI:
    async def test_set_and_echo_language(self, auth_client: AsyncClient, locales_de_en):
        resp = await auth_client.put("/api/auth/me", json={"language": "de"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "de"

        me = await auth_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["language"] == "de"

    async def test_language_normalized_to_lowercase(
        self, auth_client: AsyncClient, locales_de_en
    ):
        resp = await auth_client.put("/api/auth/me", json={"language": "DE"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "de"

    async def test_unsupported_language_rejected(
        self, auth_client: AsyncClient, locales_de_en
    ):
        resp = await auth_client.put("/api/auth/me", json={"language": "fr"})
        assert resp.status_code == 400
        # F3 (AppError): detail stays a plain string for client/test
        # compatibility; the stable code is additive.
        body = resp.json()
        assert body["code"] == "unsupported_language"
        assert "available locales" in body["detail"]

    async def test_null_clears_language(self, auth_client: AsyncClient, locales_de_en):
        await auth_client.put("/api/auth/me", json={"language": "de"})
        resp = await auth_client.put("/api/auth/me", json={"language": None})
        assert resp.status_code == 200
        assert resp.json()["language"] is None

    async def test_me_echoes_tenant_default_locale(
        self, auth_client: AsyncClient, db, tenant, locales_de_en
    ):
        tenant.default_locale = "de"
        await db.commit()
        me = await auth_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["tenant_default_locale"] == "de"


# --- PUT /settings/company-profile default_locale ---


class TestTenantDefaultLocaleAPI:
    async def test_set_and_read_default_locale(
        self, auth_client: AsyncClient, locales_de_en
    ):
        resp = await auth_client.put(
            "/api/settings/company-profile", json={"default_locale": "de"}
        )
        assert resp.status_code == 200
        assert resp.json()["default_locale"] == "de"

        read = await auth_client.get("/api/settings/company-profile")
        assert read.status_code == 200
        assert read.json()["default_locale"] == "de"

    async def test_unsupported_default_locale_rejected(
        self, auth_client: AsyncClient, locales_de_en
    ):
        resp = await auth_client.put(
            "/api/settings/company-profile", json={"default_locale": "fr"}
        )
        assert resp.status_code == 400

    async def test_null_clears_default_locale(
        self, auth_client: AsyncClient, locales_de_en
    ):
        await auth_client.put(
            "/api/settings/company-profile", json={"default_locale": "de"}
        )
        resp = await auth_client.put(
            "/api/settings/company-profile", json={"default_locale": None}
        )
        assert resp.status_code == 200
        assert resp.json()["default_locale"] is None

    async def test_other_fields_unaffected(
        self, auth_client: AsyncClient, locales_de_en
    ):
        resp = await auth_client.put(
            "/api/settings/company-profile",
            json={"industry": "Software", "default_locale": "de"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["industry"] == "Software"
        assert body["default_locale"] == "de"


# --- AppError exception handler (F3) ---


class TestAppErrorHandler:
    """Direct handler tests: flat vs structured (legacy object) detail."""

    @pytest.fixture
    def catalogs(self, monkeypatch, tmp_path):
        (tmp_path / "en.json").write_text(
            '{"errors": {"candidate_archived": "Cannot link an archived candidate.",'
            ' "insufficient_data_no_grades": "No grades configured."}}',
            encoding="utf-8",
        )
        (tmp_path / "de.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(i18n_module, "_I18N_DIR", tmp_path)
        i18n_module._load_catalog.cache_clear()
        yield
        i18n_module._load_catalog.cache_clear()

    async def _invoke(self, exc):
        import json

        from app.main import _app_error_handler

        response = await _app_error_handler(_make_request(), exc)
        return json.loads(bytes(response.body)), response

    async def test_flat_detail_is_string(self, catalogs, locales_de_en):
        from app.core.errors import AppError

        body, response = await self._invoke(
            AppError("candidate_archived", status_code=409)
        )
        assert response.status_code == 409
        assert body == {
            "detail": "Cannot link an archived candidate.",
            "code": "candidate_archived",
        }

    async def test_structured_detail_preserves_legacy_shape(
        self, catalogs, locales_de_en
    ):
        from app.core.errors import AppError

        body, _ = await self._invoke(
            AppError(
                "candidate_archived",
                status_code=409,
                detail_extra={"existing_candidate_id": "abc"},
            )
        )
        assert body == {
            "detail": {
                "code": "candidate_archived",
                "message": "Cannot link an archived candidate.",
                "existing_candidate_id": "abc",
            },
            "code": "candidate_archived",
        }

    async def test_structured_detail_code_key_and_wire_code_override(
        self, catalogs, locales_de_en
    ):
        from app.core.errors import AppError

        body, _ = await self._invoke(
            AppError(
                "insufficient_data_no_grades",
                status_code=422,
                detail_extra={},
                detail_code_key="error_code",
                detail_code="insufficient_data",
            )
        )
        assert body["detail"] == {
            "error_code": "insufficient_data",
            "message": "No grades configured.",
        }
        # top-level code stays the specific catalog code
        assert body["code"] == "insufficient_data_no_grades"

    async def test_headers_pass_through(self, catalogs, locales_de_en):
        from app.core.errors import AppError

        _, response = await self._invoke(
            AppError(
                "candidate_archived",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        )
        assert response.headers["WWW-Authenticate"] == "Bearer"

    async def test_apperror_is_httpexception_with_english_fallback(
        self, catalogs, locales_de_en
    ):
        """~530 direct-call tests do pytest.raises(HTTPException) and read
        exc.value.detail; production code catches except HTTPException to
        aggregate per-row failures. AppError must satisfy both without the
        locale-aware handler in the loop."""
        from app.core.errors import AppError
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            raise AppError("candidate_archived", status_code=409)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Cannot link an archived candidate."

        structured = AppError(
            "candidate_archived",
            status_code=409,
            detail_extra={"existing_candidate_id": "abc"},
        )
        assert isinstance(structured, HTTPException)
        assert structured.detail == {
            "code": "candidate_archived",
            "message": "Cannot link an archived candidate.",
            "existing_candidate_id": "abc",
        }

    async def test_unknown_code_falls_back_to_key(self, catalogs, locales_de_en):
        from app.core.errors import AppError

        body, _ = await self._invoke(AppError("nonexistent_code"))
        assert body["detail"] == "errors.nonexistent_code"


# --- RequestValidationError handler (F3 tail) ---


class TestValidationErrorHandler:
    """Framework validation errors localize by pydantic error ``type``;
    custom validator ``ValueError`` messages reverse-map to their
    ``errors.validation.*`` key. The en path never rewrites anything."""

    @pytest.fixture
    def catalogs(self, monkeypatch, tmp_path):
        import json

        en = {
            "errors": {
                "validation": {
                    "string_too_short": (
                        "String should have at least {min_length} characters"
                    ),
                    "at_least_one_field_must_be_set": (
                        "At least one field must be set"
                    ),
                }
            }
        }
        de = {
            "errors": {
                "validation": {
                    "string_too_short": (
                        "Zeichenkette braucht mindestens {min_length} Zeichen"
                    ),
                    "at_least_one_field_must_be_set": (
                        "Mindestens ein Feld muss gesetzt sein"
                    ),
                }
            }
        }
        (tmp_path / "en.json").write_text(json.dumps(en), encoding="utf-8")
        (tmp_path / "de.json").write_text(json.dumps(de), encoding="utf-8")
        monkeypatch.setattr(i18n_module, "_I18N_DIR", tmp_path)
        i18n_module._load_catalog.cache_clear()
        i18n_module._validation_message_keys.cache_clear()
        yield
        i18n_module._load_catalog.cache_clear()
        i18n_module._validation_message_keys.cache_clear()

    async def _invoke(self, errors, accept_language=None):
        import json

        from app.main import _validation_error_handler
        from fastapi.exceptions import RequestValidationError

        exc = RequestValidationError(errors, body=None)
        response = await _validation_error_handler(_make_request(accept_language), exc)
        return json.loads(bytes(response.body)), response

    def _missing_err(self):
        return {
            "type": "missing",
            "loc": ("body", "name"),
            "msg": "Field required",
            "input": None,
        }

    async def test_stock_type_translates_with_ctx(self, catalogs, locales_de_en):
        body, response = await self._invoke(
            [
                {
                    "type": "string_too_short",
                    "loc": ("body", "title"),
                    "msg": "String should have at least 3 characters",
                    "input": "ab",
                    "ctx": {"min_length": 3},
                }
            ],
            accept_language="de",
        )
        assert response.status_code == 422
        assert body["detail"][0]["msg"] == "Zeichenkette braucht mindestens 3 Zeichen"

    async def test_custom_value_error_reverse_maps(self, catalogs, locales_de_en):
        body, _ = await self._invoke(
            [
                {
                    "type": "value_error",
                    "loc": ("body",),
                    "msg": "Value error, At least one field must be set",
                    "input": {},
                    "ctx": {"error": ValueError("At least one field must be set")},
                }
            ],
            accept_language="de",
        )
        assert body["detail"][0]["msg"] == "Mindestens ein Feld muss gesetzt sein"

    async def test_unmapped_value_error_kept_verbatim(self, catalogs, locales_de_en):
        body, _ = await self._invoke(
            [
                {
                    "type": "value_error",
                    "loc": ("body",),
                    "msg": "Value error, something with no catalog entry",
                    "input": {},
                }
            ],
            accept_language="de",
        )
        assert (
            body["detail"][0]["msg"] == "Value error, something with no catalog entry"
        )

    async def test_untranslated_type_keeps_stock_msg(self, catalogs, locales_de_en):
        body, _ = await self._invoke([self._missing_err()], accept_language="de")
        # `missing` is absent from the tmp catalogs → stock wording survives.
        assert body["detail"][0]["msg"] == "Field required"

    async def test_en_output_untouched(self, catalogs, locales_de_en):
        body, _ = await self._invoke(
            [
                self._missing_err(),
                {
                    "type": "value_error",
                    "loc": ("body",),
                    "msg": "Value error, At least one field must be set",
                    "input": {},
                },
            ],
            accept_language="en",
        )
        assert body["detail"][0]["msg"] == "Field required"
        assert body["detail"][1]["msg"] == "Value error, At least one field must be set"
