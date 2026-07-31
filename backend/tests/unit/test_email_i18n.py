"""i18n F4 (HRP-478): recipient-locale emails, both template systems.

Path A — code templates (``app/core/email_templates.py``): every
``render_*`` accepts a keyword-only ``locale`` and pulls copy from the
``email.*`` catalog (de is an English copy until F7, so the mechanism is
asserted via the html ``lang`` attribute and a stubbed catalog).

Path B — DB templates (``NotificationTemplate``): one row per
``(code, locale)``; ``send_notification`` resolves the *recipient's*
locale (User.language > Tenant.default_locale > deployment default) and
falls back to the en row when the locale row is missing.
"""

import uuid

import pytest
from app.config import settings
from app.core import i18n as i18n_module
from app.modules.notification import service as notification_service
from app.modules.notification.models import NotificationTemplate
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def locales_de_en(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "en")


@pytest.fixture
def sent_emails(monkeypatch):
    calls: list[dict] = []

    def _capture(to, subject, body, **kwargs):
        calls.append({"to": to, "subject": subject, "body": body, **kwargs})

    monkeypatch.setattr(notification_service, "enqueue_email", _capture)
    return calls


def _template_pair(code: str) -> list[NotificationTemplate]:
    return [
        NotificationTemplate(
            code=code,
            locale="en",
            subject_template="Hello {{ name }}",
            body_template="Body for {{ name }}",
            notification_type="email",
        ),
        NotificationTemplate(
            code=code,
            locale="de",
            subject_template="Hallo {{ name }}",
            body_template="Text für {{ name }}",
            notification_type="email",
        ),
    ]


class TestResolveRecipientLocale:
    async def test_user_language_wins(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        user.language = "de"
        tenant.default_locale = None
        await db.commit()
        assert await notification_service.resolve_recipient_locale(db, user.id) == "de"

    async def test_tenant_default_fills_null_user_language(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        user.language = None
        tenant.default_locale = "de"
        await db.commit()
        assert await notification_service.resolve_recipient_locale(db, user.id) == "de"

    async def test_unsupported_user_language_falls_through(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        user.language = "fr"
        tenant.default_locale = "de"
        await db.commit()
        assert await notification_service.resolve_recipient_locale(db, user.id) == "de"

    async def test_deployment_default_when_nothing_set(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        user.language = None
        tenant.default_locale = None
        await db.commit()
        assert await notification_service.resolve_recipient_locale(db, user.id) == "en"

    async def test_unknown_user_defaults(self, db: AsyncSession, locales_de_en):
        assert (
            await notification_service.resolve_recipient_locale(db, uuid.uuid4())
            == "en"
        )


class TestGetTemplateForLocale:
    async def test_exact_locale_row(self, db: AsyncSession, locales_de_en):
        code = f"t.{uuid.uuid4().hex[:8]}"
        db.add_all(_template_pair(code))
        await db.commit()
        tpl = await notification_service.get_template_for_locale(db, code, "de")
        assert tpl is not None and tpl.locale == "de"

    async def test_falls_back_to_en_row(self, db: AsyncSession, locales_de_en):
        code = f"t.{uuid.uuid4().hex[:8]}"
        db.add_all(_template_pair(code)[:1])  # en only
        await db.commit()
        tpl = await notification_service.get_template_for_locale(db, code, "de")
        assert tpl is not None and tpl.locale == "en"

    async def test_unknown_code_is_none(self, db: AsyncSession, locales_de_en):
        assert (
            await notification_service.get_template_for_locale(
                db, f"missing.{uuid.uuid4().hex[:8]}", "de"
            )
            is None
        )


class TestSendNotificationLocale:
    async def test_de_recipient_gets_de_template(
        self, db: AsyncSession, tenant, user, sent_emails, locales_de_en
    ):
        code = f"t.{uuid.uuid4().hex[:8]}"
        db.add_all(_template_pair(code))
        user.language = "de"
        await db.commit()

        await notification_service.send_notification(
            db, tenant.id, code, user.id, user.email, {"name": "Max"}
        )

        assert len(sent_emails) == 1
        assert sent_emails[0]["subject"] == "Hallo Max"
        assert sent_emails[0]["body"] == "Text für Max"

    async def test_missing_de_row_falls_back_to_en(
        self, db: AsyncSession, tenant, user, sent_emails, locales_de_en
    ):
        code = f"t.{uuid.uuid4().hex[:8]}"
        db.add_all(_template_pair(code)[:1])  # en only
        user.language = "de"
        await db.commit()

        await notification_service.send_notification(
            db, tenant.id, code, user.id, user.email, {"name": "Max"}
        )

        assert len(sent_emails) == 1
        assert sent_emails[0]["subject"] == "Hello Max"

    async def test_explicit_locale_overrides_recipient(
        self, db: AsyncSession, tenant, user, sent_emails, locales_de_en
    ):
        code = f"t.{uuid.uuid4().hex[:8]}"
        db.add_all(_template_pair(code))
        user.language = "de"
        await db.commit()

        await notification_service.send_notification(
            db, tenant.id, code, user.id, user.email, {"name": "Max"}, locale="en"
        )

        assert len(sent_emails) == 1
        assert sent_emails[0]["subject"] == "Hello Max"


class TestRenderLocaleMechanism:
    """Path A: catalog-driven rendering (de values are en copies until F7,
    so a stubbed catalog proves locale selection end-to-end)."""

    @pytest.fixture
    def stub_catalogs(self, monkeypatch, tmp_path, locales_de_en):
        import json

        real = i18n_module._I18N_DIR
        en = json.loads((real / "en.json").read_text(encoding="utf-8"))
        de = json.loads((real / "de.json").read_text(encoding="utf-8"))
        de["email"]["verification"]["heading"] = "E-Mail bestätigen"
        (tmp_path / "en.json").write_text(json.dumps(en), encoding="utf-8")
        (tmp_path / "de.json").write_text(json.dumps(de), encoding="utf-8")
        monkeypatch.setattr(i18n_module, "_I18N_DIR", tmp_path)
        i18n_module._load_catalog.cache_clear()
        yield
        i18n_module._load_catalog.cache_clear()

    def test_html_lang_follows_locale(self, locales_de_en):
        from app.core.email_templates import render_verification_email

        _, html_en = render_verification_email("tok")
        _, html_de = render_verification_email("tok", locale="de")
        assert '<html lang="en">' in html_en
        assert '<html lang="de">' in html_de

    def test_de_catalog_string_is_used(self, stub_catalogs):
        from app.core.email_templates import render_verification_email

        _, html_de = render_verification_email("tok", locale="de")
        _, html_en = render_verification_email("tok")
        assert "E-Mail bestätigen" in html_de
        assert "E-Mail bestätigen" not in html_en
