"""HRP-381: what the external evaluator's link says when it cannot work.

Every one of these ends the page, so each needs its own code: the page
picks the copy from the error code, and "This link is invalid. Please
contact the recruiter who sent it." was being shown for three different
situations the evaluator can do nothing about.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.recruitment import manager_assessment_public as public_service
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateVacancy,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_profile,
    _make_vacancy,
)


async def _invited(db: AsyncSession, tenant, user, *, consent: bool = True):
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    token = uuid.uuid4().hex
    invite = AssessmentInvite(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        token=token,
        token_hash=public_service.hash_token(token),
        email="ext@example.com",
        evaluator_name="Ext Eval",
        status="opened",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        allow_reediting=True,
        delivery_status="sent",
        invited_by=user.id,
        consent_accepted_at=datetime.now(timezone.utc) if consent else None,
    )
    db.add(invite)
    await db.commit()
    return token, cv, vacancy


class TestDeclinedLink:
    """Declining is an answer, not a broken link."""

    async def test_declining_keeps_its_own_code(self, db: AsyncSession, tenant, user):
        token, _, _ = await _invited(db, tenant, user, consent=False)
        await public_service.public_decline(db, token)

        with pytest.raises(HTTPException) as exc:
            await public_service.public_get_context(db, token)
        assert exc.value.status_code == 410
        assert exc.value.code == "invitation_declined"

    async def test_coming_back_says_the_same_thing(
        self, db: AsyncSession, tenant, user
    ):
        token, _, _ = await _invited(db, tenant, user, consent=False)
        await public_service.public_decline(db, token)

        for _ in range(2):
            with pytest.raises(HTTPException) as exc:
                await public_service.public_get_context(db, token)
            assert exc.value.code == "invitation_declined"


class TestCandidateGone:
    async def test_detaching_from_the_vacancy_kills_the_token_itself(
        self, db: AsyncSession, tenant, user
    ):
        """Removing a candidate from a vacancy takes the invite with it.

        ``assessment_invites.candidate_vacancy_id`` is ON DELETE CASCADE
        and "remove from vacancy" is a real DELETE of the link row, so
        there is no invite left to explain anything with: the token is
        indistinguishable from one that was never issued. Pinned here so
        the difference from the archived-candidate case below is a
        recorded decision rather than an accident.
        """
        token, cv, _ = await _invited(db, tenant, user)
        await db.delete(await db.get(CandidateVacancy, cv.id))
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await public_service.public_get_context(db, token)
        assert exc.value.status_code == 410
        assert exc.value.code == "invalid_invite_link"

    async def test_candidate_archived(self, db: AsyncSession, tenant, user):
        token, cv, _ = await _invited(db, tenant, user)
        candidate = await db.get(Candidate, cv.candidate_id)
        candidate.archived_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await public_service.public_get_context(db, token)
        assert exc.value.status_code == 410
        assert exc.value.code == "candidate_no_longer_available"

    async def test_the_resume_goes_with_it(self, db: AsyncSession, tenant, user):
        token, cv, _ = await _invited(db, tenant, user)
        candidate = await db.get(Candidate, cv.candidate_id)
        candidate.archived_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await public_service.public_resume_preview(db, token)
        assert exc.value.code == "candidate_no_longer_available"


class TestVacancyGone:
    """Expected result of the 04.09 test run: an archived vacancy ends the link.

    The original table asked for read-only access with a notice; the
    tester's expected result replaced it with a 410, and read-only would
    be a fourth state on a page that already has three.
    """

    async def test_archived_vacancy_ends_the_link(
        self, db: AsyncSession, tenant, user
    ):
        token, _, vacancy = await _invited(db, tenant, user)
        vacancy.archived_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await public_service.public_get_context(db, token)
        assert exc.value.status_code == 410
        assert exc.value.code == "vacancy_no_longer_available"

    async def test_resume_preview_too(self, db: AsyncSession, tenant, user):
        token, _, vacancy = await _invited(db, tenant, user)
        vacancy.archived_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await public_service.public_resume_preview(db, token)
        assert exc.value.code == "vacancy_no_longer_available"


class TestLiveLinkStillWorks:
    async def test_healthy_invite_reaches_the_sheet(
        self, db: AsyncSession, tenant, user
    ):
        token, _, _ = await _invited(db, tenant, user)
        ctx = await public_service.public_get_context(db, token)
        assert ctx["consent_accepted"] is True
        assert ctx["candidate_vacancy_id"] is not None
