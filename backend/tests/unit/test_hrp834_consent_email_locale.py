"""HRP-834: the recording-consent letter is in the company's language.

The candidate has no account, so the recipient's locale is the tenant's
default (the rule every other candidate-facing letter of the recruitment
module applies). The wrapper used to follow ``ConsentTemplate.language``
instead — a body-language tag that defaults to "en" — so a Russian
company mailed the English letter on both the first send and Resend.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import settings
from app.core import email as email_mod
from app.core.i18n import translate
from app.modules.recruitment import consent_service, service
from app.modules.recruitment.models import ConsentTemplate
from app.modules.recruitment.schemas import CandidateCreate, ConsentSendRequest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sent_emails(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _capture(to, subject, body, **kwargs):
        calls.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(email_mod, "enqueue_email", _capture)
    return calls


async def _send_and_resend(db: AsyncSession, tenant, user) -> None:
    """An English-tagged template (the form's default) — both paths."""
    db.add(
        ConsentTemplate(
            tenant_id=tenant.id,
            name="Recording consent",
            body="<p>I agree.</p>",
            language="en",
            is_active=True,
            version=1,
        )
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Anna",
            last_name=f"K-{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
        ),
    )
    await db.commit()
    candidate_id = uuid.UUID(str(candidate["id"]))
    await consent_service.send_consent_request(
        db,
        tenant.id,
        user.id,
        candidate_id,
        ConsentSendRequest(email=candidate["email"]),
    )
    await consent_service.resend_consent_request(db, tenant.id, user.id, candidate_id)


async def test_letter_follows_the_company_locale_not_the_template_tag(
    db: AsyncSession, tenant, user, monkeypatch, sent_emails
):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "en")
    tenant.default_locale = "de"
    await db.commit()

    await _send_and_resend(db, tenant, user)

    assert len(sent_emails) == 2, "first send and Resend both go out"
    assert all('lang="de"' in m["body"] for m in sent_emails)


async def test_russian_company_gets_the_russian_letter_on_both_paths(
    db: AsyncSession, tenant, user, monkeypatch, sent_emails
):
    """The reporter's stand: the ``ru`` catalog is Enterprise-only."""
    pytest.importorskip("ee")
    monkeypatch.setattr(settings, "available_locales", "ru,en")
    monkeypatch.setattr(settings, "default_locale", "ru")
    tenant.default_locale = "ru"
    await db.commit()

    await _send_and_resend(db, tenant, user)

    expected = translate("email.recruitment_consent.subject", "ru")
    assert expected != translate("email.recruitment_consent.subject", "en")
    assert [m["subject"] for m in sent_emails] == [expected, expected]
