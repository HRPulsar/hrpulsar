"""Step 5: assessments (self / 180 / 360) — full demo only."""

import random
from datetime import timedelta

from sqlalchemy import select

from app.modules.assessment.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
    AssessmentResult,
)
from app.modules.competence.models import Indicator

from .context import SeedContext
from .helpers import now, past_dt, uid


async def _get_indicators(ctx: SeedContext, competence_id):
    return (
        (
            await ctx.db.execute(
                select(Indicator).where(Indicator.competence_id == competence_id)
            )
        )
        .scalars()
        .all()
    )


async def seed_assessments(ctx: SeedContext) -> None:
    comps = ctx.competences
    assert comps is not None, "competences step must run before assessments"

    # --- Assessment 1: Self-assessment (completed) ---
    emp_carol = ctx.employees[2]
    user_carol = ctx.users[2]

    a1 = Assessment(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Q1 2026 Self-Assessment — Carol Johnson",
        employee_id=emp_carol.id,
        type_id=ctx.type_map["self"].id,
        status_id=ctx.status_map["done"].id,
        specialization_id=ctx.specializations["Backend Developer"].id,
        grade_id=ctx.grades["Senior"].id,
        scale_id=ctx.default_scale.id,
        initiator_id=ctx.admin_user.id,
        started_at=past_dt(30),
        finished_at=past_dt(20),
    )
    ctx.db.add(a1)
    await ctx.db.flush()

    a1_comps = [comps.python, comps.sql, comps.api, comps.comm, comps.teamwork]
    for c in a1_comps:
        ctx.db.add(
            AssessmentCompetence(id=uid(), assessment_id=a1.id, competence_id=c.id)
        )

    p1 = AssessmentParticipant(
        id=uid(),
        assessment_id=a1.id,
        user_id=user_carol.id,
        role="self",
        is_completed=True,
    )
    ctx.db.add(p1)
    await ctx.db.flush()

    for comp in a1_comps:
        indicators = await _get_indicators(ctx, comp.id)
        for ind in indicators:
            opt = random.choice(ctx.scale_options[1:])
            ctx.db.add(
                AssessmentAnswer(
                    id=uid(),
                    assessment_id=a1.id,
                    participant_id=p1.id,
                    indicator_id=ind.id,
                    answer_option_id=opt.id,
                    score=opt.weight,
                )
            )

    for comp in a1_comps:
        ctx.db.add(
            AssessmentResult(
                id=uid(),
                assessment_id=a1.id,
                competence_id=comp.id,
                avg_score=round(random.uniform(2.0, 3.8), 2),
                calibrated_score=round(random.uniform(2.0, 3.8), 2),
            )
        )

    await ctx.db.flush()

    # --- Assessment 2: 180 (in_progress) ---
    emp_bob = ctx.employees[1]
    user_bob = ctx.users[1]

    a2 = Assessment(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Q1 2026 180° Assessment — Bob Martinez",
        employee_id=emp_bob.id,
        type_id=ctx.type_map["180"].id,
        status_id=ctx.status_map["in_progress"].id,
        specialization_id=ctx.specializations["Backend Developer"].id,
        grade_id=ctx.grades["Lead"].id,
        scale_id=ctx.default_scale.id,
        initiator_id=ctx.admin_user.id,
        started_at=past_dt(10),
    )
    ctx.db.add(a2)
    await ctx.db.flush()

    a2_comps = [
        comps.python,
        comps.api,
        comps.mentoring,
        comps.decision,
        comps.planning,
    ]
    for c in a2_comps:
        ctx.db.add(
            AssessmentCompetence(id=uid(), assessment_id=a2.id, competence_id=c.id)
        )

    p2_self = AssessmentParticipant(
        id=uid(),
        assessment_id=a2.id,
        user_id=user_bob.id,
        role="self",
        is_completed=True,
    )
    user_alice = ctx.users[0]
    p2_mgr = AssessmentParticipant(
        id=uid(),
        assessment_id=a2.id,
        user_id=user_alice.id,
        role="manager",
        is_completed=False,
    )
    ctx.db.add_all([p2_self, p2_mgr])
    await ctx.db.flush()

    for comp in a2_comps:
        indicators = await _get_indicators(ctx, comp.id)
        for ind in indicators:
            opt = random.choice(ctx.scale_options[1:])
            ctx.db.add(
                AssessmentAnswer(
                    id=uid(),
                    assessment_id=a2.id,
                    participant_id=p2_self.id,
                    indicator_id=ind.id,
                    answer_option_id=opt.id,
                    score=opt.weight,
                )
            )

    await ctx.db.flush()

    # --- Assessment 3: 360 (draft) ---
    emp_grace = ctx.employees[6]

    a3 = Assessment(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Q2 2026 360° Assessment — Grace Taylor",
        employee_id=emp_grace.id,
        type_id=ctx.type_map["360"].id,
        status_id=ctx.status_map["draft"].id,
        specialization_id=ctx.specializations["Frontend Developer"].id,
        grade_id=ctx.grades["Lead"].id,
        scale_id=ctx.default_scale.id,
        initiator_id=ctx.admin_user.id,
        ended_at=now + timedelta(days=30),
    )
    ctx.db.add(a3)
    await ctx.db.flush()

    a3_comps = [comps.js, comps.comm, comps.written, comps.teamwork, comps.mentoring]
    for c in a3_comps:
        ctx.db.add(
            AssessmentCompetence(id=uid(), assessment_id=a3.id, competence_id=c.id)
        )

    user_grace = ctx.users[6]
    for u, role in [
        (user_grace, "self"),
        (ctx.users[0], "manager"),
        (ctx.users[7], "peer"),
        (ctx.users[8], "peer"),
        (ctx.users[9], "peer"),
    ]:
        ctx.db.add(
            AssessmentParticipant(
                id=uid(),
                assessment_id=a3.id,
                user_id=u.id,
                role=role,
                is_completed=False,
            )
        )

    await ctx.db.flush()

    ctx.assessment_self = a1
