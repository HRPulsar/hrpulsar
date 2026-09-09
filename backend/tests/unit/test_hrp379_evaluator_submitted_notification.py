"""HRP-379: the vacancy owner is told when an external evaluator submits.

The evaluator's own page has always promised it — "Thank you! Your
evaluation has been submitted. {name} will be notified." — and nothing
was ever sent. Covered here: the event fires once per submitted sheet,
carries the recipient and a link back into the candidate's assessments,
and a re-edited re-submit does not send a second copy.
"""

from __future__ import annotations

import importlib.util
import pathlib
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.modules.recruitment import manager_assessment_public as public_service
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import RoundCreate
from app.modules.recruitment.models import AssessmentInvite
from app.modules.recruitment.notifications import (
    EVENT_TEMPLATE,
    _add_absolute_link,
    _resolve_assessment_submitted,
)
from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_extra_user,
    _make_profile,
    _make_vacancy,
)

EVENT = "recruitment.assessment.evaluator_submitted"
CODE = "recruitment.assessment_evaluator_submitted"


def _migration():
    # The test database is built from model metadata, so migration seeds
    # never run against it — assert on the migration's own table.
    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "hrp379submittpl01_evaluator_submitted_template.py"
    )
    spec = importlib.util.spec_from_file_location("hrp379submittpl01", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _invited_evaluator(db: AsyncSession, tenant, user, *, owner=None):
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    if owner is not None:
        vacancy.owner_id = owner.id
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
    )
    token = uuid.uuid4().hex
    invite = AssessmentInvite(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        round_id=uuid.UUID(str(rd["id"])),
        token=token,
        token_hash=public_service.hash_token(token),
        email="ext@example.com",
        evaluator_name="Ext Eval",
        status="opened",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        allow_reediting=True,
        delivery_status="sent",
        invited_by=user.id,
        consent_accepted_at=datetime.now(timezone.utc),
    )
    db.add(invite)
    await db.commit()
    return token, cv, vacancy


class TestSubmitPublishesTheEvent:
    async def test_owner_is_notified_once(self, db: AsyncSession, tenant, user):
        owner = await _make_extra_user(db, tenant)
        token, cv, vacancy = await _invited_evaluator(db, tenant, user, owner=owner)

        with patch("app.core.events.publish", new=AsyncMock()) as publish:
            await public_service.public_submit(db, token)

        assert publish.await_count == 1
        event, payload = publish.call_args.args
        assert event == EVENT
        assert payload["owner_user_id"] == str(owner.id)
        assert payload["evaluator_name"] == "Ext Eval"
        assert payload["vacancy_title"] == vacancy.title
        assert payload["round_type"] == "interview"
        # Straight into the block that shows the sheet that just landed.
        assert payload["link"] == (
            f"/recruitment/candidates/{cv.candidate_id}"
            f"?vacancyId={cv.vacancy_id}#manager-assessments"
        )

    async def test_resubmitting_does_not_send_a_second_copy(
        self, db: AsyncSession, tenant, user
    ):
        """Re-editing is allowed on this invite; re-notifying is not.

        The owner already knows the evaluation is in — a second identical
        email on every correction is noise, so the notice is tied to the
        first submit (decision recorded on HRP-379).
        """
        owner = await _make_extra_user(db, tenant)
        token, _, _ = await _invited_evaluator(db, tenant, user, owner=owner)

        with patch("app.core.events.publish", new=AsyncMock()) as publish:
            await public_service.public_submit(db, token)
            await public_service.public_submit(db, token)

        assert publish.await_count == 1

    async def test_falls_back_to_whoever_invited_the_evaluator(
        self, db: AsyncSession, tenant, user
    ):
        token, _, vacancy = await _invited_evaluator(db, tenant, user)
        vacancy.owner_id = None
        vacancy.hiring_manager_id = None
        await db.commit()

        with patch("app.core.events.publish", new=AsyncMock()) as publish:
            await public_service.public_submit(db, token)

        _, payload = publish.call_args.args
        assert payload["owner_user_id"] == str(user.id)

    async def test_a_failing_notification_does_not_lose_the_evaluation(
        self, db: AsyncSession, tenant, user
    ):
        token, _, _ = await _invited_evaluator(db, tenant, user)

        with patch(
            "app.core.events.publish", new=AsyncMock(side_effect=RuntimeError("smtp"))
        ):
            out = await public_service.public_submit(db, token)

        assert out["status"] == "submitted"


class TestBannerNamesTheSamePerson:
    """"{name} will be notified" has to name whoever gets the email."""

    async def test_context_carries_the_owner_name(
        self, db: AsyncSession, tenant, user
    ):
        owner = await _make_extra_user(db, tenant)
        owner.first_name = "Olga"
        owner.last_name = "Owner"
        await db.commit()
        token, _, _ = await _invited_evaluator(db, tenant, user, owner=owner)

        ctx = await public_service.public_get_context(db, token)
        assert ctx["owner_name"] == "Olga Owner"

    async def test_without_an_owner_it_is_the_inviter(
        self, db: AsyncSession, tenant, user
    ):
        token, _, vacancy = await _invited_evaluator(db, tenant, user)
        vacancy.owner_id = None
        vacancy.hiring_manager_id = None
        await db.commit()

        ctx = await public_service.public_get_context(db, token)
        assert ctx["owner_name"] == ctx["recruiter_name"]


class TestRecipientResolution:
    async def test_resolver_returns_the_owner(self, db: AsyncSession, tenant, user):
        owner = await _make_extra_user(db, tenant)
        users = await _resolve_assessment_submitted(
            db, tenant.id, {"owner_user_id": str(owner.id)}
        )
        assert [u.id for u in users] == [owner.id]

    async def test_no_recipient_sends_nothing(self, db: AsyncSession, tenant):
        assert await _resolve_assessment_submitted(db, tenant.id, {}) == []

    def test_event_is_mapped_to_its_template(self):
        assert EVENT_TEMPLATE[EVENT] == CODE


class TestTemplate:
    def test_both_core_locales_are_seeded(self):
        locales = {locale for locale, _, _ in _migration()._TEMPLATES}
        assert locales == {"en", "de"}

    def test_english_subject_is_the_one_from_the_ticket(self):
        subject = next(
            s for locale, s, _ in _migration()._TEMPLATES if locale == "en"
        )
        assert (
            Template(subject).render(candidate_name="Jane Doe")
            == "Submitted assessment for candidate Jane Doe"
        )

    def test_body_names_the_evaluator_and_links_back(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        body = next(b for locale, _, b in _migration()._TEMPLATES if locale == "en")
        ctx = {
            "candidate_name": "Jane Doe",
            "evaluator_name": "Ext Eval",
            "vacancy_title": "QA Engineer",
            "round_type": "interview",
            "round_number": 2,
            "link": "/recruitment/candidates/x?vacancyId=y#manager-assessments",
        }
        _add_absolute_link(ctx)
        rendered = Template(body).render(**ctx)
        assert "Ext Eval" in rendered
        assert "QA Engineer" in rendered
        assert "Interview 2" in rendered
        assert "https://app.example.com/recruitment/candidates/x" in rendered

    def test_russian_mirror_covers_the_same_code(self):
        path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "migrations"
            / "versions"
            / "ee"
            / "ee021_evaluator_submitted_ru_template.py"
        )
        if not path.exists():
            # The ru mirror is enterprise-only; the community tree has no
            # migrations/versions/ee at all, so there is nothing to check.
            pytest.skip("enterprise ru template migration absent in this tree")
        spec = importlib.util.spec_from_file_location("ee021", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert CODE in module._TEMPLATES
