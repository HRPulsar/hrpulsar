"""Competence and skill-ladder fixtures for the demo seed (HRP-281 — S2).

Populates ``competence_groups``, ``competences``, indicators and
materials, and the ``grade_competence_links`` cells per
(grade × specialization). Skill levels are NOT seeded as tenant-custom
rows — the demo binds to the origin Basic / Intermediate / Advanced
ladder shipped by ``aca1005a8e45``. HRP-299 collapsed the previous
4-level custom ladder so the /competences page shows a single, coherent
3-level ladder instead of mixing 3 origin + 4 custom levels.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Skill levels — reference origin (tenant_id IS NULL) rows by title.
# The seed loader resolves these to ``SkillLevel`` objects; we don't insert
# new tenant-scoped levels here.
# ---------------------------------------------------------------------------

SKILL_LEVELS: list[dict] = [
    {"key": "sl-l1", "title": "Basic"},
    {"key": "sl-l2", "title": "Intermediate"},
    {"key": "sl-l3", "title": "Advanced"},
    # Legacy L4 entries from indicator/grade lists collapse onto Advanced
    # so a previously-Expert competence becomes the top of the 3-level
    # ladder instead of vanishing from the UI.
    {"key": "sl-l4", "title": "Advanced"},
]


# ---------------------------------------------------------------------------
# Competence groups
# ---------------------------------------------------------------------------

COMPETENCE_GROUPS: list[dict] = [
    {
        "key": "g-engineering",
        "title": "Engineering",
        "description": "Software engineering and systems craft.",
        "sort_index": 10,
    },
    {
        "key": "g-product-ux",
        "title": "Product & UX",
        "description": "Discovery, product judgement, user experience.",
        "sort_index": 20,
    },
    {
        "key": "g-communication",
        "title": "Communication",
        "description": "Written, async, cross-functional clarity.",
        "sort_index": 30,
    },
    {
        "key": "g-leadership",
        "title": "Leadership",
        "description": "Mentoring, hiring, conflict resolution.",
        "sort_index": 40,
    },
    {
        "key": "g-ai-literacy",
        "title": "AI Literacy",
        "description": "Prompt fluency, agentic workflows, tool adoption.",
        "sort_index": 50,
    },
    {
        "key": "g-business",
        "title": "Business",
        "description": "Customer discovery, outcomes, sales fundamentals.",
        "sort_index": 60,
    },
]


# ---------------------------------------------------------------------------
# Competences  (group_key resolves to CompetenceGroup.id at seed time)
# ---------------------------------------------------------------------------

COMPETENCES: list[dict] = [
    # Engineering
    {
        "key": "c-python",
        "title": "Python",
        "group_key": "g-engineering",
        "description": "Idiomatic Python, type hints, async, packaging.",
    },
    {
        "key": "c-fastapi",
        "title": "FastAPI",
        "group_key": "g-engineering",
        "description": "Building production HTTP services with FastAPI.",
    },
    {
        "key": "c-postgres",
        "title": "PostgreSQL",
        "group_key": "g-engineering",
        "description": "Schema design, query tuning, partitioning.",
    },
    {
        "key": "c-distributed",
        "title": "Distributed Systems",
        "group_key": "g-engineering",
        "description": "Idempotency, queues, consistency tradeoffs.",
    },
    {
        "key": "c-typescript",
        "title": "TypeScript",
        "group_key": "g-engineering",
        "description": "Type-safe frontend code, generics, narrowing.",
    },
    {
        "key": "c-react",
        "title": "React",
        "group_key": "g-engineering",
        "description": "Component design, state management, server components.",
    },
    {
        "key": "c-web-perf",
        "title": "Web Performance",
        "group_key": "g-engineering",
        "description": "Loading budgets, profiling, optimisation.",
    },
    # Product & UX
    {
        "key": "c-user-research",
        "title": "User Research",
        "group_key": "g-product-ux",
        "description": "Interviewing, synthesis, opportunity sizing.",
    },
    {
        "key": "c-roadmap",
        "title": "Roadmap Prioritization",
        "group_key": "g-product-ux",
        "description": "Bet sizing, sequencing, opportunity tradeoffs.",
    },
    {
        "key": "c-design-systems",
        "title": "Design Systems",
        "group_key": "g-product-ux",
        "description": "Tokens, components, accessibility, contribution.",
    },
    # Communication
    {
        "key": "c-written",
        "title": "Written Communication",
        "group_key": "g-communication",
        "description": "RFCs, post-mortems, async updates that land.",
    },
    {
        "key": "c-async",
        "title": "Async Collaboration",
        "group_key": "g-communication",
        "description": "Working across timezones with low coordination cost.",
    },
    {
        "key": "c-cross-fn",
        "title": "Cross-functional Partnership",
        "group_key": "g-communication",
        "description": "Pairing with product, design, sales, legal.",
    },
    # Leadership
    {
        "key": "c-mentoring",
        "title": "Mentoring",
        "group_key": "g-leadership",
        "description": "Coaching juniors, growing peers.",
    },
    {
        "key": "c-hiring",
        "title": "Hiring",
        "group_key": "g-leadership",
        "description": "Interview craft, calibration, fair signals.",
    },
    {
        "key": "c-conflict",
        "title": "Conflict Resolution",
        "group_key": "g-leadership",
        "description": "Surfacing, mediating, repairing relationships.",
    },
    # AI Literacy
    {
        "key": "c-prompt",
        "title": "Prompt Engineering",
        "group_key": "g-ai-literacy",
        "description": "Structured prompts, examples, evaluations.",
    },
    {
        "key": "c-ai-tools",
        "title": "AI Tool Adoption",
        "group_key": "g-ai-literacy",
        "description": "Integrating AI tools into a daily workflow.",
    },
    {
        "key": "c-agentic",
        "title": "Agentic Workflows",
        "group_key": "g-ai-literacy",
        "description": "Designing multi-step agent flows with guardrails.",
    },
    # Business
    {
        "key": "c-customer-discovery",
        "title": "Customer Discovery",
        "group_key": "g-business",
        "description": "Talking to customers to validate problems.",
    },
    {
        "key": "c-okrs",
        "title": "OKRs",
        "group_key": "g-business",
        "description": "Setting, tracking and reflecting on outcomes.",
    },
    {
        "key": "c-sales-discovery",
        "title": "Sales Discovery",
        "group_key": "g-business",
        "description": "Qualifying enterprise deals, MEDDIC fundamentals.",
    },
    # HRP dev-loop storyline: the GTM team's enablement review scores
    # below the bar on these two — the dashboard's headline problem.
    {
        "key": "c-product-knowledge",
        "title": "Product Knowledge",
        "group_key": "g-business",
        "description": "Depth on the product, integrations and competitive landscape.",
    },
    {
        "key": "c-objection-handling",
        "title": "Objection Handling",
        "group_key": "g-business",
        "description": "Turning pricing and competitor pushback into next steps.",
    },
]


# ---------------------------------------------------------------------------
# Grade × specialization × competence ladder
# ---------------------------------------------------------------------------
#
# Each row says: "for the (grade, specialization) ladder cell, you need
# this competence at least at this skill level". The seed materialises
# rows for the five specializations that have a grade ladder (backend-dev,
# frontend-dev, product-mgmt, product-design, sales — the sales ladder
# was added with the HRP-612 storyline so its heroes have a growth path).

GRADE_COMPETENCE_LINKS: list[dict] = [
    # ----- Backend ladder -----
    # Junior: foundations
    {
        "grade_key": "g-junior",
        "specialization_key": "backend-dev",
        "competence_key": "c-python",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "backend-dev",
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "backend-dev",
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "backend-dev",
        "competence_key": "c-written",
        "skill_level_key": "sl-l1",
    },
    # Middle: independent
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "competence_key": "c-python",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l1",
    },
    # Senior: cross-team systems
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-python",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-written",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l2",
    },
    # Lead: architecture + people
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-python",
        "skill_level_key": "sl-l4",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "competence_key": "c-agentic",
        "skill_level_key": "sl-l2",
    },
    # ----- Frontend ladder -----
    {
        "grade_key": "g-junior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-react",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-written",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "competence_key": "c-react",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-react",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "frontend-dev",
        "competence_key": "c-react",
        "skill_level_key": "sl-l4",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "frontend-dev",
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "frontend-dev",
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "frontend-dev",
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l3",
    },
    # ----- Product Management ladder -----
    {
        "grade_key": "g-middle",
        "specialization_key": "product-mgmt",
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "product-mgmt",
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "product-mgmt",
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "product-mgmt",
        "competence_key": "c-written",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "product-mgmt",
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l4",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "product-mgmt",
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "product-mgmt",
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "product-mgmt",
        "competence_key": "c-conflict",
        "skill_level_key": "sl-l2",
    },
    # ----- Product Design ladder -----
    {
        "grade_key": "g-middle",
        "specialization_key": "product-design",
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "product-design",
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "product-design",
        "competence_key": "c-written",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-design",
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-design",
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-design",
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-design",
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l2",
    },
    # ----- Sales ladder (HRP-612 review) -----
    # The storyline's heroes are sellers; without these links their
    # personal growth block had nothing to require and the two GTM
    # competences never showed a required level anywhere.
    {
        "grade_key": "g-junior",
        "specialization_key": "sales",
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-junior",
        "specialization_key": "sales",
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "sales",
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "sales",
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "sales",
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l1",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "sales",
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "sales",
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "sales",
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l2",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "sales",
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "sales",
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l3",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "sales",
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l3",
    },
]


# ---------------------------------------------------------------------------
# Indicators  (4 per competence — one per skill level L1..L4)
# ---------------------------------------------------------------------------
#
# Behavioral statements an assessor scores on the default 5-point scale.
# Weight grows with the skill level (1..4) so the aggregator surfaces a
# meaningful spread on the results widget. Without these rows the
# /competences page renders empty competence cards and the /assessments
# scoring form has nothing to ask — both pages broke in the original S2
# cut that intentionally skipped indicators for the size budget.

INDICATORS: list[dict] = [
    # --- Python ---
    {
        "competence_key": "c-python",
        "skill_level_key": "sl-l1",
        "title": "Writes PEP-8 compliant code and uses the standard library idiomatically",
        "weight": 1,
    },
    {
        "competence_key": "c-python",
        "skill_level_key": "sl-l2",
        "title": "Applies type hints, dataclasses and pytest fixtures across a module",
        "weight": 2,
    },
    {
        "competence_key": "c-python",
        "skill_level_key": "sl-l3",
        "title": "Designs async/concurrent components and packages reusable libraries",
        "weight": 3,
    },
    {
        "competence_key": "c-python",
        "skill_level_key": "sl-l4",
        "title": "Tunes hot paths, profiles memory and mentors the team on idiomatic Python",
        "weight": 4,
    },
    # --- FastAPI ---
    {
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l1",
        "title": "Builds CRUD endpoints with Pydantic request/response models",
        "weight": 1,
    },
    {
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l2",
        "title": "Splits routers, wires dependencies and writes integration tests with TestClient",
        "weight": 2,
    },
    {
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l3",
        "title": "Designs async background flows, lifespan hooks and structured error handling",
        "weight": 3,
    },
    {
        "competence_key": "c-fastapi",
        "skill_level_key": "sl-l4",
        "title": "Owns a multi-router service end-to-end and sets API conventions for peers",
        "weight": 4,
    },
    # --- PostgreSQL ---
    {
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l1",
        "title": "Writes correct JOINs, aggregates and parametrised queries",
        "weight": 1,
    },
    {
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l2",
        "title": "Designs normalised schemas with sensible indexes and constraints",
        "weight": 2,
    },
    {
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l3",
        "title": "Reads EXPLAIN ANALYZE output and rewrites queries for measurable speed-ups",
        "weight": 3,
    },
    {
        "competence_key": "c-postgres",
        "skill_level_key": "sl-l4",
        "title": "Plans partitioning, replication and zero-downtime migrations at scale",
        "weight": 4,
    },
    # --- Distributed Systems ---
    {
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l1",
        "title": "Explains idempotency, retries and at-least-once delivery in own words",
        "weight": 1,
    },
    {
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l2",
        "title": "Picks the right queue/cache for a feature and reasons about failure modes",
        "weight": 2,
    },
    {
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l3",
        "title": "Designs eventually-consistent flows with explicit consistency tradeoffs",
        "weight": 3,
    },
    {
        "competence_key": "c-distributed",
        "skill_level_key": "sl-l4",
        "title": "Owns the architecture of a multi-service domain and writes the RFC",
        "weight": 4,
    },
    # --- TypeScript ---
    {
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l1",
        "title": "Adds and reads basic type annotations on functions and components",
        "weight": 1,
    },
    {
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l2",
        "title": "Uses generics, discriminated unions and narrowing across a feature",
        "weight": 2,
    },
    {
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l3",
        "title": "Designs reusable type-safe APIs (zod, schemas, helper types) for the codebase",
        "weight": 3,
    },
    {
        "competence_key": "c-typescript",
        "skill_level_key": "sl-l4",
        "title": "Sets TypeScript conventions and reviews complex type designs across teams",
        "weight": 4,
    },
    # --- React ---
    {
        "competence_key": "c-react",
        "skill_level_key": "sl-l1",
        "title": "Builds small components with hooks and renders props correctly",
        "weight": 1,
    },
    {
        "competence_key": "c-react",
        "skill_level_key": "sl-l2",
        "title": "Manages component state, side effects and data fetching deliberately",
        "weight": 2,
    },
    {
        "competence_key": "c-react",
        "skill_level_key": "sl-l3",
        "title": "Designs server components, streaming and cache boundaries for a feature",
        "weight": 3,
    },
    {
        "competence_key": "c-react",
        "skill_level_key": "sl-l4",
        "title": "Owns the React architecture of a product surface and trains other engineers",
        "weight": 4,
    },
    # --- Web Performance ---
    {
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l1",
        "title": "Reads a Lighthouse report and explains the main metrics",
        "weight": 1,
    },
    {
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l2",
        "title": "Profiles a page, finds the heaviest bundle/route and proposes a fix",
        "weight": 2,
    },
    {
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l3",
        "title": "Owns loading and rendering budgets across a feature and keeps them green",
        "weight": 3,
    },
    {
        "competence_key": "c-web-perf",
        "skill_level_key": "sl-l4",
        "title": "Sets perf SLOs for the product and mentors teams on web vitals tradeoffs",
        "weight": 4,
    },
    # --- User Research ---
    {
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l1",
        "title": "Runs a structured user interview from a prepared guide",
        "weight": 1,
    },
    {
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l2",
        "title": "Synthesises 5–10 interviews into themes that change the roadmap",
        "weight": 2,
    },
    {
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l3",
        "title": "Designs mixed-method research (qual + quant) to size an opportunity",
        "weight": 3,
    },
    {
        "competence_key": "c-user-research",
        "skill_level_key": "sl-l4",
        "title": "Builds the research practice and coaches PMs on customer development",
        "weight": 4,
    },
    # --- Roadmap Prioritization ---
    {
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l1",
        "title": "Maintains a backlog with clear priority labels and owners",
        "weight": 1,
    },
    {
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l2",
        "title": "Sequences a quarter of work against stated team goals and capacity",
        "weight": 2,
    },
    {
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l3",
        "title": "Frames bets and tradeoffs across multiple teams with crisp written rationale",
        "weight": 3,
    },
    {
        "competence_key": "c-roadmap",
        "skill_level_key": "sl-l4",
        "title": "Owns the product strategy narrative and resequences bets when the world changes",
        "weight": 4,
    },
    # --- Design Systems ---
    {
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l1",
        "title": "Uses existing tokens and components without rolling custom variants",
        "weight": 1,
    },
    {
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l2",
        "title": "Contributes a new component with documentation, tokens and a11y baked in",
        "weight": 2,
    },
    {
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l3",
        "title": "Owns a part of the system: governance, deprecations and migrations",
        "weight": 3,
    },
    {
        "competence_key": "c-design-systems",
        "skill_level_key": "sl-l4",
        "title": "Sets the visual system direction and unblocks teams across the company",
        "weight": 4,
    },
    # --- Written Communication ---
    {
        "competence_key": "c-written",
        "skill_level_key": "sl-l1",
        "title": "Writes clear async updates that summarise status, blockers and asks",
        "weight": 1,
    },
    {
        "competence_key": "c-written",
        "skill_level_key": "sl-l2",
        "title": "Authors a one-pager that aligns 3+ stakeholders without a meeting",
        "weight": 2,
    },
    {
        "competence_key": "c-written",
        "skill_level_key": "sl-l3",
        "title": "Ships RFCs and post-mortems that change team decisions",
        "weight": 3,
    },
    {
        "competence_key": "c-written",
        "skill_level_key": "sl-l4",
        "title": "Sets the org-wide writing bar; their docs are the reference others cite",
        "weight": 4,
    },
    # --- Async Collaboration ---
    {
        "competence_key": "c-async",
        "skill_level_key": "sl-l1",
        "title": "Replies in agreed channels within the team SLA and unblocks others",
        "weight": 1,
    },
    {
        "competence_key": "c-async",
        "skill_level_key": "sl-l2",
        "title": "Drives a multi-day decision async without falling back to a call",
        "weight": 2,
    },
    {
        "competence_key": "c-async",
        "skill_level_key": "sl-l3",
        "title": "Designs async workflows (rituals, docs, hand-offs) for a distributed team",
        "weight": 3,
    },
    {
        "competence_key": "c-async",
        "skill_level_key": "sl-l4",
        "title": "Models org-level async norms that scale across timezones and teams",
        "weight": 4,
    },
    # --- Cross-functional Partnership ---
    {
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l1",
        "title": "Partners with design/PM on a feature and surfaces tradeoffs early",
        "weight": 1,
    },
    {
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l2",
        "title": "Co-owns a feature with PM/design from problem framing to launch",
        "weight": 2,
    },
    {
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l3",
        "title": "Resolves disagreements between functions and lands a shared outcome",
        "weight": 3,
    },
    {
        "competence_key": "c-cross-fn",
        "skill_level_key": "sl-l4",
        "title": "Shapes how engineering, product and design collaborate across the org",
        "weight": 4,
    },
    # --- Mentoring ---
    {
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l1",
        "title": "Pairs with a peer to unblock them and writes up what was learned",
        "weight": 1,
    },
    {
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l2",
        "title": "Owns the onboarding of a new hire from week 1 to first independent PR",
        "weight": 2,
    },
    {
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l3",
        "title": "Grows a peer past a promotion bar with deliberate coaching",
        "weight": 3,
    },
    {
        "competence_key": "c-mentoring",
        "skill_level_key": "sl-l4",
        "title": "Builds a mentoring practice that other leads adopt",
        "weight": 4,
    },
    # --- Hiring ---
    {
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l1",
        "title": "Runs a structured interview from a prepared rubric and writes calibrated notes",
        "weight": 1,
    },
    {
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l2",
        "title": "Owns a loop end-to-end and produces a decisive, fair recommendation",
        "weight": 2,
    },
    {
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l3",
        "title": "Designs an interview track and trains other interviewers on calibration",
        "weight": 3,
    },
    {
        "competence_key": "c-hiring",
        "skill_level_key": "sl-l4",
        "title": "Sets the hiring bar for a function and keeps the funnel honest",
        "weight": 4,
    },
    # --- Conflict Resolution ---
    {
        "competence_key": "c-conflict",
        "skill_level_key": "sl-l1",
        "title": "Names a disagreement openly and proposes a path forward",
        "weight": 1,
    },
    {
        "competence_key": "c-conflict",
        "skill_level_key": "sl-l2",
        "title": "Mediates a stuck conversation between two peers to a concrete next step",
        "weight": 2,
    },
    {
        "competence_key": "c-conflict",
        "skill_level_key": "sl-l3",
        "title": "Repairs a strained cross-team relationship after a launch goes wrong",
        "weight": 3,
    },
    {
        "competence_key": "c-conflict",
        "skill_level_key": "sl-l4",
        "title": "Coaches leads through high-stakes conflict; the org trusts them as a neutral",
        "weight": 4,
    },
    # --- Prompt Engineering ---
    {
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l1",
        "title": "Writes specific prompts with role, task and an example output",
        "weight": 1,
    },
    {
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l2",
        "title": "Iterates a prompt against a small eval set and tracks regressions",
        "weight": 2,
    },
    {
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l3",
        "title": "Designs structured prompts (system + examples + checks) for a production flow",
        "weight": 3,
    },
    {
        "competence_key": "c-prompt",
        "skill_level_key": "sl-l4",
        "title": "Owns prompt engineering standards and reviews other teams' prompts",
        "weight": 4,
    },
    # --- AI Tool Adoption ---
    {
        "competence_key": "c-ai-tools",
        "skill_level_key": "sl-l1",
        "title": "Uses an AI assistant for routine drafting and explains the output trust boundary",
        "weight": 1,
    },
    {
        "competence_key": "c-ai-tools",
        "skill_level_key": "sl-l2",
        "title": "Folds AI tools into daily work (review, drafting, search) with measurable savings",
        "weight": 2,
    },
    {
        "competence_key": "c-ai-tools",
        "skill_level_key": "sl-l3",
        "title": "Designs team workflows around AI tools and shares concrete playbooks",
        "weight": 3,
    },
    {
        "competence_key": "c-ai-tools",
        "skill_level_key": "sl-l4",
        "title": "Sets the bar for AI tool adoption across the company",
        "weight": 4,
    },
    # --- Agentic Workflows ---
    {
        "competence_key": "c-agentic",
        "skill_level_key": "sl-l1",
        "title": "Reads a small agent loop and can describe its tools and guardrails",
        "weight": 1,
    },
    {
        "competence_key": "c-agentic",
        "skill_level_key": "sl-l2",
        "title": "Builds a single-task agent with tool use and a basic evaluation",
        "weight": 2,
    },
    {
        "competence_key": "c-agentic",
        "skill_level_key": "sl-l3",
        "title": "Designs multi-step agent flows with explicit guardrails and failure handling",
        "weight": 3,
    },
    {
        "competence_key": "c-agentic",
        "skill_level_key": "sl-l4",
        "title": "Owns the agent platform: orchestration, observability and safety story",
        "weight": 4,
    },
    # --- Customer Discovery ---
    {
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l1",
        "title": "Talks to customers from a script and captures verbatim quotes",
        "weight": 1,
    },
    {
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l2",
        "title": "Runs 10+ discovery calls a quarter and turns them into validated problems",
        "weight": 2,
    },
    {
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l3",
        "title": "Owns a discovery program across segments and informs the roadmap",
        "weight": 3,
    },
    {
        "competence_key": "c-customer-discovery",
        "skill_level_key": "sl-l4",
        "title": "Builds the customer-development muscle for the org",
        "weight": 4,
    },
    # --- OKRs ---
    {
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l1",
        "title": "Drafts team OKRs with measurable outcomes and a clear owner",
        "weight": 1,
    },
    {
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l2",
        "title": "Tracks OKRs weekly and adjusts plans when leading indicators slip",
        "weight": 2,
    },
    {
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l3",
        "title": "Aligns team OKRs with company strategy and re-baselines mid-cycle when needed",
        "weight": 3,
    },
    {
        "competence_key": "c-okrs",
        "skill_level_key": "sl-l4",
        "title": "Designs the OKR process for a function and keeps it honest year over year",
        "weight": 4,
    },
    # --- Sales Discovery ---
    {
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l1",
        "title": "Qualifies a lead against a written ICP and logs notes in the CRM",
        "weight": 1,
    },
    {
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l2",
        "title": "Runs a MEDDIC-style discovery call and identifies the economic buyer",
        "weight": 2,
    },
    {
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l3",
        "title": "Owns a pipeline of enterprise deals with crisp next-step accountability",
        "weight": 3,
    },
    {
        "competence_key": "c-sales-discovery",
        "skill_level_key": "sl-l4",
        "title": "Coaches AEs on discovery and sets the qualification bar for the team",
        "weight": 4,
    },
    {
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l1",
        "title": "Explains the core product value proposition without notes",
        "weight": 1,
    },
    {
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l2",
        "title": "Runs a full product demo tailored to the prospect's industry",
        "weight": 2,
    },
    {
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l3",
        "title": "Answers deep integration and security questions unaided",
        "weight": 3,
    },
    {
        "competence_key": "c-product-knowledge",
        "skill_level_key": "sl-l4",
        "title": "Trains the team on new releases and competitive positioning",
        "weight": 4,
    },
    {
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l1",
        "title": "Acknowledges an objection and restates it before answering",
        "weight": 1,
    },
    {
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l2",
        "title": "Handles common pricing objections with value-based framing",
        "weight": 2,
    },
    {
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l3",
        "title": "Turns competitor comparisons into differentiated next steps",
        "weight": 3,
    },
    {
        "competence_key": "c-objection-handling",
        "skill_level_key": "sl-l4",
        "title": "Builds the team's objection playbook and coaches on live calls",
        "weight": 4,
    },
]


# ---------------------------------------------------------------------------
# Materials (HRP-298)
#
# At least one learning resource per (competence × level on the 3-level
# Basic/Intermediate/Advanced ladder). Without these rows the /competences
# card renders empty under "Materials" and reviewers conclude the seed is
# broken. Format strings line up with the values surfaced by the existing
# materials UI (``book``, ``course``, ``article``, ``video``, ``workshop``).
# ---------------------------------------------------------------------------


def _build_materials() -> list[dict]:
    catalogue: dict[str, tuple[tuple[str, str, str, int], ...]] = {
        "c-python": (
            ("Python Crash Course — language essentials", "book", "external", 480),
            ("Fluent Python — idiomatic patterns", "book", "external", 600),
            ("High Performance Python — profiling & async", "book", "external", 540),
        ),
        "c-fastapi": (
            ("FastAPI official tutorial walkthrough", "course", "external", 240),
            ("Architecting FastAPI services — patterns", "article", "external", 120),
            (
                "FastAPI in production: lifespan, error handling, observability",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-postgres": (
            ("PostgreSQL: Up and Running — chapters 1–5", "book", "external", 360),
            ("Use the Index, Luke — query tuning primer", "article", "external", 180),
            (
                "Designing data-intensive applications — storage chapters",
                "book",
                "external",
                540,
            ),
        ),
        "c-distributed": (
            (
                "Designing Distributed Systems — patterns overview",
                "book",
                "external",
                300,
            ),
            ("Idempotent APIs and at-least-once delivery", "article", "external", 90),
            (
                "Designing Data-Intensive Applications — replication + consistency",
                "book",
                "external",
                540,
            ),
        ),
        "c-typescript": (
            (
                "TypeScript Handbook — narrowing and types basics",
                "course",
                "external",
                240,
            ),
            ("Effective TypeScript — 62 specific ways", "book", "external", 480),
            ("Total TypeScript — advanced patterns", "course", "external", 360),
        ),
        "c-react": (
            ("React docs — thinking in components", "course", "external", 180),
            ("Patterns.dev — React rendering patterns", "article", "external", 180),
            (
                "Next.js streaming + server components deep-dive",
                "workshop",
                "internal",
                240,
            ),
        ),
        "c-web-perf": (
            ("Web Vitals — how to read a Lighthouse report", "article", "external", 60),
            (
                "Smashing Magazine — bundle analysis playbook",
                "article",
                "external",
                120,
            ),
            (
                "Web performance workshops — perf budgets and SLOs",
                "workshop",
                "internal",
                240,
            ),
        ),
        "c-user-research": (
            ("Just Enough Research — Erika Hall", "book", "external", 240),
            ("Continuous Discovery Habits — Teresa Torres", "book", "external", 360),
            ("Mixed-methods research playbook", "workshop", "internal", 240),
        ),
        "c-roadmap": (
            ("Shape Up — Basecamp's approach to scoping", "book", "external", 240),
            (
                "Inspired — How To Create Tech Products Customers Love",
                "book",
                "external",
                480,
            ),
            (
                "Strategy as written narrative — Amazon-style 6-pager",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-design-systems": (
            ("Atomic Design — Brad Frost overview", "article", "external", 90),
            ("Design Systems — Alla Kholmatova", "book", "external", 360),
            (
                "Governance & deprecation playbook for design systems",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-written": (
            ("On Writing Well — Zinsser", "book", "external", 360),
            (
                "Amazon's writing culture: the 6-pager and PR/FAQ",
                "article",
                "external",
                120,
            ),
            (
                "RFCs and post-mortems — writing for decisions",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-async": (
            (
                "How GitLab works fully remote — handbook tour",
                "article",
                "external",
                120,
            ),
            ("Remote — Office Not Required (Basecamp)", "book", "external", 240),
            (
                "Designing async rituals: stand-ups, decisions, hand-offs",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-cross-fn": (
            ("Crucial Conversations — communication baseline", "book", "external", 360),
            (
                "EM/PM/Design triad — shared ownership patterns",
                "article",
                "external",
                120,
            ),
            (
                "Disagree & commit — making cross-functional calls stick",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-mentoring": (
            (
                "The Manager's Path — Camille Fournier (mentoring chapters)",
                "book",
                "external",
                240,
            ),
            ("Onboarding playbook — first 30/60/90 days", "article", "internal", 90),
            (
                "Coaching framework — GROW model in practice",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-hiring": (
            (
                "Structured interviewing 101 — rubric and calibration",
                "article",
                "internal",
                120,
            ),
            ("Who — Geoff Smart's interview method", "book", "external", 300),
            (
                "Designing an interview loop — calibration & bar-raisers",
                "workshop",
                "internal",
                240,
            ),
        ),
        "c-conflict": (
            ("Difficult Conversations — Stone/Patton/Heen", "book", "external", 360),
            ("Mediating peer conflict — frameworks", "article", "external", 120),
            ("High-stakes repair after a launch failure", "workshop", "internal", 180),
        ),
        "c-prompt": (
            ("Anthropic prompt engineering guide", "article", "external", 120),
            (
                "Eval-driven prompt iteration — Promptfoo handbook",
                "course",
                "external",
                180,
            ),
            (
                "Production prompts: system, examples, guardrails",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-ai-tools": (
            (
                "Daily AI workflow — Cursor, Claude Code, Copilot tour",
                "article",
                "internal",
                60,
            ),
            (
                "Measuring AI adoption — leading and lagging indicators",
                "article",
                "internal",
                90,
            ),
            (
                "Team-wide AI playbook — agreed-upon defaults",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-agentic": (
            ("Anatomy of an agent loop — Anthropic primer", "article", "external", 90),
            ("Building a single-task agent with evals", "course", "external", 240),
            (
                "Agent orchestration — observability and safety",
                "workshop",
                "internal",
                240,
            ),
        ),
        "c-customer-discovery": (
            ("The Mom Test — Rob Fitzpatrick", "book", "external", 240),
            ("Continuous Discovery Habits — Teresa Torres", "book", "external", 360),
            ("Cross-segment discovery program design", "workshop", "internal", 180),
        ),
        "c-okrs": (
            ("Measure What Matters — John Doerr", "book", "external", 360),
            (
                "Quarterly OKR rituals — check-ins and re-baselining",
                "article",
                "internal",
                90,
            ),
            ("Designing a function-wide OKR program", "workshop", "internal", 180),
        ),
        "c-sales-discovery": (
            ("MEDDIC and MEDDPICC — qualification primer", "article", "external", 90),
            ("SPIN Selling — Neil Rackham", "book", "external", 360),
            (
                "Coaching AEs on discovery — calibration sessions",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-product-knowledge": (
            ("Product tour — modules, roles and core flows", "course", "internal", 120),
            (
                "Integration and security FAQ — answering hard questions",
                "article",
                "internal",
                90,
            ),
            (
                "Competitive landscape deep-dive — positioning workshop",
                "workshop",
                "internal",
                180,
            ),
        ),
        "c-objection-handling": (
            (
                "Objection handling basics — listen, restate, answer",
                "article",
                "external",
                60,
            ),
            (
                "Value-based selling — pricing conversations that hold",
                "book",
                "external",
                300,
            ),
            (
                "Live-call coaching — objection drills with the team",
                "workshop",
                "internal",
                180,
            ),
        ),
    }
    level_keys = ("sl-l1", "sl-l2", "sl-l3")
    items: list[dict] = []
    for c_key, level_specs in catalogue.items():
        for level_key, (title, fmt, mtype, minutes) in zip(
            level_keys, level_specs, strict=True
        ):
            items.append(
                {
                    "competence_key": c_key,
                    "skill_level_key": level_key,
                    "title": title,
                    "format": fmt,
                    "material_type": mtype,
                    "study_time": minutes,
                }
            )
    return items


MATERIALS: list[dict] = _build_materials()
