"""HRP-129: Talent Market auto-matching of Candidates.

Covers the rewritten matcher: candidates are auto-attached when the card
gets Required Competences and/or Required Specializations, with scoring
that follows the spec verbatim (average % across required competences,
latest Done assessment at-or-above the required skill level, work-history
sum for specialization tenure).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.modules.assessment.models import (
    Assessment,
    AssessmentCompetence,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee, WorkExperience
from app.modules.position.models import Position
from app.modules.talent_market import service
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCardSpecialization,
)
from app.modules.talent_market.schemas import (
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
    TalentCardUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------
# Fixtures helpers
# --------------------------------------------------------------------------


async def _make_user(db: AsyncSession, tenant_id: uuid.UUID, name: str = "U") -> User:
    u = User(
        tenant_id=tenant_id,
        email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name=name,
        last_name="Test",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    return u


async def _make_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    name: str = "Emp",
    hire_date: date | None = None,
) -> Employee:
    u = await _make_user(db, tenant_id, name=name)
    emp = Employee(
        tenant_id=tenant_id,
        user_id=u.id,
        hire_date=hire_date or date(2022, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _make_competence(
    db: AsyncSession, tenant_id: uuid.UUID, title: str
) -> Competence:
    g = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(g)
    await db.flush()
    c = Competence(tenant_id=tenant_id, group_id=g.id, title=title)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _make_skill_level(
    db: AsyncSession, tenant_id: uuid.UUID, *, sort_index: int, title: str = "L"
) -> SkillLevel:
    sl = SkillLevel(
        tenant_id=tenant_id,
        title=f"{title}-{uuid.uuid4().hex[:4]}",
        sort_index=sort_index,
    )
    db.add(sl)
    await db.commit()
    await db.refresh(sl)
    return sl


async def _ensure_done_status(db: AsyncSession) -> AssessmentStatus:
    row = (
        await db.execute(
            select(AssessmentStatus).where(AssessmentStatus.code == "done")
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = AssessmentStatus(code="done", title="Done", sequence=6)
    db.add(row)
    await db.flush()
    return row


async def _ensure_self_type(db: AsyncSession) -> AssessmentType:
    row = (
        await db.execute(select(AssessmentType).where(AssessmentType.code == "self"))
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = AssessmentType(code="self", title="Self")
    db.add(row)
    await db.flush()
    return row


async def _add_done_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    initiator_id: uuid.UUID,
    competence_id: uuid.UUID,
    skill_level_id: uuid.UUID,
    percent: int,
    *,
    finished_at: datetime | None = None,
) -> Assessment:
    a_type = await _ensure_self_type(db)
    a_status = await _ensure_done_status(db)
    a = Assessment(
        tenant_id=tenant_id,
        employee_id=employee_id,
        type_id=a_type.id,
        status_id=a_status.id,
        initiator_id=initiator_id,
        finished_at=finished_at or datetime.now(timezone.utc),
    )
    db.add(a)
    await db.flush()
    db.add(
        AssessmentCompetence(
            assessment_id=a.id,
            competence_id=competence_id,
            skill_level_id=skill_level_id,
        )
    )
    db.add(
        AssessmentResult(
            assessment_id=a.id,
            competence_id=competence_id,
            avg_score=percent / 25.0,
            percent=percent,
        )
    )
    await db.commit()
    return a


# --------------------------------------------------------------------------
# Test scenarios
# --------------------------------------------------------------------------


class TestAutoMatchCompetence:
    async def test_full_coverage_average_picks_candidate(
        self, db: AsyncSession, tenant, user
    ):
        """4 required competences, employee covers all four → matcher uses
        the spec example averages and clears the 70 threshold."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(
                title="V", card_type="vacancy", match_percent=70
            ),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1, title="Mid")
        comps = [
            await _make_competence(db, tenant.id, f"C{i}") for i in range(4)
        ]
        emp = await _make_employee(db, tenant.id, name="Full")
        for c, pct in zip(comps, [100, 80, 70, 30], strict=False):
            await _add_done_assessment(
                db, tenant.id, emp.id, user.id, c.id, sl.id, pct
            )

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                    for c in comps
                ]
            ),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].employee_id == emp.id
        assert rows[0].match_score == 70

    async def test_partial_coverage_zero_gap_pulls_average_down(
        self, db: AsyncSession, tenant, user
    ):
        """Spec example 2: 4 required, employee covers three (100/80/70),
        one untouched → average (100+80+70+0)/4 = 62.5 → rounded 63."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(
                title="V", card_type="vacancy", match_percent=50
            ),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        comps = [
            await _make_competence(db, tenant.id, f"C{i}") for i in range(4)
        ]
        emp = await _make_employee(db, tenant.id, name="Partial")
        for c, pct in zip(comps[:3], [100, 80, 70], strict=False):
            await _add_done_assessment(
                db, tenant.id, emp.id, user.id, c.id, sl.id, pct
            )

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                    for c in comps
                ]
            ),
        )

        row = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.match_score == 63

    async def test_no_coverage_excludes_candidate(
        self, db: AsyncSession, tenant, user
    ):
        """Spec example 3: not a single matching assessment → match% is
        not computed and the employee never lands in the auto-pool."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=50),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c = await _make_competence(db, tenant.id, "Lone")
        await _make_employee(db, tenant.id, name="Empty")

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)]
            ),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_lower_skill_level_assessment_ignored(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-90 mechanic: required Mid, assessment at Basic → ignored."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=50),
        )
        sl_basic = await _make_skill_level(db, tenant.id, sort_index=0, title="Basic")
        sl_mid = await _make_skill_level(db, tenant.id, sort_index=1, title="Mid")
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="LowLevel")
        # Employee has a Basic-level assessment — below the Required Mid.
        await _add_done_assessment(
            db, tenant.id, emp.id, user.id, c.id, sl_basic.id, 99
        )

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(
                        competence_id=c.id, skill_level_id=sl_mid.id
                    )
                ]
            ),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_higher_skill_level_assessment_counts(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-90 mechanic: required Mid, assessment at Advanced → still
        contributes to the average (≥ required floor)."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
        )
        sl_mid = await _make_skill_level(db, tenant.id, sort_index=1, title="Mid")
        sl_adv = await _make_skill_level(db, tenant.id, sort_index=2, title="Adv")
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="High")
        await _add_done_assessment(
            db, tenant.id, emp.id, user.id, c.id, sl_adv.id, 84
        )

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(
                        competence_id=c.id, skill_level_id=sl_mid.id
                    )
                ]
            ),
        )

        row = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.match_score == 84

    async def test_latest_assessment_wins_even_with_lower_score(
        self, db: AsyncSession, tenant, user
    ):
        """Per the spec: pick the latest Done assessment by finished_at,
        even if its percent is lower than older Done runs."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=50),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="Latest")
        # Older assessment scored higher.
        await _add_done_assessment(
            db,
            tenant.id,
            emp.id,
            user.id,
            c.id,
            sl.id,
            95,
            finished_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        # Newest scored lower — matcher must still pick the newer one.
        await _add_done_assessment(
            db,
            tenant.id,
            emp.id,
            user.id,
            c.id,
            sl.id,
            60,
            finished_at=datetime.now(timezone.utc),
        )

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                ]
            ),
        )

        row = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.match_score == 60

    async def test_threshold_rejects_below_match_percent(
        self, db: AsyncSession, tenant, user
    ):
        """Card threshold 80; candidate at 78 → not auto-attached."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="Just")
        await _add_done_assessment(db, tenant.id, emp.id, user.id, c.id, sl.id, 78)
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                ]
            ),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
        # Bumping the threshold down promotes the candidate.
        await service.update_card(
            db, tenant.id, card["id"], TalentCardUpdate(match_percent=70)
        )
        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].employee_id == emp.id
        assert rows[0].match_score == 78


class TestAutoMatchSpecialization:
    async def test_presence_only_match_qualifies(
        self, db: AsyncSession, tenant, user
    ):
        """Required Specialization without min_experience → any
        WorkExperience row with matching (spec_id, grade_id) qualifies."""
        spec = DictionaryItem(
            type="specialization", tenant_id=tenant.id, title="Spec"
        )
        grade = DictionaryItem(type="grade", tenant_id=tenant.id, title="G")
        db.add_all([spec, grade])
        await db.commit()
        position = Position(
            tenant_id=tenant.id,
            title=f"P-{uuid.uuid4().hex[:4]}",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(position)
        await db.flush()

        emp = await _make_employee(db, tenant.id, name="HasPos")
        db.add(
            WorkExperience(
                employee_id=emp.id,
                tenant_id=tenant.id,
                position_id=position.id,
                start_date=date.today() - timedelta(days=60),
            )
        )
        await db.commit()

        card = await service.create_card(
            db, tenant.id, user.id, TalentCardCreate(title="V", card_type="vacancy")
        )
        db.add(
            TalentCardSpecialization(
                card_id=card["id"],
                specialization_id=spec.id,
                grade_id=grade.id,
                min_experience_years=None,
            )
        )
        await db.commit()
        await service._auto_populate_candidates(db, tenant.id, card["id"])

        row = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.employee_id == emp.id

    async def test_years_sum_meets_min_experience(
        self, db: AsyncSession, tenant, user
    ):
        """Two WorkExperience spells on matching positions sum past the
        Required min_experience_years floor → qualifies."""
        spec = DictionaryItem(
            type="specialization", tenant_id=tenant.id, title="S2"
        )
        grade = DictionaryItem(type="grade", tenant_id=tenant.id, title="G2")
        db.add_all([spec, grade])
        await db.commit()
        position = Position(
            tenant_id=tenant.id,
            title=f"P-{uuid.uuid4().hex[:4]}",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(position)
        await db.flush()

        emp = await _make_employee(db, tenant.id, name="Tenured")
        today = date.today()
        # 2 years on the role, then a break, then 1.5 more = ~3.5y total.
        db.add(
            WorkExperience(
                employee_id=emp.id,
                tenant_id=tenant.id,
                position_id=position.id,
                start_date=today - timedelta(days=365 * 4),
                end_date=today - timedelta(days=365 * 2),
            )
        )
        db.add(
            WorkExperience(
                employee_id=emp.id,
                tenant_id=tenant.id,
                position_id=position.id,
                start_date=today - timedelta(days=int(365 * 1.5)),
            )
        )
        await db.commit()

        card = await service.create_card(
            db, tenant.id, user.id, TalentCardCreate(title="V", card_type="vacancy")
        )
        db.add(
            TalentCardSpecialization(
                card_id=card["id"],
                specialization_id=spec.id,
                grade_id=grade.id,
                min_experience_years=3,
            )
        )
        await db.commit()
        await service._auto_populate_candidates(db, tenant.id, card["id"])

        row = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.employee_id == emp.id

    async def test_years_sum_short_excludes_candidate(
        self, db: AsyncSession, tenant, user
    ):
        """One year on the role, requirement is 5 → no candidate."""
        spec = DictionaryItem(
            type="specialization", tenant_id=tenant.id, title="S3"
        )
        grade = DictionaryItem(type="grade", tenant_id=tenant.id, title="G3")
        db.add_all([spec, grade])
        await db.commit()
        position = Position(
            tenant_id=tenant.id,
            title=f"P-{uuid.uuid4().hex[:4]}",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(position)
        await db.flush()

        emp = await _make_employee(db, tenant.id, name="Junior")
        db.add(
            WorkExperience(
                employee_id=emp.id,
                tenant_id=tenant.id,
                position_id=position.id,
                start_date=date.today() - timedelta(days=365),
            )
        )
        await db.commit()

        card = await service.create_card(
            db, tenant.id, user.id, TalentCardCreate(title="V", card_type="vacancy")
        )
        db.add(
            TalentCardSpecialization(
                card_id=card["id"],
                specialization_id=spec.id,
                grade_id=grade.id,
                min_experience_years=5,
            )
        )
        await db.commit()
        await service._auto_populate_candidates(db, tenant.id, card["id"])

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


class TestAutoMatchRecompute:
    async def test_recompute_on_competence_update(
        self, db: AsyncSession, tenant, user
    ):
        """Changing Required Competences in-place re-runs the matcher."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=50),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c1 = await _make_competence(db, tenant.id, "C1")
        c2 = await _make_competence(db, tenant.id, "C2")
        emp_a = await _make_employee(db, tenant.id, name="A")
        emp_b = await _make_employee(db, tenant.id, name="B")
        await _add_done_assessment(
            db, tenant.id, emp_a.id, user.id, c1.id, sl.id, 90
        )
        await _add_done_assessment(
            db, tenant.id, emp_b.id, user.id, c2.id, sl.id, 90
        )

        # First the card only requires c1 — only A qualifies.
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c1.id, skill_level_id=sl.id)
                ]
            ),
        )
        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.employee_id for r in rows} == {emp_a.id}

        # Swap requirements to c2 — only B should remain in the auto-pool.
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c2.id, skill_level_id=sl.id)
                ]
            ),
        )
        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.employee_id for r in rows} == {emp_b.id}

    async def test_recompute_on_threshold_lowered(
        self, db: AsyncSession, tenant, user
    ):
        """Lowering the card match% promotes a borderline employee from
        not-a-candidate to nominated."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=90),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="Border")
        await _add_done_assessment(
            db, tenant.id, emp.id, user.id, c.id, sl.id, 84
        )
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                ]
            ),
        )
        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

        await service.update_card(
            db,
            tenant.id,
            card["id"],
            TalentCardUpdate(match_percent=80),
        )
        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(
                        TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].employee_id == emp.id
        assert rows[0].match_score == 84

    async def test_detail_exposes_basis_and_score(
        self, db: AsyncSession, tenant, user
    ):
        """`GET /talent-market/{id}` includes `basis` per candidate row."""
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="V", card_type="vacancy", match_percent=50),
        )
        sl = await _make_skill_level(db, tenant.id, sort_index=1)
        c = await _make_competence(db, tenant.id, "C")
        emp = await _make_employee(db, tenant.id, name="Score")
        await _add_done_assessment(
            db, tenant.id, emp.id, user.id, c.id, sl.id, 84
        )
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c.id, skill_level_id=sl.id)
                ]
            ),
        )

        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert len(detail["candidates"]) == 1
        assert detail["candidates"][0]["match_score"] == 84
        assert detail["candidates"][0]["basis"] == "competence"
