"""Company-structure fixtures for the demo seed (HRP-281 — S1).

Sits next to ``seed_data.py`` (the recruitment-only fixtures from
HRP-250) and gets imported by ``seed.py`` to populate:

* tenant-scoped ``dictionary_items`` rows for specializations and
  grades (the unified DictionaryItem catalog uses ``type`` to namespace
  by domain);
* the ``company.Division`` tree;
* ``position.Position`` rows tied to division/spec/grade;
* ``grade_system.GradeSpecialization`` ladder cells.

All literals are deliberately static (no AI-generation at seed time)
and authored in English — the single structural source. White-label
deployments localize display strings at clone time via the
``seed_i18n`` catalog overlay; join-key titles (``GRADES`` resolve
origin rows by name) are excluded from that overlay. Sales is kept
as a specialization but without a grade ladder, per the S0 plan call
with Maxim (2026-06-16).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------
#
# Tree shape (parent_key → children):
#   Engineering → Backend / Frontend / Platform
#   Product (flat)
#   Design (flat)
#   People & Talent (flat)
#   Go-to-Market (flat)
#
# Order matters: parents come before children so the seeder can resolve
# ``parent_key`` via a name → id map built incrementally.

DIVISIONS: list[dict] = [
    {
        "key": "engineering",
        "name": "Engineering",
        "description": "Builds and operates the HRPulsar platform.",
        "parent_key": None,
    },
    {
        "key": "eng-backend",
        "name": "Engineering / Backend",
        "description": "Services, data, AI pipelines.",
        "parent_key": "engineering",
    },
    {
        "key": "eng-frontend",
        "name": "Engineering / Frontend",
        "description": "Web app, recruiter SPA, admin surfaces.",
        "parent_key": "engineering",
    },
    {
        "key": "eng-platform",
        "name": "Engineering / Platform",
        "description": "Infra, deploys, observability, security.",
        "parent_key": "engineering",
    },
    {
        "key": "product",
        "name": "Product",
        "description": "Discovery, prioritisation, roadmap.",
        "parent_key": None,
    },
    {
        "key": "design",
        "name": "Design",
        "description": "Product design and design systems.",
        "parent_key": None,
    },
    {
        "key": "people",
        "name": "People & Talent",
        "description": "HR ops, recruiting, L&D.",
        "parent_key": None,
    },
    {
        "key": "gtm",
        "name": "Go-to-Market",
        "description": "Sales, customer success, marketing.",
        "parent_key": None,
    },
]


# ---------------------------------------------------------------------------
# Specializations  (DictionaryItem type='specialization', tenant-scoped)
# ---------------------------------------------------------------------------

SPECIALIZATIONS: list[dict] = [
    {
        "key": "backend-dev",
        "title": "Backend Development",
        "description": "Server-side engineering: APIs, data, async pipelines.",
    },
    {
        "key": "frontend-dev",
        "title": "Frontend Development",
        "description": "Web UI, design-system fluency, performance budgets.",
    },
    {
        "key": "product-mgmt",
        "title": "Product Management",
        "description": "Discovery, roadmap, outcome measurement.",
    },
    {
        "key": "product-design",
        "title": "Product Design",
        "description": "Interaction, visual, research-driven design.",
    },
    {
        "key": "sales",
        "title": "Sales",
        "description": "Outbound, enterprise accounts, expansion.",
    },
]


# ---------------------------------------------------------------------------
# Grades  (DictionaryItem type='grade', tenant-scoped)
# ---------------------------------------------------------------------------

GRADES: list[dict] = [
    {"key": "g-junior", "title": "Junior", "sort_index": 10},
    {"key": "g-middle", "title": "Middle", "sort_index": 20},
    {"key": "g-senior", "title": "Senior", "sort_index": 30},
    {"key": "g-lead", "title": "Lead", "sort_index": 40},
    {"key": "g-principal", "title": "Principal", "sort_index": 50},
]


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------
#
# Each position references a division by ``division_key``, a
# specialization by ``specialization_key``, and a grade by
# ``grade_key`` — all resolved at seed time. ``headcount`` is the
# nominal target headcount for the position; the actual employee
# allocation in S3 may be lower.

POSITIONS: list[dict] = [
    # --- Backend ladder ---
    {
        "key": "p-be-l1",
        "title": "Backend Engineer L1",
        "division_key": "eng-backend",
        "specialization_key": "backend-dev",
        "grade_key": "g-junior",
        "headcount": 2,
        "description": "Junior backend engineer. Owns small features under guidance.",
    },
    {
        "key": "p-be-l2",
        "title": "Backend Engineer L2",
        "division_key": "eng-backend",
        "specialization_key": "backend-dev",
        "grade_key": "g-middle",
        "headcount": 3,
        "description": "Middle backend engineer. Independent feature ownership.",
    },
    {
        "key": "p-be-l3",
        "title": "Backend Engineer L3",
        "division_key": "eng-backend",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "headcount": 3,
        "description": "Senior backend engineer. Cross-team systems work.",
    },
    {
        "key": "p-be-l4",
        "title": "Backend Engineer L4 — Staff",
        "division_key": "eng-backend",
        "specialization_key": "backend-dev",
        "grade_key": "g-lead",
        "headcount": 1,
        "description": "Staff backend engineer. Domain-wide architecture.",
    },
    # --- Frontend ladder ---
    {
        "key": "p-fe-l1",
        "title": "Frontend Engineer L1",
        "division_key": "eng-frontend",
        "specialization_key": "frontend-dev",
        "grade_key": "g-junior",
        "headcount": 1,
        "description": "Junior frontend engineer.",
    },
    {
        "key": "p-fe-l2",
        "title": "Frontend Engineer L2",
        "division_key": "eng-frontend",
        "specialization_key": "frontend-dev",
        "grade_key": "g-middle",
        "headcount": 2,
        "description": "Middle frontend engineer. Owns components and flows.",
    },
    {
        "key": "p-fe-l3",
        "title": "Frontend Engineer L3",
        "division_key": "eng-frontend",
        "specialization_key": "frontend-dev",
        "grade_key": "g-senior",
        "headcount": 2,
        "description": "Senior frontend engineer. Cross-feature architecture.",
    },
    # --- Engineering management ---
    {
        "key": "p-em-backend",
        "title": "Engineering Manager — Backend",
        "division_key": "eng-backend",
        "specialization_key": "backend-dev",
        "grade_key": "g-lead",
        "headcount": 1,
        "description": "Backend EM. People + delivery + tech direction.",
    },
    {
        "key": "p-em-frontend",
        "title": "Engineering Manager — Frontend",
        "division_key": "eng-frontend",
        "specialization_key": "frontend-dev",
        "grade_key": "g-lead",
        "headcount": 1,
        "description": "Frontend EM.",
    },
    {
        "key": "p-em-platform",
        "title": "Engineering Manager — Platform",
        "division_key": "eng-platform",
        "specialization_key": "backend-dev",
        "grade_key": "g-lead",
        "headcount": 1,
        "description": "Platform EM. Infra, deploys, SRE.",
    },
    # --- Product ---
    {
        "key": "p-pm-mid",
        "title": "Product Manager",
        "division_key": "product",
        "specialization_key": "product-mgmt",
        "grade_key": "g-middle",
        "headcount": 3,
        "description": "Owns a product area end-to-end.",
    },
    {
        "key": "p-pm-senior",
        "title": "Senior Product Manager",
        "division_key": "product",
        "specialization_key": "product-mgmt",
        "grade_key": "g-senior",
        "headcount": 2,
        "description": "Senior PM. Leads cross-area initiatives.",
    },
    # --- Design ---
    {
        "key": "p-designer-mid",
        "title": "Product Designer",
        "division_key": "design",
        "specialization_key": "product-design",
        "grade_key": "g-middle",
        "headcount": 2,
        "description": "Product designer.",
    },
    {
        "key": "p-designer-senior",
        "title": "Senior Product Designer",
        "division_key": "design",
        "specialization_key": "product-design",
        "grade_key": "g-senior",
        "headcount": 2,
        "description": "Senior designer. Owns design system.",
    },
    # --- People & Talent ---
    {
        "key": "p-people-partner",
        "title": "People Partner",
        "division_key": "people",
        "specialization_key": "product-mgmt",
        "grade_key": "g-senior",
        "headcount": 2,
        "description": "HRBP for an engineering or business org.",
    },
    {
        "key": "p-recruiter",
        "title": "Recruiter",
        "division_key": "people",
        "specialization_key": "product-mgmt",
        "grade_key": "g-middle",
        "headcount": 3,
        "description": "Owns sourcing and screening for assigned roles.",
    },
    # --- Go-to-Market ---
    {
        "key": "p-ae",
        "title": "Account Executive",
        "division_key": "gtm",
        "specialization_key": "sales",
        "grade_key": "g-senior",
        "headcount": 3,
        "description": "Owns enterprise accounts.",
    },
    {
        "key": "p-sdr",
        "title": "Sales Development Representative",
        "division_key": "gtm",
        "specialization_key": "sales",
        "grade_key": "g-junior",
        "headcount": 4,
        "description": "Outbound prospecting.",
    },
]


# ---------------------------------------------------------------------------
# Grade ladders  (grade × specialization with salary band)
# ---------------------------------------------------------------------------
#
# Salary numbers are in EUR-equivalent low-thousands so the demo
# tenant doesn't anchor on a single market. ``passing_score`` is the
# percent of competence coverage required to be considered for the
# grade. Sales is intentionally absent (see S0 decision).

GRADE_SPECIALIZATIONS: list[dict] = [
    # Backend
    {
        "grade_key": "g-junior",
        "specialization_key": "backend-dev",
        "salary_min": 38000,
        "salary_max": 52000,
        "passing_score": 60,
        "description": "Junior Backend Engineer ladder cell.",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "backend-dev",
        "salary_min": 55000,
        "salary_max": 75000,
        "passing_score": 70,
        "description": "Middle Backend Engineer ladder cell.",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "backend-dev",
        "salary_min": 80000,
        "salary_max": 105000,
        "passing_score": 75,
        "description": "Senior Backend Engineer ladder cell.",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "backend-dev",
        "salary_min": 105000,
        "salary_max": 135000,
        "passing_score": 80,
        "description": "Lead Backend Engineer ladder cell.",
    },
    # Frontend
    {
        "grade_key": "g-junior",
        "specialization_key": "frontend-dev",
        "salary_min": 36000,
        "salary_max": 50000,
        "passing_score": 60,
        "description": "Junior Frontend Engineer ladder cell.",
    },
    {
        "grade_key": "g-middle",
        "specialization_key": "frontend-dev",
        "salary_min": 52000,
        "salary_max": 72000,
        "passing_score": 70,
        "description": "Middle Frontend Engineer ladder cell.",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "frontend-dev",
        "salary_min": 78000,
        "salary_max": 100000,
        "passing_score": 75,
        "description": "Senior Frontend Engineer ladder cell.",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "frontend-dev",
        "salary_min": 100000,
        "salary_max": 130000,
        "passing_score": 80,
        "description": "Lead Frontend Engineer ladder cell.",
    },
    # Product Management
    {
        "grade_key": "g-middle",
        "specialization_key": "product-mgmt",
        "salary_min": 60000,
        "salary_max": 80000,
        "passing_score": 70,
        "description": "Product Manager ladder cell.",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-mgmt",
        "salary_min": 85000,
        "salary_max": 110000,
        "passing_score": 75,
        "description": "Senior Product Manager ladder cell.",
    },
    {
        "grade_key": "g-lead",
        "specialization_key": "product-mgmt",
        "salary_min": 110000,
        "salary_max": 140000,
        "passing_score": 80,
        "description": "Product Lead ladder cell.",
    },
    # Product Design
    {
        "grade_key": "g-middle",
        "specialization_key": "product-design",
        "salary_min": 55000,
        "salary_max": 75000,
        "passing_score": 70,
        "description": "Product Designer ladder cell.",
    },
    {
        "grade_key": "g-senior",
        "specialization_key": "product-design",
        "salary_min": 80000,
        "salary_max": 105000,
        "passing_score": 75,
        "description": "Senior Product Designer ladder cell.",
    },
]


# Marker for tenant-scoped DictionaryItem.metadata_ so the seeder can
# tell which rows it has previously inserted (idempotency belt-and-
# braces — the primary guard is still ``_already_seeded`` on Candidate).
DEMO_SEED_METADATA_MARKER = {"demo_seed": "company-structure"}
