"""Step 6: PDPs — full demo only."""

from datetime import timedelta

from app.modules.assessment.models import PDP, PDPComment, PDPItem, PDPItemMaterial

from .context import SeedContext
from .helpers import now, past_dt, uid


async def seed_pdps(ctx: SeedContext) -> None:
    comps = ctx.competences
    assert comps is not None, "competences step must run before pdps"
    a1 = ctx.assessment_self
    assert a1 is not None, "assessments step must run before pdps"

    emp_carol = ctx.employees[2]
    user_carol = ctx.users[2]
    emp_bob = ctx.employees[1]

    pdp1 = PDP(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Backend Growth Plan — Carol Johnson",
        employee_id=emp_carol.id,
        assessment_id=a1.id,
        author_id=ctx.admin_user.id,
        reviewer_id=ctx.users[0].id,
        status="active",
        total_progress=40,
        specialization_id=ctx.specializations["Backend Developer"].id,
        grade_id=ctx.grades["Senior"].id,
        deadline=now + timedelta(days=60),
        started_at=past_dt(15),
    )
    ctx.db.add(pdp1)
    await ctx.db.flush()

    pdp1_items_data: list[tuple] = [
        (
            "Improve async Python skills",
            "Focus on asyncio patterns and aiohttp",
            comps.python,
            True,
            [
                (
                    "AsyncIO Deep Dive course",
                    "video",
                    "https://example.com/asyncio",
                    240,
                ),
                ("Practice: rewrite sync service to async", "exercise", None, 480),
            ],
        ),
        (
            "Master query optimization",
            "Learn EXPLAIN ANALYZE and indexing strategies",
            comps.sql,
            False,
            [
                (
                    "PostgreSQL Performance Tuning",
                    "article",
                    "https://example.com/pg-perf",
                    120,
                ),
                (
                    "Database Internals (book)",
                    "book",
                    "https://example.com/db-internals",
                    600,
                ),
            ],
        ),
        (
            "Develop public speaking skills",
            "Practice presenting at team demos",
            comps.comm,
            False,
            [
                ("Crucial Conversations", "book", "https://example.com/crucial", 300),
            ],
        ),
    ]
    for idx, (title, desc, comp, is_passed, mats) in enumerate(pdp1_items_data):
        item = PDPItem(
            id=uid(),
            pdp_id=pdp1.id,
            competence_id=comp.id,
            title=title,
            description=desc,
            sort_index=idx,
            is_passed=is_passed,
            entity_type="competence",
        )
        ctx.db.add(item)
        await ctx.db.flush()
        for mi, (mt, mf, ml, mst) in enumerate(mats):
            ctx.db.add(
                PDPItemMaterial(
                    id=uid(),
                    item_id=item.id,
                    title=mt,
                    format=mf,
                    link=ml,
                    study_time=mst,
                    sort_index=mi,
                    is_passed=is_passed and mi == 0,
                )
            )

    ctx.db.add(
        PDPComment(
            id=uid(),
            pdp_id=pdp1.id,
            user_id=ctx.users[0].id,
            text="Great progress on async Python! Let's discuss SQL optimization next.",
        )
    )
    ctx.db.add(
        PDPComment(
            id=uid(),
            pdp_id=pdp1.id,
            user_id=user_carol.id,
            text="Thanks! I've started the PostgreSQL course, it's very helpful.",
        )
    )
    await ctx.db.flush()

    # PDP 2: Draft
    pdp2 = PDP(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Leadership Development Plan — Bob Martinez",
        employee_id=emp_bob.id,
        author_id=ctx.admin_user.id,
        status="draft",
        specialization_id=ctx.specializations["Backend Developer"].id,
        grade_id=ctx.grades["Lead"].id,
        deadline=now + timedelta(days=90),
    )
    ctx.db.add(pdp2)
    await ctx.db.flush()

    for idx, (title, desc) in enumerate(
        [
            (
                "Develop architecture decision skills",
                "Practice writing ADRs for team decisions",
            ),
            (
                "Improve delegation skills",
                "Learn to delegate effectively to senior developers",
            ),
            ("Cross-team collaboration", "Lead a cross-team initiative"),
        ]
    ):
        ctx.db.add(
            PDPItem(
                id=uid(),
                pdp_id=pdp2.id,
                title=title,
                description=desc,
                sort_index=idx,
                entity_type="custom",
            )
        )

    # PDP 3: Completed
    pdp3 = PDP(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Onboarding Development Plan — David Kim",
        employee_id=ctx.employees[3].id,
        author_id=ctx.users[1].id,
        reviewer_id=ctx.users[0].id,
        status="completed",
        total_progress=100,
        specialization_id=ctx.specializations["Backend Developer"].id,
        grade_id=ctx.grades["Middle"].id,
        deadline=past_dt(5),
        started_at=past_dt(60),
        finished_at=past_dt(5),
    )
    ctx.db.add(pdp3)
    await ctx.db.flush()

    for idx, title in enumerate(
        ["Learn Docker multi-stage builds", "Complete SQL workshop"]
    ):
        ctx.db.add(
            PDPItem(
                id=uid(),
                pdp_id=pdp3.id,
                title=title,
                sort_index=idx,
                is_passed=True,
                entity_type="custom",
            )
        )

    await ctx.db.flush()
