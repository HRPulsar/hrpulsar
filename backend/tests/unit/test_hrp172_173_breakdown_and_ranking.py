"""HRP-172 + HRP-173: candidate match breakdown endpoint and the new
ranking rules in the Candidates block + Add / Change picker.
"""

from __future__ import annotations

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.talent_market import service
from app.modules.talent_market.schemas import (
    CandidateAdd,
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup_card_with_two_comps(
    db: AsyncSession, tenant, user, *, match_percent: int = 60
):
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(
            title="HRP-173 ranking",
            card_type="vacancy",
            match_percent=match_percent,
        ),
    )
    group = CompetenceGroup(tenant_id=tenant.id, title="G")
    db.add(group)
    await db.flush()
    sl = SkillLevel(tenant_id=tenant.id, title="L", sort_index=0)
    db.add(sl)
    await db.flush()
    c_a = Competence(tenant_id=tenant.id, group_id=group.id, title="A")
    c_b = Competence(tenant_id=tenant.id, group_id=group.id, title="B")
    db.add_all([c_a, c_b])
    await db.commit()
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[
                RequiredCompetenceItem(competence_id=c_a.id, skill_level_id=sl.id),
                RequiredCompetenceItem(competence_id=c_b.id, skill_level_id=sl.id),
            ]
        ),
    )
    return card_dict, [c_a, c_b], sl


class TestCandidateBreakdownEndpointHRP172:
    """Per-candidate breakdown endpoint feeding the Sheet drawer.

    Wires a Required Competences block + employee with one Done assessment
    on one of the comps. The endpoint must return both comp rows — the
    assessed one with actual_percent populated, the un-assessed one with
    actual_percent=None and qualifies=False. card_match_percent is passed
    through so the drawer can render the threshold next to each row.
    """

    async def test_breakdown_returns_per_comp_rows(
        self, db: AsyncSession, tenant, user, employee
    ):
        # The synthetic assessment helper from the HRP-129 test file uses the
        # AssessmentResult.percent fallback when there's no scale — perfect
        # for forcing a known percent without spinning up indicators.
        from tests.unit.test_talent_market_service import TestComputeMatchHRP129

        card_dict, (comp_a, comp_b), sl = await _setup_card_with_two_comps(
            db, tenant, user, match_percent=60
        )
        helper = TestComputeMatchHRP129()
        await helper._add_done_assessment(db, tenant, employee, comp_a, sl, 90)

        bd = await service.get_candidate_breakdown(
            db, tenant.id, card_dict["id"], employee.id
        )
        assert bd["employee_id"] == employee.id
        assert bd["card_match_percent"] == 60
        rows = {r["competence_id"]: r for r in bd["competences"]}
        assert rows[comp_a.id]["actual_percent"] == 90
        assert rows[comp_a.id]["qualifies"] is True
        assert rows[comp_b.id]["actual_percent"] is None
        assert rows[comp_b.id]["qualifies"] is False
        # No Required Specs on this card → empty list, not absent.
        assert bd["specializations"] == []


class TestCandidatesBreakdownInCardDetailHRP173:
    """get_card_detail enriches each candidate with comp_match / etc."""

    async def test_card_detail_carries_comp_match_for_candidate(
        self, db: AsyncSession, tenant, user, employee
    ):
        from tests.unit.test_talent_market_service import TestComputeMatchHRP129

        card_dict, (comp_a, comp_b), sl = await _setup_card_with_two_comps(
            db, tenant, user, match_percent=60
        )
        helper = TestComputeMatchHRP129()
        await helper._add_done_assessment(db, tenant, employee, comp_a, sl, 90)
        # Attach manually so the candidate row exists regardless of the
        # auto-pool gate (90 / 2 = 45 < 60 threshold, so auto-pool would
        # skip this employee). HRP-173 still wants the per-axis breakdown
        # on manual rows so recruiters can see why they don't qualify.
        await service.add_candidate(
            db, tenant.id, card_dict["id"], CandidateAdd(employee_id=employee.id)
        )

        detail = await service.get_card_detail(db, tenant.id, card_dict["id"])
        assert len(detail["candidates"]) == 1
        cand = detail["candidates"][0]
        assert cand["comp_match"] == 45  # (90 + 0) / 2
        assert cand["comp_qualifies"] is False
        assert cand["has_comp_requirement"] is True
        assert cand["has_spec_requirement"] is False


class TestPoolRankingHRP173:
    """Pool sort: qualifying first, then comp-only, then exp-only, then rest.

    With a comp-only card (no specs) the spec-only buckets collapse to a
    single 0/3 split — qualifying employees first by comp_match desc, then
    everyone else by the same key. Adds three employees with different
    competence percents to assert the order.
    """

    async def test_pool_orders_qualifying_first(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.auth.models import User
        from app.modules.company.models import Tenant
        from app.modules.employee.models import Employee

        from tests.unit.test_talent_market_service import TestComputeMatchHRP129

        # Use the existing tenant; spin up three employees with distinct names
        # so the secondary alphabetical sort is deterministic.
        async def _emp(name: str) -> Employee:
            import uuid as _uuid

            from app.core.security import hash_password

            u = User(
                tenant_id=tenant.id,
                email=f"{name.lower()}-{_uuid.uuid4().hex[:6]}@example.com",
                password_hash=hash_password("x"),
                first_name=name,
                last_name="Doe",
            )
            db.add(u)
            await db.flush()
            from datetime import date as _date

            e = Employee(
                tenant_id=tenant.id,
                user_id=u.id,
                hire_date=_date(2024, 1, 15),
            )
            db.add(e)
            await db.commit()
            await db.refresh(e)
            return e

        # tenant + Tenant import retained for namespace stability across
        # fixture reshuffles; not directly used inline.
        _ = Tenant
        e_alice = await _emp("Alice")
        e_bob = await _emp("Bob")
        e_carl = await _emp("Carl")

        card_dict, (comp_a, comp_b), sl = await _setup_card_with_two_comps(
            db, tenant, user, match_percent=50
        )
        helper = TestComputeMatchHRP129()
        # Alice: 90 on A, 90 on B → 90 (qualifies)
        # Bob: 80 on A only → 40 (does not qualify)
        # Carl: 100 on A, 80 on B → 90 (qualifies, same comp_match as Alice
        # → secondary alphabetical Alice first)
        await helper._add_done_assessment(db, tenant, e_alice, comp_a, sl, 90)
        await helper._add_done_assessment(db, tenant, e_alice, comp_b, sl, 90)
        await helper._add_done_assessment(db, tenant, e_bob, comp_a, sl, 80)
        await helper._add_done_assessment(db, tenant, e_carl, comp_a, sl, 100)
        await helper._add_done_assessment(db, tenant, e_carl, comp_b, sl, 80)

        pool = await service.list_candidate_pool(
            db, tenant.id, card_dict["id"], include_attached=True
        )
        names_in_order = [p["name"] for p in pool if p["name"] in {
            "Alice Doe", "Bob Doe", "Carl Doe"
        }]
        # Qualifying first (Alice + Carl tie at 90 → Alice alphabetically),
        # then Bob in the non-qualifying bucket.
        assert names_in_order[:2] == ["Alice Doe", "Carl Doe"]
        assert names_in_order[-1] == "Bob Doe"
