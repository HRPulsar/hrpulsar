"""HRP-129 REDO regression: matcher projects assessment results to the
required level using the per-level breakdown.

The reporter's 2026-05-27 example (TM 1c92efaa, employee 6a3b4dd2): a Done
assessment that ran at level Adv with breakdown {Basic: 100, Int: 100,
Adv: 33} on a competence required at level Int should contribute
(100 + 100) / 2 = 100% to the matcher, not the stored
``AssessmentResult.percent`` (78% — the Adv-level average). The old
matcher used ``AssessmentResult.percent`` directly, so the per-row Match
read 65% where the spec required 72%.

This file sets up a real Assessment with AssessmentParticipant /
AssessmentCompetence / Indicator / AssessmentAnswer rows so
``_compute_per_level_breakdowns_batch`` returns a non-empty breakdown,
then drives the talent-market matcher and asserts the projected percent
matches the Employee Competences-tab formula.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    SkillLevel,
)
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCard, TalentCardCompetence
from app.modules.talent_market.schemas import (
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_scale(db: AsyncSession, tenant) -> tuple[AnswerScale, AnswerOption]:
    """Seed a 0..4 scale with one usable option whose weight equals max.

    Picking weight = max_weight means every indicator answered with this
    option contributes 100% — so breakdown[level].percent = 100 for any
    level we answer fully and 0 (or missing) otherwise. That gives clean
    integer expectations in the assertions without manual rounding.
    """
    scale = AnswerScale(tenant_id=tenant.id, title="HRP-129 scale")
    db.add(scale)
    await db.flush()
    high = AnswerOption(scale_id=scale.id, title="Yes", code="yes", weight=4, sort_index=0)
    low = AnswerOption(scale_id=scale.id, title="No", code="no", weight=0, sort_index=1)
    db.add_all([high, low])
    await db.commit()
    return scale, high


async def _done_status(db: AsyncSession) -> AssessmentStatus:
    row = (
        await db.execute(select(AssessmentStatus).where(AssessmentStatus.code == "done"))
    ).scalar_one_or_none()
    if row is None:
        row = AssessmentStatus(code="done", title="Done", sequence=6)
        db.add(row)
        await db.commit()
    return row


async def _self_type(db: AsyncSession) -> AssessmentType:
    row = (
        await db.execute(select(AssessmentType).where(AssessmentType.code == "self"))
    ).scalar_one_or_none()
    if row is None:
        row = AssessmentType(code="self", title="Self")
        db.add(row)
        await db.commit()
    return row


async def _seed_assessment_with_breakdown(
    db: AsyncSession,
    *,
    tenant,
    employee,
    scale: AnswerScale,
    answer_high: AnswerOption,
    target_level: SkillLevel,
    competence: Competence,
    answered_levels: list[SkillLevel],
    finished_at: datetime | None = None,
) -> Assessment:
    """Spin up a Done assessment with one indicator per level on `competence`.

    `answered_levels` is the subset of levels for which the participant
    chose the high-weight option (= 100%). Unanswered levels still have an
    indicator, but get the low-weight option (= 0%) — that way the
    breakdown surfaces a row for every level (cascade-trimmed at
    target_level), with percent 100 for answered levels and 0 for the rest.
    """
    done = await _done_status(db)
    self_type = await _self_type(db)

    a = Assessment(
        tenant_id=tenant.id,
        employee_id=employee.id,
        type_id=self_type.id,
        status_id=done.id,
        initiator_id=employee.user_id,
        scale_id=scale.id,
        finished_at=finished_at or datetime.now(timezone.utc),
    )
    db.add(a)
    await db.flush()

    ac = AssessmentCompetence(
        assessment_id=a.id,
        competence_id=competence.id,
        skill_level_id=target_level.id,
    )
    db.add(ac)

    participant = AssessmentParticipant(
        assessment_id=a.id,
        user_id=employee.user_id,
        role="self",
    )
    db.add(participant)
    await db.flush()

    answered_ids = {sl.id for sl in answered_levels}
    # All levels up to the target's sort_index get an indicator; cascade
    # trimming in _compute_breakdown_for_assessment will keep all of them.
    low_option = (
        await db.execute(
            select(AnswerOption).where(
                AnswerOption.scale_id == scale.id, AnswerOption.weight == 0
            )
        )
    ).scalar_one()

    levels_q = await db.execute(
        select(SkillLevel).where(SkillLevel.tenant_id == tenant.id)
    )
    all_levels = list(levels_q.scalars().all())
    target_sort = target_level.sort_index
    relevant_levels = [lv for lv in all_levels if lv.sort_index <= target_sort]

    for level in relevant_levels:
        ind = Indicator(
            tenant_id=tenant.id,
            competence_id=competence.id,
            skill_level_id=level.id,
            title=f"ind-{competence.title}-{level.title}",
            weight=1,
        )
        db.add(ind)
        await db.flush()
        chosen = answer_high if level.id in answered_ids else low_option
        db.add(
            AssessmentAnswer(
                assessment_id=a.id,
                participant_id=participant.id,
                indicator_id=ind.id,
                answer_option_id=chosen.id,
            )
        )

    db.add(
        AssessmentResult(
            assessment_id=a.id,
            competence_id=competence.id,
            avg_score=2.0,
            # Intentionally store a misleading value to prove the matcher
            # does NOT read AssessmentResult.percent when breakdowns are
            # available — it must use the projected average instead.
            percent=999,
        )
    )
    await db.commit()
    return a


class TestHrp129LevelProjection:
    """REDO regression: assessment at Adv level, required at Int → project."""

    async def _setup_levels(
        self, db: AsyncSession, tenant
    ) -> tuple[SkillLevel, SkillLevel, SkillLevel]:
        basic = SkillLevel(tenant_id=tenant.id, title="Basic", sort_index=0)
        inter = SkillLevel(tenant_id=tenant.id, title="Int", sort_index=1)
        adv = SkillLevel(tenant_id=tenant.id, title="Adv", sort_index=2)
        db.add_all([basic, inter, adv])
        await db.flush()
        return basic, inter, adv

    async def _setup_card_with_three_comps(
        self,
        db: AsyncSession,
        tenant,
        user,
        *,
        req_levels: list[SkillLevel],
    ) -> tuple[TalentCard, list[Competence]]:
        card_dict = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(
                title="HRP-129 REDO",
                card_type="vacancy",
                match_percent=70,
            ),
        )
        card = await db.get(TalentCard, card_dict["id"])
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comps: list[Competence] = []
        for i, level in enumerate(req_levels):
            c = Competence(
                tenant_id=tenant.id, group_id=group.id, title=f"C{i}"
            )
            db.add(c)
            await db.flush()
            comps.append(c)
            db.add(
                TalentCardCompetence(
                    card_id=card.id,
                    competence_id=c.id,
                    skill_level_id=level.id,
                )
            )
        await db.commit()
        return card, comps

    async def test_higher_level_assessment_projects_to_required(
        self, db: AsyncSession, tenant, user, employee
    ):
        """The QA scenario: Required Int, assessment at Adv. The matcher
        averages only Basic + Int breakdown rows — Adv is dropped.

        Three competences:
          * C0 Int required, Adv assessment answered at {Basic, Int}
            → projected 100% (Adv row in breakdown not included).
          * C1 Int required, Adv assessment answered at {Basic, Int}
            → projected 100%.
          * C2 Basic required, Adv assessment answered at {Basic}
            → projected 100%.

        Card-level Match% = 70 → all three employees clear the threshold,
        average score = 100. Without level projection, the matcher would
        instead read AssessmentResult.percent (deliberately seeded as 999)
        and the score would be nonsensical — proving the projection path
        is the one actually taken.
        """
        basic, inter, adv = await self._setup_levels(db, tenant)
        scale, high = await _seed_scale(db, tenant)
        card, comps = await self._setup_card_with_three_comps(
            db, tenant, user, req_levels=[inter, inter, basic]
        )
        # Re-fetch the card so its match_percent stays fresh after the
        # auto-pool recompute committed in _setup_card_with_three_comps.
        card = await db.get(TalentCard, card.id)
        for c, answered in zip(
            comps,
            [[basic, inter], [basic, inter], [basic]],
            strict=False,
        ):
            await _seed_assessment_with_breakdown(
                db,
                tenant=tenant,
                employee=employee,
                scale=scale,
                answer_high=high,
                target_level=adv,
                competence=c,
                answered_levels=answered,
            )

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert basis == "competence"
        assert score == 100

    async def test_mixed_levels_match_spec_table(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Replays the reporter's exact spec table (HRP-129 REDO 2026-05-27).

        Required:
          * C0 Int., assessment Adv breakdown {Basic: 100, Int: 33}
              → avg(100, 33) = 67
          * C1 Int., assessment Adv breakdown {Basic: 100, Int: 100}
              → avg(100, 100) = 100
          * C2 Basic, assessment Adv breakdown {Basic: 50}
              → avg(50) = 50

        Combined match: (67 + 100 + 50) / 3 = 72 — the expected value from
        the QA screenshot. Pre-REDO matcher returned 65 (AssessmentResult.percent
        for the Adv-level overall — average across all three).
        """
        basic, inter, adv = await self._setup_levels(db, tenant)
        scale = AnswerScale(tenant_id=tenant.id, title="HRP-129 weighted")
        db.add(scale)
        await db.flush()
        # Three options on a 0..2 weight scale so we can express 100 / 33 / 50.
        # 100% → weight 2, 50% → weight 1, 33% comes from one-of-three
        # indicators answered "yes" at weight 2 (so 2/2 * 100 = 100 for that
        # ind, averaged with two unanswered = 33). We use the indicator-level
        # averaging the breakdown function already does.
        full = AnswerOption(
            scale_id=scale.id, title="Full", code="full", weight=2, sort_index=0
        )
        half = AnswerOption(
            scale_id=scale.id, title="Half", code="half", weight=1, sort_index=1
        )
        zero = AnswerOption(
            scale_id=scale.id, title="Zero", code="zero", weight=0, sort_index=2
        )
        db.add_all([full, half, zero])
        await db.commit()
        done = await _done_status(db)
        self_type = await _self_type(db)

        card, comps = await self._setup_card_with_three_comps(
            db, tenant, user, req_levels=[inter, inter, basic]
        )
        card = await db.get(TalentCard, card.id)
        c0, c1, c2 = comps

        # For each (competence, level) pair, we seed three indicators (a, b, c)
        # so we can vary their answers to land on the target percent.
        # Indicator avg = sum(answers)/3. Level percent = indicator_avg / max_weight * 100.
        # max_weight = 2 → indicator weight 2 contributes 100, weight 1 → 50, weight 0 → 0.
        # The breakdown averages indicator percents per level (with weight=1 each):
        #   Basic 100 = 3 inds at weight 2 → (100 + 100 + 100) / 3
        #   Int  33  = 1 ind at weight 2, 2 at weight 0 → (100 + 0 + 0) / 3
        #   Int  100 = 3 inds at weight 2
        #   Basic 50 = 3 inds at weight 1
        a = Assessment(
            tenant_id=tenant.id,
            employee_id=employee.id,
            type_id=self_type.id,
            status_id=done.id,
            initiator_id=employee.user_id,
            scale_id=scale.id,
            finished_at=datetime.now(timezone.utc),
        )
        db.add(a)
        await db.flush()

        participant = AssessmentParticipant(
            assessment_id=a.id, user_id=employee.user_id, role="self"
        )
        db.add(participant)
        await db.flush()

        # Helper to seed (3 indicators on `level` for `comp`, answers list).
        async def _level_block(
            comp: Competence,
            level: SkillLevel,
            opts: list[AnswerOption],
        ) -> None:
            for i, opt in enumerate(opts):
                ind = Indicator(
                    tenant_id=tenant.id,
                    competence_id=comp.id,
                    skill_level_id=level.id,
                    title=f"{comp.title}-{level.title}-{i}",
                    weight=1,
                )
                db.add(ind)
                await db.flush()
                db.add(
                    AssessmentAnswer(
                        assessment_id=a.id,
                        participant_id=participant.id,
                        indicator_id=ind.id,
                        answer_option_id=opt.id,
                    )
                )

        # AssessmentCompetence rows — one per (comp), target = Adv.
        for comp in (c0, c1, c2):
            db.add(
                AssessmentCompetence(
                    assessment_id=a.id,
                    competence_id=comp.id,
                    skill_level_id=adv.id,
                )
            )
        await db.flush()

        # C0: Basic[full,full,full]=100, Int[full,zero,zero]=33
        await _level_block(c0, basic, [full, full, full])
        await _level_block(c0, inter, [full, zero, zero])

        # C1: Basic[full,full,full]=100, Int[full,full,full]=100
        await _level_block(c1, basic, [full, full, full])
        await _level_block(c1, inter, [full, full, full])

        # C2: Basic[half,half,half]=50
        await _level_block(c2, basic, [half, half, half])

        await db.commit()

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert basis == "competence"
        # (67 + 100 + 50) / 3 = 72.33… → round to 72.
        assert score == 72

    async def test_fallback_to_result_percent_when_no_breakdown(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Synthetic-fixture assessments without scale/answers still work.

        Backward-compat: existing test_talent_market_service.py fixtures
        seed AssessmentResult.percent directly without a scale, so the
        breakdown batch returns ``{}`` and the matcher must fall back to
        AssessmentResult.percent. We don't want this rewrite to require
        every test in the suite to spin up indicators + answers.
        """
        basic, inter, _adv = await self._setup_levels(db, tenant)
        done = await _done_status(db)
        self_type = await _self_type(db)

        # Card with one Required Competence at Int level.
        card_dict = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(
                title="Fallback", card_type="vacancy", match_percent=60
            ),
        )
        card = await db.get(TalentCard, card_dict["id"])
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="C")
        db.add(comp)
        await db.flush()
        db.add(
            TalentCardCompetence(
                card_id=card.id, competence_id=comp.id, skill_level_id=inter.id
            )
        )
        await db.commit()

        # Done assessment at Int — no scale, no answers; the breakdown
        # function returns {} so the matcher falls back to result.percent.
        a = Assessment(
            tenant_id=tenant.id,
            employee_id=employee.id,
            type_id=self_type.id,
            status_id=done.id,
            initiator_id=employee.user_id,
            finished_at=datetime.now(timezone.utc),
        )
        db.add(a)
        await db.flush()
        db.add(
            AssessmentCompetence(
                assessment_id=a.id,
                competence_id=comp.id,
                skill_level_id=inter.id,
            )
        )
        db.add(
            AssessmentResult(
                assessment_id=a.id,
                competence_id=comp.id,
                avg_score=2.0,
                percent=85,
            )
        )
        await db.commit()

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert basis == "competence"
        assert score == 85

    async def test_latest_assessment_still_wins_after_projection(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-129 invariant: latest Done assessment wins even when its
        projected percent is lower than an older one.

        Seeds two Done assessments at Adv on the same competence required
        at Int. The older assessment fully covers Basic+Int (→ 100%), the
        newer one only covers Basic (→ 50%). Matcher must return 50.
        """
        from datetime import timedelta

        basic, inter, adv = await self._setup_levels(db, tenant)
        scale, high = await _seed_scale(db, tenant)
        card, comps = await self._setup_card_with_three_comps(
            db, tenant, user, req_levels=[inter]
        )
        card = await db.get(TalentCard, card.id)
        comp = comps[0]

        await _seed_assessment_with_breakdown(
            db,
            tenant=tenant,
            employee=employee,
            scale=scale,
            answer_high=high,
            target_level=adv,
            competence=comp,
            answered_levels=[basic, inter],
            finished_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        await _seed_assessment_with_breakdown(
            db,
            tenant=tenant,
            employee=employee,
            scale=scale,
            answer_high=high,
            target_level=adv,
            competence=comp,
            answered_levels=[basic],
            finished_at=datetime.now(timezone.utc),
        )

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert basis == "competence"
        # New assessment: Basic answered = 100, Int unanswered = 0 → (100+0)/2 = 50.
        assert score == 50


class TestHrp129AutoPoolEndToEnd:
    """Cold-start scenario: empty card → set Required Competences →
    Candidates block populated. Pure black-box test that goes through the
    same public API the UI hits.
    """

    async def test_cold_start_auto_pool_with_qa_scenario(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Mirror the reporter's first 2026-05-25 example: card threshold 80%,
        employee with a Done assessment scoring 84% → auto-pool picks the
        employee up as soon as Required Competences are set.
        """
        from sqlalchemy import select

        levels = await self._setup_levels(db, tenant)
        basic, inter, adv = levels
        # Two competences required at Int, both fully answered at Int
        # (and trivially answered at Basic) on an Int-target assessment.
        # avg(Basic, Int) per breakdown = 100, then averaged across two
        # comps = 100 → comfortably above the 80% gate.
        scale, high = await _seed_scale(db, tenant)
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        c1 = Competence(tenant_id=tenant.id, group_id=group.id, title="C1")
        c2 = Competence(tenant_id=tenant.id, group_id=group.id, title="C2")
        db.add_all([c1, c2])
        await db.commit()

        for comp in (c1, c2):
            await _seed_assessment_with_breakdown(
                db,
                tenant=tenant,
                employee=employee,
                scale=scale,
                answer_high=high,
                target_level=inter,
                competence=comp,
                answered_levels=[basic, inter],
            )

        card_dict = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(
                title="QA cold-start",
                card_type="vacancy",
                match_percent=80,
            ),
        )
        # Cold state: empty Required Competences → no candidates yet.
        candidates_before = (
            (
                await db.execute(
                    select(service.TalentCandidate).where(
                        service.TalentCandidate.card_id == card_dict["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert candidates_before == []

        await service.add_required_competences(
            db,
            tenant.id,
            card_dict["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=c1.id, skill_level_id=inter.id),
                    RequiredCompetenceItem(competence_id=c2.id, skill_level_id=inter.id),
                ]
            ),
        )

        candidates = (
            (
                await db.execute(
                    select(service.TalentCandidate).where(
                        service.TalentCandidate.card_id == card_dict["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(candidates) == 1
        assert candidates[0].employee_id == employee.id
        # HRP-214: auto-pool now tags rows `matched`.
        assert candidates[0].status == "matched"
        assert candidates[0].match_score == 100

    async def _setup_levels(
        self, db: AsyncSession, tenant
    ) -> tuple[SkillLevel, SkillLevel, SkillLevel]:
        basic = SkillLevel(tenant_id=tenant.id, title="Basic", sort_index=0)
        inter = SkillLevel(tenant_id=tenant.id, title="Int", sort_index=1)
        adv = SkillLevel(tenant_id=tenant.id, title="Adv", sort_index=2)
        db.add_all([basic, inter, adv])
        await db.flush()
        return basic, inter, adv
