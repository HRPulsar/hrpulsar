"""HRP-684: resending the recording-consent link.

Resend re-mails the *pending* request instead of issuing a new one — a
candidate who still has the first email must not find a dead link because
someone in the office pressed Resend. What is asserted here: the token
survives, ``last_sent_at`` moves, an absent request refuses, and the URL
the banner calls is a URL the app serves.

REDO (QA 14.09): the letter goes to the candidate's *current* email, not
the one the first letter went to; and an expired link is replaced by a
fresh token instead of answering "Consent link has expired".
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core import email as email_mod
from app.main import app
from app.modules.recruitment import consent_service, service
from app.modules.recruitment.models import Candidate, ConsentRequest, ConsentTemplate
from app.modules.recruitment.schemas import CandidateCreate, ConsentSendRequest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession, tenant, user) -> dict:
    template = ConsentTemplate(
        tenant_id=tenant.id,
        name="Recording consent",
        body="<p>I agree.</p>",
        language="en",
        is_active=True,
        version=1,
    )
    db.add(template)
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"Ada-{uuid.uuid4().hex[:4]}",
            last_name=f"Lovelace-{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
        ),
    )
    await db.commit()
    sent = await consent_service.send_consent_request(
        db,
        tenant.id,
        user.id,
        uuid.UUID(str(candidate["id"])),
        ConsentSendRequest(email=candidate["email"]),
    )
    return {"candidate_id": uuid.UUID(str(candidate["id"])), "sent": sent}


@pytest.fixture
def sent_to(monkeypatch) -> list[str]:
    """Recipients of every consent letter enqueued during the test."""
    recipients: list[str] = []
    monkeypatch.setattr(
        email_mod,
        "enqueue_email",
        lambda to, subject, body, **kwargs: recipients.append(to),
    )
    return recipients


async def _correct_email(db: AsyncSession, candidate_id) -> str:
    """The recruiter fixes the address on the candidate card."""
    candidate = await db.get(Candidate, candidate_id)
    candidate.email = f"corrected-{uuid.uuid4().hex[:6]}@example.com"
    await db.commit()
    return candidate.email


async def _row(db: AsyncSession, request_id) -> ConsentRequest:
    return (
        await db.execute(
            select(ConsentRequest).where(ConsentRequest.id == request_id)
        )
    ).scalar_one()


class TestConsentResend:
    @pytest.mark.asyncio
    async def test_first_send_stamps_last_sent_at(self, db, tenant, user):
        setup = await _setup(db, tenant, user)
        assert setup["sent"]["last_sent_at"] is not None

    @pytest.mark.asyncio
    async def test_resend_keeps_the_token_and_moves_the_stamp(
        self, db, tenant, user
    ):
        setup = await _setup(db, tenant, user)
        before = await _row(db, setup["sent"]["id"])
        token_before, stamp_before = before.token, before.last_sent_at

        # Backdate so the comparison cannot pass on clock resolution alone.
        before.last_sent_at = stamp_before - timedelta(hours=3)
        await db.commit()

        resent = await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )

        after = await _row(db, setup["sent"]["id"])
        assert resent["id"] == setup["sent"]["id"], "a new request was issued"
        assert after.token == token_before, "the delivered link stopped working"
        assert after.status == "pending"
        assert after.last_sent_at > stamp_before - timedelta(hours=3)

    @pytest.mark.asyncio
    async def test_resend_without_a_pending_request_is_404(
        self, db, tenant, user
    ):
        setup = await _setup(db, tenant, user)
        row = await _row(db, setup["sent"]["id"])
        row.status = "signed"
        row.signed_at = datetime.now(UTC)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await consent_service.resend_consent_request(
                db, tenant.id, user.id, setup["candidate_id"]
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resend_goes_to_the_current_email(
        self, db, tenant, user, sent_to
    ):
        """QA (14.09) task 1: the address was corrected after the first send."""
        setup = await _setup(db, tenant, user)
        corrected = await _correct_email(db, setup["candidate_id"])
        assert sent_to == [setup["sent"]["email"]]

        resent = await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )

        assert sent_to[-1] == corrected
        assert resent["email"] == corrected, "the banner must name where it went"
        # Review 01.10: the first letter went to someone else, so its token
        # dies; the new one keeps the old expiry (a re-send, not a new link).
        old = await _row(db, setup["sent"]["id"])
        assert old.status == "superseded"
        fresh = await _row(db, resent["id"])
        assert fresh.token != old.token and fresh.expires_at == old.expires_at
        view = await consent_service.get_consent_by_token(db, old.token)
        assert view["status"] != "pending"
        with pytest.raises(HTTPException) as exc:
            await consent_service.sign_consent(db, old.token)
        assert exc.value.status_code == 410

    @pytest.mark.asyncio
    async def test_only_the_reissue_of_an_expired_link_is_charged(
        self, db, tenant, user, sent_to, monkeypatch
    ):
        from app.core import billing_hooks

        charged: list[str] = []

        async def consume(db, tenant_id, user_id, action, **kwargs):
            charged.append(action)

        monkeypatch.setattr(billing_hooks, "consume_action", consume)
        setup = await _setup(db, tenant, user)
        await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )
        assert charged == []
        row = await _row(db, setup["sent"]["id"])
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
        await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )
        assert charged == ["recruitment.send_consent_request"]

    @pytest.mark.asyncio
    async def test_expired_link_is_replaced_and_sent_to_the_current_email(
        self, db, tenant, user, sent_to
    ):
        """QA (14.09) task 2: no "Consent link has expired" — a new link."""
        setup = await _setup(db, tenant, user)
        row = await _row(db, setup["sent"]["id"])
        old_token = row.token
        # Issued 15 days ago for 14 days, so it ran out yesterday.
        now = datetime.now(UTC)
        row.created_at = now - timedelta(days=15)
        row.expires_at = now - timedelta(days=1)
        await db.commit()
        corrected = await _correct_email(db, setup["candidate_id"])

        resent = await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )

        assert resent["id"] != setup["sent"]["id"], "the dead link was re-sent"
        assert resent["status"] == "pending"
        assert resent["email"] == corrected
        assert sent_to[-1] == corrected
        fresh = await _row(db, resent["id"])
        assert fresh.token != old_token
        # The new link lives as long as the original was issued for.
        assert timedelta(days=13, hours=23) < fresh.expires_at - now
        assert fresh.expires_at - now < timedelta(days=14, minutes=1)
        assert (await _row(db, setup["sent"]["id"])).status == "expired"

    @pytest.mark.asyncio
    async def test_expired_token_cannot_be_signed_after_the_reissue(
        self, db, tenant, user, sent_to
    ):
        setup = await _setup(db, tenant, user)
        row = await _row(db, setup["sent"]["id"])
        old_token = row.token
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

        await consent_service.resend_consent_request(
            db, tenant.id, user.id, setup["candidate_id"]
        )

        # The public consent page shows the old link as dead.
        view = await consent_service.get_consent_by_token(db, old_token)
        assert view["status"] == "expired"


_FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
_SECTION = (
    _FRONTEND
    / "src"
    / "components"
    / "recruitment"
    / "candidate-interviews-section.tsx"
)


@pytest.mark.skipif(not _SECTION.exists(), reason="frontend tree not present")
def test_the_banner_calls_a_url_the_app_serves():
    """The Resend button's literal has to match the mounted route."""
    urls = re.findall(
        r"/recruitment/candidates/\$\{[^}]+\}/consent/\w+",
        _SECTION.read_text(encoding="utf-8"),
    )
    referenced = {"/api" + re.sub(r"\$?\{[^}]*\}", "{}", u) for u in urls}
    mounted = {
        re.sub(r"\{[^}]*\}", "{}", getattr(route, "path", ""))
        for route in app.routes
    }
    assert "/api/recruitment/candidates/{}/consent/resend" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
