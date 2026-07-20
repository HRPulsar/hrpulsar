"""Step 8: talent market cards (vacancy / talent / project) — full demo
only."""

import random
from datetime import timedelta

from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardCompetence,
    TalentCardRequirement,
    TalentCardSpecialization,
)

from .context import SeedContext
from .helpers import now, past_date, past_dt, uid


async def seed_talent_market(ctx: SeedContext) -> None:
    comps = ctx.competences
    assert comps is not None, "competences step must run before talent market"
    sl_basic = ctx.skill_levels["Basic"]
    sl_inter = ctx.skill_levels["Intermediate"]
    sl_adv = ctx.skill_levels["Advanced"]

    card_vacancy = TalentCard(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Senior Backend Developer — Platform Team",
        description=(
            "We're looking for a Senior Backend Developer to join our Platform team. "
            "You'll work on the core API layer, database optimization, and build "
            "scalable microservices. Experience with Python/FastAPI and PostgreSQL required."
        ),
        card_type="vacancy",
        status="published",
        author_id=ctx.admin_user.id,
        division_id=ctx.div["backend"].id,
        is_published=True,
        published_at=past_dt(14),
        start_date=past_date(14),
    )
    ctx.db.add(card_vacancy)
    await ctx.db.flush()

    ctx.db.add(
        TalentCardSpecialization(
            id=uid(),
            card_id=card_vacancy.id,
            specialization_id=ctx.specializations["Backend Developer"].id,
            grade_id=ctx.grades["Senior"].id,
        )
    )
    ctx.db.add(
        TalentCardCompetence(
            id=uid(),
            card_id=card_vacancy.id,
            competence_id=comps.python.id,
            skill_level_id=sl_adv.id,
        )
    )
    ctx.db.add(
        TalentCardCompetence(
            id=uid(),
            card_id=card_vacancy.id,
            competence_id=comps.sql.id,
            skill_level_id=sl_inter.id,
        )
    )
    ctx.db.add(
        TalentCardRequirement(
            id=uid(),
            card_id=card_vacancy.id,
            description="3+ years of Python backend development",
            min_experience_years=3,
        )
    )
    ctx.db.add(
        TalentCardRequirement(
            id=uid(),
            card_id=card_vacancy.id,
            description="Experience with PostgreSQL or similar RDBMS",
            min_experience_years=2,
        )
    )

    ctx.db.add(
        TalentCandidate(
            id=uid(),
            card_id=card_vacancy.id,
            employee_id=ctx.employees[3].id,
            status="interested",
            match_score=78,
            response_at=past_dt(10),
        )
    )
    ctx.db.add(
        TalentCandidate(
            id=uid(),
            card_id=card_vacancy.id,
            employee_id=ctx.employees[4].id,
            status="nominated",
            match_score=85,
        )
    )
    await ctx.db.flush()

    card_talent = TalentCard(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Internal Mobility: Engineering -> Product",
        description=(
            "Looking for engineers interested in transitioning to Product Management. "
            "This is a 6-month rotation program with mentoring from senior PMs."
        ),
        card_type="talent",
        status="draft",
        author_id=ctx.users[18].id if len(ctx.users) > 18 else ctx.admin_user.id,
        division_id=ctx.div.get("product_mgmt", list(ctx.div.values())[0]).id,
        start_date=past_date(0),
    )
    ctx.db.add(card_talent)
    await ctx.db.flush()

    ctx.db.add(
        TalentCardRequirement(
            id=uid(),
            card_id=card_talent.id,
            description="2+ years in engineering role",
            min_experience_years=2,
        )
    )
    ctx.db.add(
        TalentCardRequirement(
            id=uid(),
            card_id=card_talent.id,
            description="Interest in product management and user research",
        )
    )

    card_project = TalentCard(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Hackathon: AI-Powered Code Review Tool",
        description=(
            "Cross-functional team project to build an AI-powered code review assistant. "
            "2-week sprint, starting next month. Looking for backend, frontend, and ML engineers."
        ),
        card_type="project",
        status="published",
        author_id=ctx.users[0].id,
        division_id=ctx.div.get("engineering", list(ctx.div.values())[0]).id,
        is_published=True,
        published_at=past_dt(3),
        # The description promises a sprint "starting next month".
        start_date=(now + timedelta(days=30)).date(),
    )
    ctx.db.add(card_project)
    await ctx.db.flush()

    ctx.db.add(
        TalentCardCompetence(
            id=uid(),
            card_id=card_project.id,
            competence_id=comps.python.id,
            skill_level_id=sl_inter.id,
        )
    )
    ctx.db.add(
        TalentCardCompetence(
            id=uid(),
            card_id=card_project.id,
            competence_id=comps.js.id,
            skill_level_id=sl_basic.id,
        )
    )

    for emp in random.sample(
        ctx.employees[: min(15, len(ctx.employees))], min(4, len(ctx.employees))
    ):
        ctx.db.add(
            TalentCandidate(
                id=uid(),
                card_id=card_project.id,
                employee_id=emp.id,
                status=random.choice(["nominated", "interested", "matched"]),
                match_score=random.randint(60, 95),
            )
        )

    await ctx.db.flush()
