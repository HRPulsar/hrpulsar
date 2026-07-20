"""HRP-211: Talent Market lifecycle email notifications.

Covers the six events the spec calls out by monkeypatching the
service-side ``_dispatch_lifecycle_emails`` so the tests don't actually
enqueue mail. We pin both the event tag the dispatcher receives and the
filter (single-candidate vs whole-card) so a future refactor that
collapses the helpers can't silently drop a notification path.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.talent_market import common, service
from app.modules.talent_market.models import (
    TalentCard,
    TalentCardCompetence,
)
from app.modules.talent_market.schemas import (
    CandidateAdd,
    CandidateBulkAdd,
    TalentCardCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _patch_dispatch(monkeypatch):
    """Stand in for ``_dispatch_lifecycle_emails`` and capture every call."""
    calls: list[dict] = []

    async def fake_dispatch(
        db,
        card,
        event,
        *,
        only_candidate_ids=None,
        appointed_before_cancel=None,
        # HRP-245: keep this stub in sync with the real dispatcher so a
        # future test that drives delete_candidate through this fixture
        # doesn't TypeError on the new kwarg.
        removed_employee_ids=None,
    ):
        calls.append(
            {
                "card_id": card.id,
                "event": event,
                "only_candidate_ids": (
                    list(only_candidate_ids) if only_candidate_ids else None
                ),
                "appointed_before_cancel": (
                    list(appointed_before_cancel) if appointed_before_cancel else None
                ),
                "removed_employee_ids": (
                    list(removed_employee_ids) if removed_employee_ids else None
                ),
            }
        )

    monkeypatch.setattr(common, "_dispatch_lifecycle_emails", fake_dispatch)
    return calls


async def _make_employee(
    db: AsyncSession, tenant, *, suffix: str
) -> Employee:
    u = User(
        tenant_id=tenant.id,
        email=f"hrp211-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash="x",
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        tenant_id=tenant.id, user_id=u.id, hire_date=date(2024, 1, 1)
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _attach_min_competence(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> None:
    from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel

    g = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(g)
    await db.flush()
    c = Competence(tenant_id=tenant_id, group_id=g.id, title="C")
    db.add(c)
    sl = SkillLevel(tenant_id=tenant_id, title="L", sort_index=1)
    db.add(sl)
    await db.flush()
    db.add(
        TalentCardCompetence(
            card_id=card_id,
            competence_id=c.id,
            skill_level_id=sl.id,
            match_percent=80,
        )
    )
    await db.commit()


async def _force_published(db: AsyncSession, card_id: uuid.UUID) -> None:
    card = await db.get(TalentCard, card_id)
    assert card is not None
    card.status = "published"
    card.is_published = True
    card.published_at = datetime.now(timezone.utc)
    await db.commit()


async def test_publish_dispatches_published_event(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    calls = _patch_dispatch(monkeypatch)
    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy"),
    )
    emp = await _make_employee(db, tenant, suffix="pub")
    await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    await _attach_min_competence(db, tenant.id, card["id"])

    await service.publish_card(db, tenant.id, card["id"])

    publish_calls = [c for c in calls if c["event"] == "published"]
    assert len(publish_calls) == 1
    assert publish_calls[0]["card_id"] == card["id"]
    assert publish_calls[0]["only_candidate_ids"] is None


async def test_add_candidate_silent_on_draft(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    calls = _patch_dispatch(monkeypatch)
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="D", card_type="vacancy")
    )
    emp = await _make_employee(db, tenant, suffix="draft")
    await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    assert [c for c in calls if c["event"] == "candidate_added"] == []


async def test_add_candidate_published_fires_candidate_added(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="P", card_type="vacancy")
    )
    await _force_published(db, card["id"])
    emp = await _make_employee(db, tenant, suffix="pubadd")

    calls = _patch_dispatch(monkeypatch)
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    events = [c for c in calls if c["event"] == "candidate_added"]
    assert len(events) == 1
    assert events[0]["only_candidate_ids"] == [cand["id"]]


async def test_add_candidates_bulk_published_fires_one_event(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="B", card_type="vacancy")
    )
    await _force_published(db, card["id"])
    emp_a = await _make_employee(db, tenant, suffix="ba")
    emp_b = await _make_employee(db, tenant, suffix="bb")

    calls = _patch_dispatch(monkeypatch)
    rows = await service.add_candidates_bulk(
        db,
        tenant.id,
        card["id"],
        CandidateBulkAdd(employee_ids=[emp_a.id, emp_b.id]),
    )
    events = [c for c in calls if c["event"] == "candidate_added"]
    assert len(events) == 1
    assert sorted(events[0]["only_candidate_ids"]) == sorted(
        row["id"] for row in rows
    )


async def test_appoint_fires_appointed_event(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="A", card_type="vacancy")
    )
    emp = await _make_employee(db, tenant, suffix="app")
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )

    calls = _patch_dispatch(monkeypatch)
    await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])
    events = [c for c in calls if c["event"] == "appointed"]
    assert len(events) == 1
    assert events[0]["only_candidate_ids"] == [cand["id"]]


async def test_complete_fires_completed_event(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="C", card_type="vacancy")
    )
    emp = await _make_employee(db, tenant, suffix="comp")
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])
    await _force_published(db, card["id"])

    calls = _patch_dispatch(monkeypatch)
    await service.complete_card(db, tenant.id, card["id"])
    events = [c for c in calls if c["event"] == "completed"]
    assert len(events) == 1
    assert events[0]["card_id"] == card["id"]


async def test_cancel_from_draft_passes_appointed_before(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="CD", card_type="vacancy")
    )
    emp = await _make_employee(db, tenant, suffix="cd")
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])

    calls = _patch_dispatch(monkeypatch)
    await service.cancel_card(db, tenant.id, card["id"])
    events = [c for c in calls if c["event"] == "cancelled_from_draft"]
    assert len(events) == 1
    assert events[0]["appointed_before_cancel"] == [emp.id]


async def test_cancel_from_published_routes_to_published_handler(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="CP", card_type="vacancy")
    )
    await _force_published(db, card["id"])

    calls = _patch_dispatch(monkeypatch)
    await service.cancel_card(db, tenant.id, card["id"])
    events = [c for c in calls if c["event"] == "cancelled_from_published"]
    assert len(events) == 1


def _patch_enqueue(monkeypatch):
    """Capture every enqueue_email call so we can count letters per event.

    HRP-211 REDO (2026-06-09): when a self-managed employee gets
    appointed / cancelled, only the appointed-self / cancelled-self
    mail must fire — the manager-side mail is intentionally suppressed
    because the manager IS the employee.
    """
    sent: list[tuple[str, str]] = []

    def fake_enqueue(
        recipient,
        subject,
        body,
        *,
        tenant_id=None,
        template_code=None,
    ):
        sent.append((recipient, subject))

    from app.core import email as email_mod
    from app.modules.talent_market import common as tm_common

    # The dispatcher imports ``enqueue_email`` inside the function body
    # so we patch the symbol on the email module itself (the dispatcher
    # picks the patched version on each call).
    monkeypatch.setattr(email_mod, "enqueue_email", fake_enqueue)
    monkeypatch.setattr(
        tm_common,
        "_dispatch_lifecycle_emails",
        tm_common._dispatch_lifecycle_emails,
    )
    return sent


async def test_self_managed_appoint_skips_manager_email(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    """A manager appointing themselves should get only the self mail."""
    from app.modules.company.models import Division

    emp = await _make_employee(db, tenant, suffix="selfmgr")
    division = Division(
        tenant_id=tenant.id, name="Solo", manager_id=emp.id
    )
    db.add(division)
    await db.flush()
    emp.division_id = division.id
    await db.commit()

    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="SelfMgr", card_type="vacancy"),
    )
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )

    sent = _patch_enqueue(monkeypatch)
    await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])

    # Exactly one mail, addressed to the appointed-self subject.
    assert len(sent) == 1
    assert sent[0][1].startswith("You are appointed!")


async def test_self_managed_cancel_skips_manager_email(
    db: AsyncSession, tenant, user, monkeypatch
) -> None:
    """Cancelling a Draft card with a self-managed appointee fires the
    self cancellation mail only — the dispatcher must skip the manager
    bucket so the employee doesn't get two copies."""
    from app.modules.company.models import Division

    emp = await _make_employee(db, tenant, suffix="selfcanc")
    division = Division(
        tenant_id=tenant.id, name="Solo", manager_id=emp.id
    )
    db.add(division)
    await db.flush()
    emp.division_id = division.id
    await db.commit()

    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="SelfCanc", card_type="vacancy"),
    )
    cand = await service.add_candidate(
        db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
    )
    await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])

    sent = _patch_enqueue(monkeypatch)
    await service.cancel_card(db, tenant.id, card["id"])

    # Only the cancellation-self mail; the manager-side mail is suppressed.
    subjects = [s for _, s in sent]
    assert any(s.startswith("Your appointment cancelled") for s in subjects)
    assert not any(
        s.startswith("Your employee") for s in subjects
    )
