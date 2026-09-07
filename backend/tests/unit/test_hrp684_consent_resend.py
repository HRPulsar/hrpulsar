"""HRP-684: resending the recording-consent link.

Resend re-mails the *pending* request instead of issuing a new one — a
candidate who still has the first email must not find a dead link because
someone in the office pressed Resend. What is asserted here: the token
survives, ``last_sent_at`` moves, an expired or absent request refuses,
and the URL the banner calls is a URL the app serves.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.main import app
from app.modules.recruitment import consent_service, service
from app.modules.recruitment.models import ConsentRequest, ConsentTemplate
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
            db, tenant.id, setup["candidate_id"]
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
        row.signed_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await consent_service.resend_consent_request(
                db, tenant.id, setup["candidate_id"]
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_expired_link_is_not_resent(self, db, tenant, user):
        setup = await _setup(db, tenant, user)
        row = await _row(db, setup["sent"]["id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await consent_service.resend_consent_request(
                db, tenant.id, setup["candidate_id"]
            )
        assert exc.value.status_code == 409


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
