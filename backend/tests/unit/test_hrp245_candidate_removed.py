"""HRP-245: notify a candidate when they are removed from a Published card.

Two layers:

- Template rendering (subject is the literal "You are not considered more: …"
  from the spec, with a sane fallback when the title is blank).
- Service wiring — ``delete_candidate`` dispatches the
  ``candidate_removed_from_published`` event only when the card is in
  ``published`` status, and the dispatcher actually sends the mail to the
  removed employee's user.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.core.email_templates import render_talent_market_removed_candidate_email
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.talent_market import common, service
from app.modules.talent_market.models import TalentCard
from app.modules.talent_market.schemas import CandidateAdd, TalentCardCreate
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers (mirror HRP-211 fixtures)
# ---------------------------------------------------------------------------


async def _make_employee(db: AsyncSession, tenant, *, suffix: str) -> Employee:
    u = User(
        tenant_id=tenant.id,
        email=f"hrp245-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash="x",
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    emp = Employee(tenant_id=tenant.id, user_id=u.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _force_published(db: AsyncSession, card_id: uuid.UUID) -> None:
    card = await db.get(TalentCard, card_id)
    assert card is not None
    card.status = "published"
    card.is_published = True
    card.published_at = datetime.now(timezone.utc)
    await db.commit()


def _patch_dispatch(monkeypatch):
    calls: list[dict] = []

    async def fake_dispatch(
        db,
        card,
        event,
        *,
        only_candidate_ids=None,
        appointed_before_cancel=None,
        removed_employee_ids=None,
    ):
        calls.append(
            {
                "card_id": card.id,
                "event": event,
                "only_candidate_ids": (
                    list(only_candidate_ids) if only_candidate_ids else None
                ),
                "removed_employee_ids": (
                    list(removed_employee_ids) if removed_employee_ids else None
                ),
            }
        )

    monkeypatch.setattr(common, "_dispatch_lifecycle_emails", fake_dispatch)
    return calls


def _patch_enqueue(monkeypatch):
    sent: list[dict] = []

    def fake_enqueue(recipient, subject, body, **kwargs):
        sent.append({"to": recipient, "subject": subject, "kwargs": kwargs})

    from app.core import email as email_mod

    monkeypatch.setattr(email_mod, "enqueue_email", fake_enqueue)
    return sent


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TestHRP245Template:
    def test_subject_matches_spec(self):
        subject, html = render_talent_market_removed_candidate_email(
            "Senior Backend Engineer", str(uuid.uuid4())
        )
        assert subject == "You are not considered more: Senior Backend Engineer"
        assert "Senior Backend Engineer" in html

    def test_title_is_escaped(self):
        _, html = render_talent_market_removed_candidate_email(
            "<script>alert(1)</script>", str(uuid.uuid4())
        )
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_no_open_card_button(self):
        # HRP-245 redo: a removed employee has no access to the card, so
        # the email must not link back to it.
        card_id = str(uuid.uuid4())
        _, html = render_talent_market_removed_candidate_email(
            "Senior Backend Engineer", card_id
        )
        assert "Open card" not in html
        assert f"/talent-market/{card_id}" not in html


# ---------------------------------------------------------------------------
# Service-level dispatch
# ---------------------------------------------------------------------------


class TestHRP245Dispatch:
    async def test_delete_from_published_dispatches_event(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Vacancy", card_type="vacancy"),
        )
        emp = await _make_employee(db, tenant, suffix="del")
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
        )
        await _force_published(db, card["id"])

        calls = _patch_dispatch(monkeypatch)
        await service.delete_candidate(db, tenant.id, card["id"], emp.id)

        events = [
            c for c in calls if c["event"] == "candidate_removed_from_published"
        ]
        assert len(events) == 1
        assert events[0]["removed_employee_ids"] == [emp.id]

    async def test_delete_from_draft_stays_silent(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Draft Vac", card_type="vacancy"),
        )
        emp = await _make_employee(db, tenant, suffix="draft")
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
        )

        calls = _patch_dispatch(monkeypatch)
        await service.delete_candidate(db, tenant.id, card["id"], emp.id)

        # delete_candidate is the only writer here; if it skips the
        # dispatcher (as the spec requires for draft) the list must stay
        # empty for the relevant event.
        assert [
            c for c in calls if c["event"] == "candidate_removed_from_published"
        ] == []


class TestHRP245EndToEndMail:
    async def test_delete_from_published_sends_real_email(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Senior Backend", card_type="vacancy"),
        )
        emp = await _make_employee(db, tenant, suffix="e2e")
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=emp.id)
        )
        await _force_published(db, card["id"])

        sent = _patch_enqueue(monkeypatch)
        await service.delete_candidate(db, tenant.id, card["id"], emp.id)

        # The dispatcher iterates removed_employee_ids and falls back to
        # ``db.get(Employee, ...)`` because the candidate row is already
        # gone — so the address still resolves to the dropped user.
        usr = await db.get(User, emp.user_id)
        assert usr is not None
        matched = [s for s in sent if s["to"] == usr.email]
        assert len(matched) == 1
        assert matched[0]["subject"] == "You are not considered more: Senior Backend"
