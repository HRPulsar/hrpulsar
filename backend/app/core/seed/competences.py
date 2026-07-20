"""Step 4: competence groups, competences, indicators, materials."""

from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
)

from .context import CompetenceHandles, SeedContext
from .helpers import uid


async def seed_competences(ctx: SeedContext) -> None:
    hard_type = ctx.comp_types["Hard skill"]
    soft_type = ctx.comp_types["Soft skill"]
    sl_basic = ctx.skill_levels["Basic"]
    sl_inter = ctx.skill_levels["Intermediate"]
    sl_adv = ctx.skill_levels["Advanced"]

    tech_group = CompetenceGroup(
        id=uid(), title="Technical Skills", tenant_id=ctx.tenant_id, sort_index=0
    )
    soft_group = CompetenceGroup(
        id=uid(), title="Soft Skills", tenant_id=ctx.tenant_id, sort_index=1
    )
    lead_group = CompetenceGroup(
        id=uid(), title="Leadership", tenant_id=ctx.tenant_id, sort_index=2
    )
    ctx.db.add_all([tech_group, soft_group, lead_group])
    await ctx.db.flush()

    prog_group = CompetenceGroup(
        id=uid(),
        title="Programming",
        parent_id=tech_group.id,
        tenant_id=ctx.tenant_id,
        sort_index=0,
    )
    infra_group = CompetenceGroup(
        id=uid(),
        title="Infrastructure",
        parent_id=tech_group.id,
        tenant_id=ctx.tenant_id,
        sort_index=1,
    )
    comm_group = CompetenceGroup(
        id=uid(),
        title="Communication",
        parent_id=soft_group.id,
        tenant_id=ctx.tenant_id,
        sort_index=0,
    )
    ctx.db.add_all([prog_group, infra_group, comm_group])
    await ctx.db.flush()

    all_competences = []

    def make_competence(title, desc, group, ctype, indicators_data):
        c = Competence(
            id=uid(),
            title=title,
            description=desc,
            group_id=group.id,
            competence_type_id=ctype.id,
            tenant_id=ctx.tenant_id,
            is_active=True,
        )
        ctx.db.add(c)
        for ind_title, sl, weight, idx in indicators_data:
            ctx.db.add(
                Indicator(
                    id=uid(),
                    title=ind_title,
                    weight=weight,
                    sort_index=idx,
                    skill_level_id=sl.id,
                    competence_id=c.id,
                    tenant_id=ctx.tenant_id,
                )
            )
        all_competences.append(c)
        return c

    c_python = make_competence(
        "Python Development",
        "Proficiency in Python programming",
        prog_group,
        hard_type,
        [
            ("Writes clean, PEP-8 compliant code", sl_basic, 1, 0),
            ("Uses type hints and dataclasses effectively", sl_inter, 2, 1),
            ("Designs async/concurrent systems", sl_adv, 3, 2),
            ("Optimizes performance and memory usage", sl_adv, 3, 3),
        ],
    )
    c_js = make_competence(
        "JavaScript/TypeScript",
        "Modern JS/TS development skills",
        prog_group,
        hard_type,
        [
            ("Understands ES6+ features", sl_basic, 1, 0),
            ("Uses TypeScript type system effectively", sl_inter, 2, 1),
            ("Builds complex React applications", sl_adv, 3, 2),
        ],
    )
    c_sql = make_competence(
        "SQL & Databases",
        "Database design and query optimization",
        prog_group,
        hard_type,
        [
            ("Writes correct JOIN queries", sl_basic, 1, 0),
            ("Designs normalized schemas", sl_inter, 2, 1),
            ("Optimizes query execution plans", sl_adv, 3, 2),
        ],
    )
    c_api = make_competence(
        "API Design",
        "RESTful and GraphQL API design",
        prog_group,
        hard_type,
        [
            ("Follows REST conventions", sl_basic, 1, 0),
            ("Designs versioned, backward-compatible APIs", sl_inter, 2, 1),
            ("Implements proper error handling and pagination", sl_adv, 3, 2),
        ],
    )
    make_competence(
        "Docker & Containers",
        "Containerization skills",
        infra_group,
        hard_type,
        [
            ("Writes Dockerfiles", sl_basic, 1, 0),
            ("Uses multi-stage builds", sl_inter, 2, 1),
            ("Manages container orchestration", sl_adv, 3, 2),
        ],
    )
    make_competence(
        "CI/CD Pipelines",
        "Continuous integration and deployment",
        infra_group,
        hard_type,
        [
            ("Configures basic CI pipelines", sl_basic, 1, 0),
            ("Implements blue-green deployments", sl_inter, 2, 1),
            ("Designs multi-environment promotion strategies", sl_adv, 3, 2),
        ],
    )
    c_comm = make_competence(
        "Verbal Communication",
        "Clear and effective verbal communication",
        comm_group,
        soft_type,
        [
            ("Expresses ideas clearly in meetings", sl_basic, 1, 0),
            ("Presents technical topics to non-technical audience", sl_inter, 2, 1),
            ("Facilitates productive discussions", sl_adv, 3, 2),
        ],
    )
    c_written = make_competence(
        "Written Communication",
        "Documentation and written skills",
        comm_group,
        soft_type,
        [
            ("Writes clear PRs and commit messages", sl_basic, 1, 0),
            ("Creates comprehensive technical documentation", sl_inter, 2, 1),
            ("Authors RFCs and architecture decision records", sl_adv, 3, 2),
        ],
    )
    c_teamwork = make_competence(
        "Teamwork",
        "Collaboration and team skills",
        soft_group,
        soft_type,
        [
            ("Participates actively in team activities", sl_basic, 1, 0),
            ("Helps onboard new team members", sl_inter, 2, 1),
            ("Resolves team conflicts constructively", sl_adv, 3, 2),
        ],
    )
    c_mentoring = make_competence(
        "Mentoring",
        "Ability to mentor and grow others",
        lead_group,
        soft_type,
        [
            ("Provides constructive code review feedback", sl_basic, 1, 0),
            ("Creates learning plans for mentees", sl_inter, 2, 1),
            ("Develops senior-level engineers", sl_adv, 3, 2),
        ],
    )
    c_decision = make_competence(
        "Decision Making",
        "Strategic and tactical decision making",
        lead_group,
        soft_type,
        [
            ("Makes timely decisions with available data", sl_basic, 1, 0),
            ("Balances short-term and long-term trade-offs", sl_inter, 2, 1),
            ("Makes high-stakes decisions under uncertainty", sl_adv, 3, 2),
        ],
    )
    c_planning = make_competence(
        "Project Planning",
        "Planning and execution of projects",
        lead_group,
        soft_type,
        [
            ("Breaks tasks into actionable work items", sl_basic, 1, 0),
            ("Estimates effort and manages timelines", sl_inter, 2, 1),
            ("Plans cross-team initiatives", sl_adv, 3, 2),
        ],
    )

    await ctx.db.flush()

    # Materials
    for comp, mats in [
        (
            c_python,
            [
                (
                    "Fluent Python (book)",
                    "book",
                    "https://example.com/fluent-python",
                    600,
                ),
                (
                    "Real Python Tutorials",
                    "article",
                    "https://example.com/realpython",
                    120,
                ),
            ],
        ),
        (
            c_js,
            [
                (
                    "TypeScript Handbook",
                    "article",
                    "https://example.com/ts-handbook",
                    180,
                ),
                (
                    "React Patterns Course",
                    "video",
                    "https://example.com/react-patterns",
                    480,
                ),
            ],
        ),
        (
            c_comm,
            [
                (
                    "Crucial Conversations (book)",
                    "book",
                    "https://example.com/crucial-conv",
                    300,
                ),
            ],
        ),
    ]:
        for i, (title, fmt, link, study_time) in enumerate(mats):
            ctx.db.add(
                Material(
                    id=uid(),
                    title=title,
                    format=fmt,
                    link=link,
                    study_time=study_time,
                    sort_index=i,
                    skill_level_id=sl_inter.id,
                    competence_id=comp.id,
                    tenant_id=ctx.tenant_id,
                )
            )

    await ctx.db.flush()

    ctx.competences = CompetenceHandles(
        python=c_python,
        js=c_js,
        sql=c_sql,
        api=c_api,
        comm=c_comm,
        written=c_written,
        teamwork=c_teamwork,
        mentoring=c_mentoring,
        decision=c_decision,
        planning=c_planning,
        all_competences=all_competences,
    )
