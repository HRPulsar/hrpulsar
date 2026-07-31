"""R4c — recruitment notification fan-out (FR §8.5, SCR-03).

The recruitment service publishes ten event types through the in-process
event bus. Handlers in ``recruitment/notifications.py`` translate each
event into Notification rows + outbound emails. These tests verify the
end-to-end shape: publish → handler → row in ``notifications`` table
with the right ``recipient_id`` / ``template_code`` / ``context``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.config import settings
from app.core import events
from app.modules.notification.models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
)
from app.modules.recruitment import notifications as recruitment_notifications
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_TEMPLATES = (
    ("recruitment.vacancy_assigned", "Vacancy assigned: {{ vacancy_title }}", "x"),
    ("recruitment.candidate_attached", "New candidate", "x"),
    ("recruitment.candidate_stage_changed", "Stage change", "x"),
    ("recruitment.interview_scheduled", "Interview scheduled", "x"),
    ("recruitment.interview_transcript_ready", "Transcript ready", "x"),
    ("recruitment.interview_analysis_ready", "Analysis ready", "x"),
    ("recruitment.report_generated", "Report ready", "x"),
    ("recruitment.consent_signed", "Consent signed", "x"),
    ("recruitment.invite_completed", "Evaluation submitted", "x"),
    ("recruitment.ai_task_failed", "AI task failed", "x"),
)


@pytest_asyncio.fixture(autouse=True)
async def _seed_templates(db: AsyncSession):
    """Populate the notification_templates table with the recruitment codes.

    Tests bootstrap the DB via ``Base.metadata.create_all`` — alembic
    seeds never run, so templates would be missing. Insert them in-test.
    """
    for code, subject, body in _TEMPLATES:
        # Rows are per (code, locale) since i18n F4 — the shared test DB
        # also holds de rows seeded by the locale tests below, so the
        # existence probe must pin the locale or it sees two rows.
        existing = (
            await db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.code == code,
                    NotificationTemplate.locale == "en",
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                NotificationTemplate(
                    code=code,
                    subject_template=subject,
                    body_template=body,
                    notification_type="email",
                )
            )
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _register_handlers(db: AsyncSession, monkeypatch):
    """Re-subscribe handlers and force them to use the test session.

    The real handlers open their own ``async_session()`` — that points
    at the dev DB, not the test DB. We monkeypatch
    :func:`app.database.async_session` to return a context manager that
    yields the test session.
    """

    class _SessionWrapper:
        def __init__(self, session: AsyncSession):
            self._session = session

        async def __aenter__(self) -> AsyncSession:
            return self._session

        async def __aexit__(self, *exc) -> None:
            return None

    def _factory() -> _SessionWrapper:
        return _SessionWrapper(db)

    monkeypatch.setattr("app.database.async_session", _factory)

    original = events._handlers.copy()
    events._handlers.clear()
    recruitment_notifications.register()
    try:
        yield
    finally:
        events._handlers.clear()
        events._handlers.update(original)


@pytest.fixture
def locales_de_en(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "en")


async def _publish(event: str, payload: dict[str, Any]) -> None:
    await events.publish(event, payload)


async def _list_notifications_for(
    db: AsyncSession, recipient_id: uuid.UUID
) -> list[Notification]:
    rows = (
        await db.execute(
            select(Notification).where(Notification.recipient_id == recipient_id)
        )
    ).scalars().all()
    return list(rows)


class TestRecruitmentNotifications:
    async def test_vacancy_assigned(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.vacancy.assigned",
            {
                "tenant_id": str(tenant.id),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "Senior Engineer",
                "new_owner_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1
        assert rows[0].tenant_id == tenant.id

    async def test_candidate_attached(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.candidate.attached",
            {
                "tenant_id": str(tenant.id),
                "cv_id": str(uuid.uuid4()),
                "vacancy_title": "Vacancy",
                "candidate_name": "Alice",
                "owner_id": str(user.id),
                "actor_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_candidate_stage_changed(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.candidate.stage_changed",
            {
                "tenant_id": str(tenant.id),
                "cv_id": str(uuid.uuid4()),
                "stage_name": "Screening",
                "owner_id": str(user.id),
                "actor_id": None,
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_interview_scheduled(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.interview.scheduled",
            {
                "tenant_id": str(tenant.id),
                "interview_id": str(uuid.uuid4()),
                "interviewer_id": str(user.id),
                "candidate_name": "Bob",
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_interview_transcript_ready(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.interview.transcript_ready",
            {
                "tenant_id": str(tenant.id),
                "interview_id": str(uuid.uuid4()),
                "interviewer_id": str(user.id),
                "candidate_name": "Bob",
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_interview_analysis_ready(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.interview.analysis_ready",
            {
                "tenant_id": str(tenant.id),
                "interview_id": str(uuid.uuid4()),
                "interviewer_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_report_generated(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.report.generated",
            {
                "tenant_id": str(tenant.id),
                "report_id": str(uuid.uuid4()),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "Vacancy",
                "generated_by": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_consent_signed_routes_to_requester(
        self, db: AsyncSession, tenant, user
    ):
        await _publish(
            "recruitment.consent.signed",
            {
                "tenant_id": str(tenant.id),
                "consent_request_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "candidate_name": "Carla",
                "requested_by": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_consent_signed_fallback_to_admins(
        self, db: AsyncSession, tenant, user
    ):
        # No ``requested_by`` → fan out to admin roles. ``user`` has
        # the system ``admin`` role from the conftest factory.
        await _publish(
            "recruitment.consent.signed",
            {
                "tenant_id": str(tenant.id),
                "consent_request_id": str(uuid.uuid4()),
                "candidate_name": "Carla",
                "requested_by": None,
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_invite_completed_fallback_admins(
        self, db: AsyncSession, tenant, user
    ):
        await _publish(
            "recruitment.invite.completed",
            {
                "tenant_id": str(tenant.id),
                "invite_id": str(uuid.uuid4()),
                "cv_id": str(uuid.uuid4()),
                "evaluator_name": "External evaluator",
                "candidate_name": "Diana",
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_ai_task_failed(self, db: AsyncSession, tenant, user):
        await _publish(
            "recruitment.ai.task_failed",
            {
                "tenant_id": str(tenant.id),
                "task_type": "transcribe_interview_task",
                "entity_id": str(uuid.uuid4()),
                "error": "boom",
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1

    async def test_cross_tenant_isolation(
        self, db: AsyncSession, tenant, user
    ):
        # Publishing for another tenant must not write rows visible to
        # ``user`` (different tenant_id on the payload).
        other_tenant_id = uuid.uuid4()
        await _publish(
            "recruitment.vacancy.assigned",
            {
                "tenant_id": str(other_tenant_id),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "Other",
                "new_owner_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert rows == [], "cross-tenant leak"

    async def test_in_app_preference_disabled(
        self, db: AsyncSession, tenant, user
    ):
        db.add(
            NotificationPreference(
                user_id=user.id,
                event_type="recruitment.vacancy.assigned",
                channel="in_app",
                enabled=False,
            )
        )
        await db.commit()

        await _publish(
            "recruitment.vacancy.assigned",
            {
                "tenant_id": str(tenant.id),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "x",
                "new_owner_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert rows == []


class TestRecipientLocale:
    """i18n F4 (HRP-478): the recipient's locale picks the template row.

    Recruitment fan-out resolves ``User.language > Tenant.default_locale
    > deployment default`` per recipient and reads the matching
    ``NotificationTemplate`` row, falling back to the en row.
    """

    async def test_de_recipient_gets_de_template_row(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        de_row = NotificationTemplate(
            code="recruitment.vacancy_assigned",
            locale="de",
            subject_template="Vakanz zugewiesen: {{ vacancy_title }}",
            body_template="x",
            notification_type="email",
        )
        db.add(de_row)
        user.language = "de"
        await db.commit()

        await _publish(
            "recruitment.vacancy.assigned",
            {
                "tenant_id": str(tenant.id),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "Senior Engineer",
                "new_owner_id": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1
        assert rows[0].template_id == de_row.id

    async def test_falls_back_to_en_row_without_de_translation(
        self, db: AsyncSession, tenant, user, locales_de_en
    ):
        # ``recruitment.report_generated`` is seeded in en only, so a de
        # recipient must still get the en row rather than no row at all.
        user.language = "de"
        await db.commit()

        await _publish(
            "recruitment.report.generated",
            {
                "tenant_id": str(tenant.id),
                "report_id": str(uuid.uuid4()),
                "vacancy_id": str(uuid.uuid4()),
                "vacancy_title": "Vacancy",
                "generated_by": str(user.id),
            },
        )
        rows = await _list_notifications_for(db, user.id)
        assert len(rows) == 1
        template = await db.get(NotificationTemplate, rows[0].template_id)
        assert template is not None
        assert template.code == "recruitment.report_generated"
        assert template.locale == "en"


class TestServicePublishesEvents:
    """Confirms the service-layer mutations actually publish events."""

    async def test_attach_candidate_publishes_event(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment import service
        from app.modules.recruitment.schemas import (
            CandidateCreate,
            CandidateVacancyCreate,
            VacancyCreate,
        )

        vac = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title=f"V-{uuid.uuid4().hex[:4]}"),
        )
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="A",
                last_name="B",
                email=f"{uuid.uuid4().hex[:6]}@x.com",
            ),
        )

        captured: list[tuple[str, dict]] = []

        async def _fake_publish(event: str, payload: dict) -> None:
            captured.append((event, payload))

        with patch("app.modules.recruitment.candidate_service._publish_event", side_effect=_fake_publish):
            await service.attach_candidate(
                db,
                tenant.id,
                user.id,
                CandidateVacancyCreate(
                    candidate_id=uuid.UUID(str(cand["id"])),
                    vacancy_id=uuid.UUID(str(vac["id"])),
                ),
            )

        names = {e for e, _ in captured}
        assert "recruitment.candidate.attached" in names


class TestTaskFailureNAI:
    """task_failure-signal handler fires N-AI even when the row already
    flipped to ``failed`` in the task's own except block (transcribe /
    analyze pattern with ``self.retry``).
    """

    async def test_task_failure_publishes_nai_for_failed_row(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        from app.modules.recruitment.models import (
            CandidateVacancy,
            Interview,
            Vacancy,
        )
        from app.modules.recruitment.tasks.maintenance import (
            _on_recruitment_task_failure,
        )

        # Build the minimum data graph: a vacancy + cv + interview with
        # ``transcription_status='failed'`` (same shape as after the task's
        # inline except block ran prior to ``self.retry``).
        vacancy = Vacancy(tenant_id=tenant.id, title="V", owner_id=user.id)
        db.add(vacancy)
        await db.flush()
        from app.models import Person
        from app.modules.recruitment.models import Candidate

        person = Person(first_name="X", last_name="Y", email="x@y.z")
        db.add(person)
        await db.flush()
        candidate = Candidate(
            tenant_id=tenant.id,
            person_id=person.id,
            full_name=f"{person.first_name} {person.last_name}",
            email=person.email,
        )
        db.add(candidate)
        await db.flush()
        cv = CandidateVacancy(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            vacancy_id=vacancy.id,
            status="new",
        )
        db.add(cv)
        await db.flush()
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv.id,
            interviewer_id=user.id,
            transcription_status="failed",
            transcription_error="boom",
        )
        db.add(interview)
        await db.commit()

        # Point the handler's sync engine at the test DB.
        from app.config import settings as app_settings

        from tests.conftest import TEST_DB_URL

        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)

        class _FakeRequest:
            args = (str(interview.id),)

        class _FakeSender:
            name = "app.modules.recruitment.tasks.transcribe_interview_task"
            request = _FakeRequest()

        _on_recruitment_task_failure(
            sender=_FakeSender(),
            task_id="t-1",
            exception=RuntimeError("provider rate limited"),
        )

        # Re-read across the async session to see the row written by the
        # sync handler in a separate connection.
        await db.commit()
        await db.close()
        from app.modules.notification.models import Notification

        rows = (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant.id,
                    Notification.recipient_id == user.id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1, "task_failure handler must publish N-AI"
