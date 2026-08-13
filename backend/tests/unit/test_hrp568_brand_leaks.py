"""HRP-568 — brand leakage outside notification templates.

Three seams kept the stock brand on branded installs even after HRP-515
parameterised the template layer: the SMTP Message-ID domain was a
hardcoded stock domain, DB-template emails went out as bare fragments
(no branded layout — covered in test_notification_service.py), and a
custom BRAND_NAME next to a default EMAIL_FROM / empty FRONTEND_URL
kept the stock sender identity silently. The startup warnings and the
Message-ID derivation are pinned here.
"""

from __future__ import annotations

import logging

from app.config import Settings, settings
from app.core.email import _message_id_domain

STOCK_EMAIL_FROM = Settings.model_fields["email_from"].default


def _settings(**overrides):
    base = {
        # Hermetic against the ambient dev .env (same rationale as
        # test_config_s3_validator._settings).
        "s3_endpoint": "",
        "s3_public_endpoint": "",
        "frontend_url": "",
        "sentry_environment": "",
        "brand_name": "HRPulsar",
        "email_from": STOCK_EMAIL_FROM,
    }
    base.update(overrides)
    return Settings(**base)


class TestMessageIdDomain:
    def test_derives_from_email_from(self, monkeypatch):
        monkeypatch.setattr(
            settings, "email_from", "Acme Talent <notifications@acme.example>"
        )
        assert _message_id_domain() == "acme.example"

    def test_stock_default_keeps_stock_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "email_from", STOCK_EMAIL_FROM)
        assert _message_id_domain() == "hrpulsar.com"

    def test_bare_address_without_display_name(self, monkeypatch):
        monkeypatch.setattr(settings, "email_from", "hr@acme.example")
        assert _message_id_domain() == "acme.example"

    def test_unquoted_comma_in_display_name(self, monkeypatch):
        """parseaddr alone returns an empty address here — the regex
        fallback must still find the real sender domain."""
        monkeypatch.setattr(settings, "email_from", "Acme, Inc <hr@acme.example>")
        assert _message_id_domain() == "acme.example"

    def test_idn_domain_is_punycoded(self, monkeypatch):
        """A non-ASCII sender domain must not produce a Message-ID that
        Python RFC2047-encodes into an invalid header."""
        monkeypatch.setattr(settings, "email_from", "HR <hr@bücher.example>")
        assert _message_id_domain() == "xn--bcher-kva.example"

    def test_falls_back_to_frontend_host(self, monkeypatch):
        monkeypatch.setattr(settings, "email_from", "not-an-address")
        monkeypatch.setattr(settings, "frontend_url", "https://hr.acme.example")
        assert _message_id_domain() == "hr.acme.example"

    def test_schemeless_frontend_url_still_yields_host(self, monkeypatch):
        monkeypatch.setattr(settings, "email_from", "not-an-address")
        monkeypatch.setattr(settings, "frontend_url", "hr.acme.example")
        assert _message_id_domain() == "hr.acme.example"


class TestBrandDefaultWarnings:
    def test_stock_brand_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings()
        assert "BRAND_NAME" not in caplog.text

    def test_custom_brand_with_defaults_warns_on_all_three(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(brand_name="Acme Talent")
        assert "FRONTEND_URL is empty" in caplog.text
        assert "branded sender address" in caplog.text
        assert "BRAND_LOGO_URL is empty" in caplog.text

    def test_configured_branded_install_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(
                brand_name="Acme Talent",
                frontend_url="https://hr.acme.example",
                email_from="Acme Talent <notifications@acme.example>",
                brand_logo_url="https://cdn.acme.example/logo.png",
            )
        assert "BRAND_NAME" not in caplog.text

    def test_partial_config_warns_only_for_the_gap(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(
                brand_name="Acme Talent",
                frontend_url="https://hr.acme.example",
                brand_logo_url="https://cdn.acme.example/logo.png",
            )
        assert "FRONTEND_URL is empty" not in caplog.text
        assert "branded sender address" in caplog.text

    def test_stock_address_behind_custom_display_name_still_warns(self, caplog):
        """The most likely half-rebrand: a new display name in front of
        the stock address. The check is domain-based, not string-based."""
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(
                brand_name="Acme Talent",
                frontend_url="https://hr.acme.example",
                email_from="Acme Talent <notifications@hrpulsar.com>",
                brand_logo_url="https://cdn.acme.example/logo.png",
            )
        assert "branded sender address" in caplog.text

    def test_onprem_cors_fallback_is_a_valid_link_base(self, caplog):
        """SELF_HOSTED.md documents FRONTEND_URL as optional with the
        first CORS origin as fallback — an operator-owned CORS_ORIGINS
        must not warn on every boot."""
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(
                brand_name="Acme Talent",
                cors_origins="https://hr.acme.example",
                email_from="Acme Talent <notifications@acme.example>",
                brand_logo_url="https://cdn.acme.example/logo.png",
            )
        assert "FRONTEND_URL is empty" not in caplog.text

    def test_saas_mode_warns_without_frontend_url(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            _settings(
                brand_name="Acme Talent",
                deployment_mode="saas",
                cors_origins="https://hr.acme.example",
                email_from="Acme Talent <notifications@acme.example>",
                brand_logo_url="https://cdn.acme.example/logo.png",
            )
        assert "FRONTEND_URL is empty" in caplog.text
