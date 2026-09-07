"""HRP-213: employee reaction on a Published Talent Market card.

The "React" action is gated to candidate rows whose ``status`` is in
``{matched, not_matched}``. Already-reacted rows are rejected; appointed
candidates can't react. The card-list response surfaces
``reacted_by_me`` so the preview tile can render a chip.
"""

from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.modules.auth.models import Role, User, user_roles
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate, TalentCardCompetence
from app.modules.talent_market.schemas import (
    CandidateBulkAdd,
    SearchRequest,
    TalentCardCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import (
    _add_done_assessment,
    _make_competence,
    _make_employee,
    _make_skill_level,
)


async def _make_card_published(db: AsyncSession, tenant_id, author_id) -> dict:
    card_dict = await service.create_card(
        db,
        tenant_id,
        author_id,
        TalentCardCreate(title="TM-react", card_type="vacancy"),
    )
    from app.modules.talent_market.models import TalentCard

    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None
    card.status = "published"
    await db.commit()
    return card_dict


async def _employee_user(
    db: AsyncSession, tenant_id, emp, *, role_code: str = "employee"
) -> User:
    """Eager-load the user.roles so React's role check has the right shape."""
    role = (
        await db.execute(select(Role).where(Role.code == role_code))
    ).scalar_one_or_none()
    if role is None:
        role = Role(name=role_code.title(), code=role_code, is_system=True)
        db.add(role)
        await db.flush()
    await db.execute(user_roles.insert().values(user_id=emp.user_id, role_id=role.id))
    await db.commit()
    from sqlalchemy.orm import selectinload

    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == emp.user_id)
        )
    ).scalar_one()


async def test_react_stamps_response_at_and_marks_reacted_by_me(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Reactor")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    out = await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    assert out["response_at"] is not None
    assert out["is_me"] is True

    # Card list surfaces reacted_by_me for the reacting viewer.
    cards, _ = await service.search_cards(
        db,
        tenant.id,
        SearchRequest(),
        scope=None,
        viewer_employee_id=emp.id,
    )
    matching = [c for c in cards if c["id"] == card_dict["id"]]
    assert matching and matching[0]["reacted_by_me"] is True


async def test_react_twice_is_rejected(db: AsyncSession, tenant, user) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="DoubleReact")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    assert ex.value.status_code == 409


async def test_react_rejects_non_candidate(db: AsyncSession, tenant, user) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Stranger")
    emp_user = await _employee_user(db, tenant.id, emp)
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    assert ex.value.status_code == 404


async def test_react_rejects_appointed_candidate(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Appointed")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one()
    row.status = "appointed"
    await db.commit()
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    assert ex.value.status_code == 409


async def test_candidates_ranking_experience_before_reaction(
    db: AsyncSession, tenant, user
) -> None:
    """HRP-213 Task 2 redo: experience is part of "all else being equal".

    Qualifying experience > longer experience > reaction; the reaction
    only breaks ties between rows equal on both percent and experience.
    """
    from datetime import datetime, timezone

    from app.modules.talent_market.common import _card_to_detail
    from app.modules.talent_market.models import TalentCard
    from sqlalchemy.orm import selectinload

    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp_qualifies = await _make_employee(db, tenant.id, name="Qualif")
    emp_longer = await _make_employee(db, tenant.id, name="Longer")
    emp_reacted = await _make_employee(db, tenant.id, name="ZReactor")
    emp_plain = await _make_employee(db, tenant.id, name="ANoexp")
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(
            employee_ids=[
                emp_qualifies.id,
                emp_longer.id,
                emp_reacted.id,
                emp_plain.id,
            ]
        ),
    )
    reacted_row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp_reacted.id,
            )
        )
    ).scalar_one()
    reacted_row.response_at = datetime.now(timezone.utc)
    await db.commit()

    card = (
        await db.execute(
            select(TalentCard)
            .options(
                selectinload(TalentCard.specializations),
                selectinload(TalentCard.competences),
                selectinload(TalentCard.requirements),
                selectinload(TalentCard.candidates),
            )
            .where(TalentCard.id == card_dict["id"])
        )
    ).scalar_one()
    # Equal comp percent everywhere (None); only the experience axis and
    # the reaction differ.
    breakdown = {
        emp_qualifies.id: {"exp_qualifies": True, "exp_months": None},
        emp_longer.id: {"exp_qualifies": False, "exp_months": 14},
        emp_reacted.id: {},
        emp_plain.id: {},
    }
    detail = _card_to_detail(card, breakdown_by_emp=breakdown)
    ordered = [c["employee_id"] for c in detail["candidates"]]
    assert ordered == [
        emp_qualifies.id,  # qualifying experience wins outright
        emp_longer.id,  # longer experience beats the reaction
        emp_reacted.id,  # reaction breaks the tie with the equal row...
        emp_plain.id,  # ...despite the alphabetically earlier name
    ]


async def test_react_rejected_on_unpublished_card(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="Draft", card_type="vacancy"),
    )
    emp = await _make_employee(db, tenant.id, name="Draftee")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    assert ex.value.status_code == 409


# ---------------------------------------------------------------------------
# HRP-714 — the soft auto-reply on a below-the-bar reaction, and the CTA
# ---------------------------------------------------------------------------


async def _seed_gap_templates(db: AsyncSession) -> None:
    """The rows the core migration ships; the unit suite skips migrations."""
    from app.modules.notification.models import NotificationTemplate

    for code, subject, body in (
        (
            "talent_market.reaction_gap",
            "About your response to {{ card_title }}",
            "<p>Some skills in your profile differ from what this "
            "opportunity requires.</p>"
            '{% if link_url %}<p><a href="{{ link_url }}">Open</a></p>'
            "{% endif %}",
        ),
        (
            "talent_market.plan_requested",
            "{{ employee_name }} asked for a plan",
            "<p>{{ employee_name }} asked for a development plan for "
            "{{ card_title }}.</p>",
        ),
    ):
        # (code, locale) is unique and the session is shared across the
        # tests in this file — insert once, like the migration's upsert.
        # The rows outlive each test: they are inserted on the first call
        # and reused by every later one in this process.
        existing = (
            await db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.code == code,
                    NotificationTemplate.locale == "en",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            NotificationTemplate(
                code=code,
                locale="en",
                subject_template=subject,
                body_template=body,
                notification_type="email",
            )
        )
    await db.commit()


def _capture_letters(monkeypatch) -> list[tuple[str, str, str | None]]:
    """Every letter ``send_notification`` hands to the mailer."""
    sent: list[tuple[str, str, str | None]] = []

    def fake_enqueue(recipient, subject, body, *, tenant_id=None, template_code=None):
        sent.append((recipient, subject, template_code))

    from app.modules.notification import service as notif_service

    monkeypatch.setattr(notif_service, "enqueue_email", fake_enqueue)
    return sent


async def _notifications_for(db: AsyncSession, recipient_id):
    """(template code, context) of every in-app notification for a user."""
    from app.modules.notification.models import Notification, NotificationTemplate

    rows = (
        await db.execute(
            select(NotificationTemplate.code, Notification.context)
            .join(Notification, Notification.template_id == NotificationTemplate.id)
            .where(Notification.recipient_id == recipient_id)
        )
    ).all()
    return [(code, ctx) for code, ctx in rows]


async def _candidate_row(db: AsyncSession, card_id, employee_id) -> TalentCandidate:
    return (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_id,
                TalentCandidate.employee_id == employee_id,
            )
        )
    ).scalar_one()


async def _reacting_candidate(
    db: AsyncSession, tenant_id, author_id, *, card_type: str = "vacancy"
):
    """A published card of ``card_type`` requiring one competence, with one
    employee on it who was never assessed on it — below the bar on the card
    page's own live verdict (HRP-734), whatever the stored score says."""
    from app.modules.talent_market.models import TalentCard

    card_dict = await service.create_card(
        db,
        tenant_id,
        author_id,
        TalentCardCreate(title="Senior Account Executive", card_type=card_type),
    )
    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None
    card.status = "published"
    card.match_percent = 80
    comp = await _make_competence(db, tenant_id, "Negotiation")
    level = await _make_skill_level(db, tenant_id, sort_index=1)
    db.add(
        TalentCardCompetence(
            card_id=card.id,
            competence_id=comp.id,
            skill_level_id=level.id,
            match_percent=80,
        )
    )
    await db.commit()
    emp = await _make_employee(db, tenant_id, name="Probelov")
    emp_user = await _employee_user(db, tenant_id, emp)
    await service.add_candidates_bulk(
        db, tenant_id, card_dict["id"], CandidateBulkAdd(employee_ids=[emp.id])
    )
    return card_dict, emp, emp_user


async def _assess_at(
    db: AsyncSession, tenant_id, card_id, employee_id, initiator_id, percent: int
) -> None:
    """A Done assessment at ``percent`` on every competence the card requires."""
    links = (
        (
            await db.execute(
                select(TalentCardCompetence).where(
                    TalentCardCompetence.card_id == card_id
                )
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        await _add_done_assessment(
            db,
            tenant_id,
            employee_id,
            initiator_id,
            link.competence_id,
            link.skill_level_id,
            percent,
        )


class TestReactionGapAutoReply:
    """HRP-714: silence read as a rejection nobody sent."""

    async def test_below_the_bar_gets_the_soft_reply(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        await _seed_gap_templates(db)
        letters = _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        # A manual pick has no score at all — the matcher never ranked
        # them, which is the strongest form of "below the bar".
        row = await _candidate_row(db, card_dict["id"], emp.id)
        assert row.match_score is None

        out = await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        # The reaction still stands: that is the whole promise of the letter.
        assert out["response_at"] is not None

        mine = await _notifications_for(db, emp_user.id)
        assert [code for code, _ in mine] == ["talent_market.reaction_gap"]
        ctx = mine[0][1]
        assert ctx["link"] == f"/talent-market/{card_dict['id']}"
        assert ctx["card_title"] == "Senior Account Executive"
        assert ctx["gaps"] == ["Negotiation"]
        # HRP-714 review: the bell renders ``title or message`` as text.
        # Both were the card title, so the letter the ticket is about was
        # readable nowhere — email is dropped outright for demo tenants,
        # which is the very setting this was built for.
        assert ctx["title"] != ctx["card_title"]
        assert ctx["title"] == "About your response to Senior Account Executive"
        assert "differ from what this opportunity requires" in ctx["message"]
        # The click-through is the row itself, so it stays out of the text.
        assert "Open" not in ctx["message"]
        assert "<" not in ctx["message"]
        assert [
            code for _, _, code in letters if code == "talent_market.reaction_gap"
        ] == ["talent_market.reaction_gap"]

    async def test_the_live_verdict_wins_over_a_stale_stored_score(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """Stored below, live above: the card says "Matched", so no reply.

        ``match_score`` is refreshed only by a pool recompute, while the
        row on the card page is judged live on every read (HRP-734).
        Answering off the stored number told people who had since closed
        the gap that they still had one.
        """
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await _assess_at(db, tenant.id, card_dict["id"], emp.id, user.id, 90)
        row = await _candidate_row(db, card_dict["id"], emp.id)
        assert row.match_score is None  # the stored verdict still says "below"

        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        assert await _notifications_for(db, emp_user.id) == []

    async def test_a_stale_stored_pass_still_gets_the_reply_with_the_gap(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """Stored above, live below: the reply goes out and names the gap."""
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        row = await _candidate_row(db, card_dict["id"], emp.id)
        row.match_score = 95
        await db.commit()

        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        mine = await _notifications_for(db, emp_user.id)
        assert [code for code, _ in mine] == ["talent_market.reaction_gap"]
        assert mine[0][1]["gaps"] == ["Negotiation"]

    async def test_a_talent_card_never_auto_replies(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """A reserve pool for a role that does not exist yet has no bar."""
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(
            db, tenant.id, user.id, card_type="talent"
        )
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        assert await _notifications_for(db, emp_user.id) == []


class TestRequestDevelopmentPlan:
    """HRP-714: the CTA. Employees cannot make their own plan, so they ask."""

    async def _with_manager(self, db: AsyncSession, tenant_id, emp):
        from app.modules.company.models import Division

        manager = await _make_employee(db, tenant_id, name="Manager")
        division = Division(tenant_id=tenant_id, name="Go-to-Market")
        db.add(division)
        await db.flush()
        division.manager_id = manager.id
        emp.division_id = division.id
        await db.commit()
        return manager

    async def test_notifies_the_manager_with_a_deep_link(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        await _seed_gap_templates(db)
        letters = _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        manager = await self._with_manager(db, tenant.id, emp)
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)

        out = await service.request_development_plan(
            db, tenant.id, card_dict["id"], emp_user
        )
        assert out["is_me"] is True

        row = await _candidate_row(db, card_dict["id"], emp.id)
        theirs = await _notifications_for(db, manager.user_id)
        assert [code for code, _ in theirs] == ["talent_market.plan_requested"]
        # The manager lands on the candidate whose drawer builds the plan.
        assert theirs[0][1]["link"] == (
            f"/talent-market/{card_dict['id']}?candidate={row.id}"
        )
        # Same fix on the manager's side: the entry says what was asked.
        assert "asked for a plan" in theirs[0][1]["title"]
        assert "asked for a development plan for" in theirs[0][1]["message"]
        assert [
            code for _, _, code in letters if code == "talent_market.plan_requested"
        ] == ["talent_market.plan_requested"]

    async def test_refuses_before_a_reaction(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await self._with_manager(db, tenant.id, emp)
        with pytest.raises(HTTPException) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409

    async def test_refuses_when_a_plan_already_exists(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        from app.modules.assessment.models import PDP

        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await self._with_manager(db, tenant.id, emp)
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)

        plan = PDP(
            tenant_id=tenant.id,
            title="Close the gaps",
            employee_id=emp.id,
            author_id=user.id,
        )
        db.add(plan)
        await db.flush()
        row = await _candidate_row(db, card_dict["id"], emp.id)
        row.pdp_id = plan.id
        await db.commit()

        with pytest.raises(HTTPException) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409

    async def test_refuses_when_nobody_manages_the_division(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """No manager is a dead end for the employee, so say so."""
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        with pytest.raises(HTTPException) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409

    async def test_refuses_when_the_live_breakdown_has_no_gap(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """Nothing to plan for: the card page hides the CTA, the server agrees."""
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await self._with_manager(db, tenant.id, emp)
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        await _assess_at(db, tenant.id, card_dict["id"], emp.id, user.id, 90)

        with pytest.raises(AppError) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409
        assert ex.value.code == "tm_plan_request_no_gap"

    async def test_refuses_an_appointed_candidate(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """An appointed row is terminal — there is nothing left to ask for."""
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        await self._with_manager(db, tenant.id, emp)
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        row = await _candidate_row(db, card_dict["id"], emp.id)
        row.status = "appointed"
        await db.commit()

        with pytest.raises(AppError) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409
        assert ex.value.code == "tm_plan_request_no_gap"


async def test_the_plan_request_url_is_the_one_the_card_page_calls() -> None:
    import re
    from pathlib import Path

    from app.main import app

    page = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "app"
        / "(dashboard)"
        / "talent-market"
        / "[id]"
        / "page.tsx"
    )
    if not page.exists():
        pytest.skip("frontend tree not present")

    def collapse(path: str) -> str:
        return re.sub(r"\$?\{[^}]*\}", "{}", path).rstrip("/")

    referenced = {
        "/api" + collapse(u)
        for u in re.findall(
            r"/talent-market/\$\{[^}]+\}/request-development-plan",
            page.read_text(encoding="utf-8"),
        )
    }
    mounted = {
        collapse(getattr(r, "path", ""))
        for r in app.routes
        if "request-development-plan" in getattr(r, "path", "")
    }
    assert referenced, "the card page stopped calling the plan-request URL"
    assert referenced <= mounted, referenced - mounted


class TestReactionGapReviewFollowUps:
    """HRP-714 review follow-ups."""

    async def test_a_failing_notification_does_not_lose_the_reaction(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """The reaction is the user's act; the reply is best-effort.

        Whatever the mailer or the template lookup does, the row keeps
        ``response_at`` — losing it would silently drop an application.
        """
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)

        from app.modules.notification import service as notif_service

        async def boom(*args, **kwargs):
            raise RuntimeError("notification backend down")

        monkeypatch.setattr(notif_service, "send_notification", boom)

        out = await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        assert out["response_at"] is not None
        row = await _candidate_row(db, card_dict["id"], emp.id)
        assert row.response_at is not None
        assert await _notifications_for(db, emp_user.id) == []

    async def test_a_division_head_is_told_they_manage_themselves(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """ "Nobody manages this division" is the wrong sentence for them."""
        from app.modules.company.models import Division

        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        division = Division(tenant_id=tenant.id, name="Go-to-Market")
        db.add(division)
        await db.flush()
        division.manager_id = emp.id  # they run it themselves
        emp.division_id = division.id
        await db.commit()
        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)

        with pytest.raises(HTTPException) as ex:
            await service.request_development_plan(
                db, tenant.id, card_dict["id"], emp_user
            )
        assert ex.value.status_code == 409
        assert ex.value.code == "tm_self_managed_no_request"

    async def test_an_employee_without_an_email_still_gets_the_bell(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """The in-app copy must not hang off having an address.

        ``send_notification`` gates the letter on its own preference
        check; returning early on a missing address dropped the bell
        entry too — the only copy a demo tenant ever sees.
        """
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)
        emp_user.email = ""
        await db.commit()

        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
        mine = await _notifications_for(db, emp_user.id)
        assert [code for code, _ in mine] == ["talent_market.reaction_gap"]

    async def test_the_reply_text_reaches_a_surface_that_renders_it(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """The letter's words must land in a key the UI actually shows.

        Live check on the demo stand: both the bell dropdown and the
        notifications list render ``context.title or context.message``,
        so with a title set the body was displayed nowhere — and demo
        tenants get no email to read it in. ``description`` is the one
        key the list renders under the title.
        """
        await _seed_gap_templates(db)
        _capture_letters(monkeypatch)
        card_dict, emp, emp_user = await _reacting_candidate(db, tenant.id, user.id)

        await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)

        ctx = (await _notifications_for(db, emp_user.id))[0][1]
        assert ctx["description"] == ctx["message"]
        assert "differ from what this opportunity requires" in ctx["description"]

    def test_tag_stripping_does_not_leave_a_space_before_punctuation(self) -> None:
        """``<b>x</b>.`` used to render as ``x .`` in the bell."""
        from app.modules.notification.models import NotificationTemplate
        from app.modules.notification.service import render_db_template_preview

        template = NotificationTemplate(
            code="t",
            locale="en",
            subject_template="s",
            body_template="<p>asked about <b>{{ card_title }}</b>, twice</p>",
            notification_type="email",
        )
        _, message = render_db_template_preview(template, {"card_title": "SAE"})
        assert message == "asked about SAE, twice"
