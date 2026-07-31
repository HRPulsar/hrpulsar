"""HRP-84: lifecycle email notifications for assessments.

Covers the MVP matrix:
  1. Draft → Sent fires the per-role `Evaluate ...` email for every
     participant with an email (self / manager / peer / subordinate).
  2. Late add to a Sent assessment fires a single targeted Evaluate email.
  3. On Review → Done fires `completed` emails (self + manager).
  4. Sent → Cancelled fires `cancelled` emails (self + manager).
  5. Draft → Cancelled stays silent — there was no announcement, so no
     cancellation needs to land in anyone's inbox.

Tests capture the dispatch by monkeypatching ``_dispatch_lifecycle_emails``
so they don't actually try to send mail.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.schemas import (
    AssessmentCreate,
    ParticipantAdd,
)

from tests.unit._send_prereqs import advance_to_done, seed_send_prereqs


async def _make_user_employee(db, tenant, suffix: str):
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    u = AuthUser(
        email=f"hrp84-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("p"),
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return u, emp


def _patch_dispatch(monkeypatch):
    """Replace _dispatch_lifecycle_emails with a recorder. Returns the
    captured ``calls`` list — each entry is ``{assessment_id, event,
    only_participant_id}``."""
    calls: list[dict] = []

    async def fake_dispatch(
        db, assessment, event, *, only_participant_id=None
    ):
        calls.append(
            {
                "assessment_id": assessment.id,
                "event": event,
                "only_participant_id": only_participant_id,
            }
        )

    monkeypatch.setattr(service, "_dispatch_lifecycle_emails", fake_dispatch)
    return calls


@pytest.mark.asyncio
async def test_draft_to_sent_dispatches_evaluate(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    calls = _patch_dispatch(monkeypatch)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="N1", employee_id=employee.id, type_code="self"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")

    events = [c for c in calls if c["assessment_id"] == created["id"]]
    assert any(c["event"] == "evaluate" for c in events)


@pytest.mark.asyncio
async def test_late_add_dispatches_targeted_evaluate(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="N2", employee_id=employee.id, type_code="360"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")

    _patched_after_send = _patch_dispatch(monkeypatch)
    _, peer = await _make_user_employee(db, tenant, "late")
    added = await service.add_participant(
        db,
        tenant.id,
        uuid.UUID(str(created["id"])),
        ParticipantAdd(employee_id=peer.id, role="peer"),
    )
    targeted = [
        c
        for c in _patched_after_send
        if c["event"] == "evaluate" and c["only_participant_id"] == added["id"]
    ]
    assert targeted, "Late add must trigger a participant-scoped evaluate email"


@pytest.mark.asyncio
async def test_done_dispatches_completed(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="N3", employee_id=employee.id, type_code="self"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    # HRP-192 removed manual Sent → In progress — advance_to_done bridges
    # through on_review on its own, so the in_progress stopover is no
    # longer needed (and would now fail with a 400).
    calls = _patch_dispatch(monkeypatch)
    await advance_to_done(db, tenant.id, created["id"])
    assert any(c["event"] == "completed" for c in calls)


@pytest.mark.asyncio
async def test_sent_to_cancelled_dispatches_cancelled(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="N4", employee_id=employee.id, type_code="self"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    calls = _patch_dispatch(monkeypatch)
    await service.change_status(db, tenant.id, created["id"], "cancelled")
    assert any(c["event"] == "cancelled" for c in calls)


@pytest.mark.asyncio
async def test_draft_to_cancelled_is_silent(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="N5", employee_id=employee.id, type_code="self"),
    )
    # No transition to sent before cancelling — nobody was told the
    # assessment was live, so no cancellation email goes out.
    calls = _patch_dispatch(monkeypatch)
    await service.change_status(db, tenant.id, created["id"], "cancelled")
    assert not any(
        c["assessment_id"] == created["id"] and c["event"] == "cancelled"
        for c in calls
    )


@pytest.mark.asyncio
async def test_in_app_notification_row_written_on_send(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-84 REDO: bell sees the same event the email did."""
    from app.modules.notification.models import (
        Notification,
        NotificationTemplate,
    )
    from sqlalchemy import select

    # The seed migration (hrp84inappnotif) ships these templates in prod;
    # the unit suite skips migrations so we insert the template inline.
    tmpl = NotificationTemplate(
        code="assessment.self_evaluate",
        subject_template="Evaluate yourself",
        body_template="Please complete your assessment.",
        notification_type="assessment",
    )
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)

    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="Bell-Send", employee_id=employee.id, type_code="self"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])

    before = (
        await db.execute(
            select(Notification.id).where(Notification.recipient_id == user.id)
        )
    ).all()

    await service.change_status(db, tenant.id, created["id"], "sent")

    after = (
        await db.execute(
            select(Notification.template_id, Notification.context)
            .where(Notification.recipient_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).all()
    assert len(after) > len(before)
    template_id, context = after[0]
    assert template_id == tmpl.id
    assert context["event"] == "evaluate"
    assert context["role"] == "self"


# ---------- HRP-84 REDO ----------


@pytest.mark.asyncio
async def test_evaluate_email_links_to_assessment_detail_page(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-84 REDO: the Evaluate-yourself email CTA points at
    /assessments/{id} so the participant lands on the assessment they
    were just invited to instead of the generic list."""
    from unittest.mock import patch

    from app.core.email import enqueue_email

    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="Deeplink", employee_id=employee.id, type_code="self"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])

    captured: list[tuple[str, str, str]] = []

    def fake_enqueue(to, subject, body, **kwargs):
        captured.append((to, subject, body))

    with patch.object(service, "enqueue_email", fake_enqueue, create=True):
        # service._send_role_email imports enqueue_email lazily inside the
        # function — patch the source module so the lazy import resolves
        # to our spy.
        import app.core.email as email_mod

        with patch.object(email_mod, "enqueue_email", fake_enqueue):
            await service.change_status(db, tenant.id, created["id"], "sent")

    assert captured, "Expected at least one email"
    # Find the self-evaluate email (sent to the user who owns the assessment).
    self_emails = [(_, s, b) for _, s, b in captured if s.startswith("Evaluate yourself")]
    assert self_emails, f"No self-evaluate email captured: subjects={[s for _,s,_ in captured]}"
    _, _, body = self_emails[0]
    assert f"/assessments/{created['id']}" in body, (
        f"Email body must deep-link to the assessment detail page; got\n{body}"
    )
    _ = enqueue_email  # silence "unused import"


@pytest.mark.asyncio
async def test_evaluate_emails_render_in_each_recipient_locale(
    db, tenant, user, employee, assessment_statuses, assessment_types, monkeypatch
):
    """i18n F4 (HRP-478): a lifecycle batch renders per recipient, not per
    sender — the assessee's own ``User.language`` wins over the tenant
    default, while a participant without a preference inherits it."""
    from unittest.mock import patch

    from app.config import settings

    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "en")

    peer_user, peer_emp = await _make_user_employee(db, tenant, "locale")
    tenant.default_locale = "de"
    user.language = "en"
    await db.commit()

    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="Locale", employee_id=employee.id, type_code="360"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.add_participant(
        db,
        tenant.id,
        created["id"],
        ParticipantAdd(employee_id=peer_emp.id, role="peer"),
    )

    captured: dict[str, str] = {}

    def fake_enqueue(to, subject, body, **kwargs):
        captured[to] = body

    import app.core.email as email_mod

    with patch.object(email_mod, "enqueue_email", fake_enqueue):
        await service.change_status(db, tenant.id, created["id"], "sent")

    assert '<html lang="en">' in captured[user.email], (
        "User.language must beat the tenant default for the assessee's "
        "own email"
    )
    assert '<html lang="de">' in captured[peer_user.email], (
        "A participant without a language preference falls back to the "
        "tenant default"
    )


@pytest.mark.asyncio
async def test_cancelled_dispatches_to_peer_when_pending(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-84 REDO: cancellation now notifies pending peer / subordinate
    participants too — they're mid-flight reviewers whose work just got
    pulled. Already-completed reviewers stay silent."""
    from unittest.mock import patch

    from app.core.email import enqueue_email
    from app.modules.assessment.models import AssessmentParticipant
    from sqlalchemy import select

    peer_user, peer_emp = await _make_user_employee(db, tenant, "peer-cancel")
    completed_user, completed_emp = await _make_user_employee(db, tenant, "peer-done")

    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(title="Cancel-Peer", employee_id=employee.id, type_code="360"),
    )
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.add_participant(
        db,
        tenant.id,
        created["id"],
        ParticipantAdd(employee_id=peer_emp.id, role="peer"),
    )
    await service.add_participant(
        db,
        tenant.id,
        created["id"],
        ParticipantAdd(employee_id=completed_emp.id, role="subordinate"),
    )
    await service.change_status(db, tenant.id, created["id"], "sent")

    # Flag the subordinate as already-completed; they should NOT receive
    # the cancellation email (their work is done).
    parts = (
        await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == created["id"]
            )
        )
    ).scalars().all()
    for p in parts:
        if p.user_id == completed_user.id:
            p.is_completed = True
    await db.commit()

    captured: list[tuple[str, str]] = []

    def fake_enqueue(to, subject, body, **kwargs):
        captured.append((to, subject))

    import app.core.email as email_mod

    with patch.object(email_mod, "enqueue_email", fake_enqueue):
        await service.change_status(db, tenant.id, created["id"], "cancelled")

    targeted_subjects = {subject for _, subject in captured}
    peer_emails = [c for c in captured if c[0] == peer_user.email]
    completed_emails = [c for c in captured if c[0] == completed_user.email]
    assert peer_emails, (
        "Pending peer participant must receive the cancellation email "
        f"(captured: {targeted_subjects})"
    )
    assert not completed_emails, (
        "Already-completed reviewer must stay silent on cancellation "
        f"(captured for completed user: {completed_emails})"
    )

    _ = enqueue_email  # silence "unused import"
