"""Talent Market fixtures for the demo seed (HRP-281 — S6).

Six TalentCard rows covering every TalentCard.status value
(draft / published / completed / cancelled) plus a published card
with an appointed candidate, so the /talent-market index has chips
in every column.

Each card carries:

* 1..2 ``TalentCardSpecialization`` rows (spec × grade × min years)
* 3..4 ``TalentCardCompetence`` rows (competence × skill_level)
* 1..2 ``TalentCardRequirement`` rows (free-text constraint)
* 2..3 ``TalentCandidate`` rows from the seeded employee pool with
  ``status`` distributed across matched / not_matched / appointed
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Talent cards
# ---------------------------------------------------------------------------

TALENT_CARDS: list[dict] = [
    {
        "key": "tc-platform-arch",
        "title": "Platform Architect — internal pool",
        "description": (
            "Looking for a senior platform-minded engineer to take over the "
            "deploy and infra hardening initiative for the next two quarters."
        ),
        "card_type": "vacancy",
        "status": "published",
        "division_key": "eng-platform",
        "match_percent": 75,
        "specializations": [
            {"specialization_key": "backend-dev", "grade_key": "g-lead", "min_years": 6},
        ],
        "competences": [
            {"competence_key": "c-distributed", "skill_level_key": "sl-l3", "match_percent": 90},
            {"competence_key": "c-postgres", "skill_level_key": "sl-l3", "match_percent": 85},
            {"competence_key": "c-mentoring", "skill_level_key": "sl-l2", "match_percent": 70},
        ],
        "requirements": [
            {"description": "Hands-on with Kubernetes or comparable orchestrator", "min_years": 3},
            {"description": "Comfortable owning the on-call rotation playbook", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 7, "status": "matched", "match_score": 88},  # Hana Okafor
            {"employee_index": 8, "status": "matched", "match_score": 82},  # Ivan Petrov
            {"employee_index": 1, "status": "not_matched", "match_score": 64},  # Bella Martins
        ],
    },
    {
        "key": "tc-ai-eng",
        "title": "AI Workflow Engineer",
        "description": (
            "Hybrid product/eng role to push the AI fluency methodology into the "
            "recruitment + assessment surfaces."
        ),
        "card_type": "vacancy",
        "status": "published",
        "division_key": "eng-backend",
        "match_percent": 70,
        "specializations": [
            {"specialization_key": "backend-dev", "grade_key": "g-senior", "min_years": 4},
        ],
        "competences": [
            {"competence_key": "c-prompt", "skill_level_key": "sl-l3", "match_percent": 95},
            {"competence_key": "c-agentic", "skill_level_key": "sl-l2", "match_percent": 80},
            {"competence_key": "c-python", "skill_level_key": "sl-l3", "match_percent": 85},
            {"competence_key": "c-cross-fn", "skill_level_key": "sl-l2", "match_percent": 70},
        ],
        "requirements": [
            {"description": "Shipped at least one production agentic workflow", "min_years": 1},
        ],
        "candidates": [
            {"employee_index": 2, "status": "matched", "match_score": 91},  # Carlos
            {"employee_index": 3, "status": "matched", "match_score": 87},  # Daria
            {"employee_index": 4, "status": "not_matched", "match_score": 58},  # Ethan
        ],
    },
    {
        "key": "tc-design-system-lead",
        "title": "Design System Lead — recruiter SPA",
        "description": (
            "Already appointed — Yara is taking the spike on the new design tokens "
            "rollout starting next sprint."
        ),
        "card_type": "project",
        "status": "published",
        "division_key": "design",
        "match_percent": 80,
        "specializations": [
            {"specialization_key": "product-design", "grade_key": "g-senior", "min_years": 5},
            {"specialization_key": "frontend-dev", "grade_key": "g-senior", "min_years": 3},
        ],
        "competences": [
            {"competence_key": "c-design-systems", "skill_level_key": "sl-l3", "match_percent": 95},
            {"competence_key": "c-react", "skill_level_key": "sl-l2", "match_percent": 80},
            {"competence_key": "c-mentoring", "skill_level_key": "sl-l2", "match_percent": 75},
        ],
        "requirements": [
            {"description": "Cross-team alignment with Frontend EM + Senior PMs", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 24, "status": "appointed", "match_score": 95},  # Yara Saito
            {"employee_index": 25, "status": "matched", "match_score": 86},  # Zoe Caron
            {"employee_index": 11, "status": "not_matched", "match_score": 60},  # Leila Karam (EM-FE)
        ],
    },
    {
        "key": "tc-eu-onboarding",
        "title": "EU customer onboarding project",
        "description": (
            "Closed successfully — onboarding playbook v1 was delivered by Hannah's "
            "small task force last quarter."
        ),
        "card_type": "project",
        "status": "completed",
        "division_key": "gtm",
        "match_percent": 80,
        "specializations": [
            {"specialization_key": "sales", "grade_key": "g-senior", "min_years": 4},
        ],
        "competences": [
            {"competence_key": "c-sales-discovery", "skill_level_key": "sl-l3", "match_percent": 90},
            {"competence_key": "c-customer-discovery", "skill_level_key": "sl-l2", "match_percent": 80},
            {"competence_key": "c-written", "skill_level_key": "sl-l3", "match_percent": 75},
        ],
        "requirements": [
            {"description": "Available in EU timezones for cross-team standup", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 33, "status": "appointed", "match_score": 92},  # Hannah Adler
            {"employee_index": 34, "status": "matched", "match_score": 79},  # Igor Sokolov
        ],
    },
    {
        "key": "tc-em-frontend",
        "title": "Engineering Manager — Frontend backfill (draft)",
        "description": (
            "Draft card while we evaluate whether to backfill Leila's previous role "
            "or merge it with Platform EM."
        ),
        "card_type": "talent",
        "status": "draft",
        "division_key": "eng-frontend",
        "match_percent": 80,
        "specializations": [
            {"specialization_key": "frontend-dev", "grade_key": "g-lead", "min_years": 6},
        ],
        "competences": [
            {"competence_key": "c-react", "skill_level_key": "sl-l4", "match_percent": 90},
            {"competence_key": "c-hiring", "skill_level_key": "sl-l2", "match_percent": 75},
        ],
        "requirements": [
            {"description": "Comfortable running a 5-7 person org", "min_years": 2},
        ],
        "candidates": [
            {"employee_index": 12, "status": "matched", "match_score": 84},  # Marcus Johnson
        ],
    },
    {
        "key": "tc-cancelled-recruiter-pool",
        "title": "Recruiter pool — Q4 expansion",
        "description": "Cancelled — pool requirement absorbed into the regular recruiter ladder.",
        "card_type": "talent",
        "status": "cancelled",
        "division_key": "people",
        "match_percent": 70,
        "specializations": [
            {"specialization_key": "product-mgmt", "grade_key": "g-middle", "min_years": 2},
        ],
        "competences": [
            {"competence_key": "c-hiring", "skill_level_key": "sl-l2", "match_percent": 75},
            {"competence_key": "c-async", "skill_level_key": "sl-l2", "match_percent": 65},
        ],
        "requirements": [
            {"description": "Bilingual EN + DE or EN + ES preferred", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 30, "status": "not_matched", "match_score": 55},  # Emil Krause
            {"employee_index": 31, "status": "not_matched", "match_score": 50},  # Farah Khoury
        ],
    },
]
