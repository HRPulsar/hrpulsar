"""HRP-393: white-label branding of outbound email via BRAND_* settings.

The stock build must stay byte-identical (defaults reproduce the old
hardcoded HRPulsar brand); a configured brand must replace the name,
logo and accent color everywhere in the rendered email.
"""

from app.config import settings
from app.core.email_templates import (
    render_deadline_reminder_email,
    render_invitation_email,
    render_magic_login_email,
    render_verification_email,
)

STOCK_LOGO_PATH = "/brand/logo-horizontal-color-light.png"


class TestDefaultBrand:
    def test_default_email_keeps_stock_brand(self):
        subject, html = render_verification_email("tok")
        assert "HRPulsar" in subject
        assert STOCK_LOGO_PATH in html
        assert 'alt="HRPulsar"' in html
        assert "#0066FF" in html  # button + footer link color

    def test_default_settings_values(self):
        assert settings.brand_name == "HRPulsar"
        assert settings.brand_logo_url == ""
        assert settings.brand_accent_color == "#0066FF"


class TestCustomBrand:
    def _apply(self, monkeypatch, **overrides):
        defaults = {
            "brand_name": "Acme Talent",
            "brand_logo_url": "https://cdn.acme.test/logo.png",
            "brand_accent_color": "#AA0044",
        }
        defaults.update(overrides)
        for key, value in defaults.items():
            monkeypatch.setattr(settings, key, value)

    def test_custom_brand_replaces_name_logo_and_color(self, monkeypatch):
        self._apply(monkeypatch)
        subject, html = render_verification_email("tok")
        assert "Acme Talent" in subject
        assert "HRPulsar" not in subject
        assert "HRPulsar" not in html
        assert "https://cdn.acme.test/logo.png" in html
        assert STOCK_LOGO_PATH not in html
        assert 'alt="Acme Talent"' in html
        assert "#AA0044" in html
        assert "#0066FF" not in html

    def test_custom_brand_in_all_literal_templates(self, monkeypatch):
        self._apply(monkeypatch)
        for subject, html in (
            render_invitation_email("Anna", "tok"),
            render_magic_login_email("tok", "Acme GmbH"),
            render_deadline_reminder_email("exam", "Final", "2026-08-01"),
        ):
            assert "HRPulsar" not in subject
            assert "HRPulsar" not in html
            assert "Acme Talent" in html

    def test_brand_name_is_html_escaped_in_body(self, monkeypatch):
        self._apply(monkeypatch, brand_name="Acme <&> Co")
        subject, html = render_verification_email("tok")
        assert "Acme <&> Co" in subject  # subjects are plain text
        assert "Acme &lt;&amp;&gt; Co" in html
        assert "<&>" not in html

    def test_brand_name_is_html_escaped_in_button_label(self, monkeypatch):
        self._apply(monkeypatch, brand_name="Acme <&> Co")
        _, html = render_deadline_reminder_email("exam", "Final", "2026-08-01")
        assert "Open Acme &lt;&amp;&gt; Co" in html
        assert "<&>" not in html

    def test_custom_logo_drops_fixed_width(self, monkeypatch):
        self._apply(monkeypatch)
        _, html = render_verification_email("tok")
        assert "width: auto" in html
        assert 'width="160"' not in html

    def test_stock_logo_keeps_fixed_width_markup(self):
        _, html = render_verification_email("tok")
        assert 'width="160" height="31"' in html
