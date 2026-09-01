"""Talent Market fixtures for the demo seed (HRP-281 — S6, HRP-664).

Six TalentCard rows covering every TalentCard.status value
(draft / published / completed / cancelled) plus a published card
with an appointed candidate, so the /talent-market index has chips
in every column.

Each card carries:

* 1..2 ``TalentCardSpecialization`` rows (spec × grade)
* 2..3 ``TalentCardCompetence`` rows (competence × skill_level)
* 1..2 ``TalentCardRequirement`` rows (free-text constraint)
* 0..3 ``TalentCandidate`` rows from the seeded employee pool with
  ``status`` distributed across matched / not_matched / appointed

HRP-664 — the fixture must agree with the product's own matcher.
Two invariants hold here, and breaking either makes the demo lie:

1. **Required competences are ones the demo actually assesses.**
   ``matching._comp_percent_from_map`` averages across *every*
   required row and scores a competence with no ``done`` assessment
   as 0, so a card asking for competences nobody was assessed on
   caps every candidate in the twenties. Only the competences in
   ``seed_data_assessments.ASSESSMENTS`` (python / postgres /
   distributed / mentoring / typescript / react / design-systems /
   web-perf / product-knowledge / objection-handling /
   sales-discovery) can carry a card.

2. **A spec ``min_years`` must fit the seeded tenure.** HRP-682
   gives every demo employee one ``WorkExperience`` spell starting
   on their hire date, so ``_employee_spec_match`` measures a real
   tenure instead of falling back to HRP-210's current-position
   check. The floor is therefore honest but unforgiving: a spec
   asking for more years than ``hire_days_back`` grants the card's
   matched candidates prunes them on the first recompute. Regular
   demo hires sit between ~2 and ~6.5 years. The free-text
   ``requirements`` below carry years of their own; the matcher
   never reads those, they are recruiter-facing prose.

3. **A ``talent`` card has to find a gap.** The type exists to feed
   development plans, and the drawer only offers "Create development
   plan" when a candidate is short on a Required Competence. Its
   roster must therefore clear the Match% bar *and* stay under it on
   at least one required row — pinned by
   ``test_seed_talent_card_leaves_a_gap_to_plan_for``.

``match_score`` on each candidate is the value the matcher computes
on the seeded tenant, not a decorative number: pressing "Recompute"
on a card must leave the roster and the percentages exactly where the
seed put them.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Talent cards
# ---------------------------------------------------------------------------

TALENT_CARDS: list[dict] = [
    # --- Vacancy: an open headcount. The whole point of the type is the
    # ranked shortlist, so this card carries the demo's clearest
    # "fits / does not fit, and here is why" split.
    {
        "key": "tc-platform-arch",
        "title": "Platform Architect — open role",
        "description": (
            "Open headcount on the Platform team — we fill it from inside "
            "before posting it outside. Senior and Lead backend engineers "
            "are ranked against the required competencies."
        ),
        "card_type": "vacancy",
        "status": "published",
        "division_key": "eng-platform",
        "match_percent": 75,
        "specializations": [
            {"specialization_key": "backend-dev", "grade_key": "g-lead", "min_years": 2},
            {"specialization_key": "backend-dev", "grade_key": "g-senior", "min_years": 2},
        ],
        "competences": [
            {"competence_key": "c-python", "skill_level_key": "sl-l3"},
            {"competence_key": "c-distributed", "skill_level_key": "sl-l3"},
        ],
        "requirements": [
            {"description": "Hands-on with Kubernetes or comparable orchestrator", "min_years": 3},
            {"description": "Comfortable owning the on-call rotation playbook", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 1, "status": "matched", "match_score": 84},  # Bella Martins
            {"employee_index": 2, "status": "matched", "match_score": 78},  # Carlos Mendez
            {"employee_index": 8, "status": "not_matched", "match_score": 73},  # Ivan Petrov
        ],
    },
    # --- Vacancy: the same type seen from the GTM side, and the card
    # that pays off the dashboard's headline problem (HRP-661) — the
    # sellers who scored below the bar on product knowledge are the same
    # ones who miss the bar here.
    {
        "key": "tc-ae-dach",
        "title": "Senior Account Executive — DACH",
        "description": (
            "One open seat on the DACH team. Two of the three account "
            "executives clear the three-year experience floor; only one of "
            "them clears the competency bar — the others get a named gap "
            "instead of a rejection."
        ),
        "card_type": "vacancy",
        "status": "published",
        "division_key": "gtm",
        "match_percent": 75,
        "specializations": [
            {"specialization_key": "sales", "grade_key": "g-senior", "min_years": 3},
        ],
        "competences": [
            {"competence_key": "c-sales-discovery", "skill_level_key": "sl-l3"},
            {"competence_key": "c-objection-handling", "skill_level_key": "sl-l3"},
        ],
        "requirements": [
            {"description": "Available in EU timezones for cross-team standup", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 33, "status": "matched", "match_score": 88},  # Hannah Adler
            {"employee_index": 34, "status": "not_matched", "match_score": 73},  # Igor Sokolov
            {"employee_index": 35, "status": "not_matched", "match_score": 36},  # Jana Vargas
        ],
    },
    # --- Project: a time-boxed initiative rather than a headcount. The
    # appointed lead keeps their job; the card exists to staff the work.
    {
        "key": "tc-design-system-lead",
        "title": "Design System Lead — recruiter SPA",
        "description": (
            "A time-boxed initiative, not a headcount: people keep their jobs "
            "and join for the rollout. A lead is already appointed; the "
            "matcher surfaces who else could staff it."
        ),
        "card_type": "project",
        "status": "published",
        "division_key": "design",
        "match_percent": 80,
        "specializations": [
            {"specialization_key": "product-design", "grade_key": "g-senior", "min_years": 3},
            {"specialization_key": "frontend-dev", "grade_key": "g-senior", "min_years": 3},
        ],
        "competences": [
            {"competence_key": "c-design-systems", "skill_level_key": "sl-l3"},
            {"competence_key": "c-react", "skill_level_key": "sl-l3"},
        ],
        "requirements": [
            {"description": "Cross-team alignment with Frontend EM + Senior PMs", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 24, "status": "appointed", "match_score": 88},  # Yara Saito
            {"employee_index": 13, "status": "matched", "match_score": 82},  # Nadia Hassan
        ],
    },
    # --- Project: the same type at the other end of its life, so the
    # index shows what a finished initiative leaves behind.
    {
        "key": "tc-eu-onboarding",
        "title": "EU customer onboarding project",
        "description": (
            "Closed successfully — the onboarding playbook shipped and the "
            "task force went back to their teams. The card stays as the "
            "record of who ran it."
        ),
        "card_type": "project",
        "status": "completed",
        "division_key": "gtm",
        "match_percent": 75,
        "specializations": [
            {"specialization_key": "sales", "grade_key": "g-senior", "min_years": 3},
        ],
        "competences": [
            {"competence_key": "c-sales-discovery", "skill_level_key": "sl-l3"},
            {"competence_key": "c-product-knowledge", "skill_level_key": "sl-l3"},
        ],
        "requirements": [
            {"description": "Available in EU timezones for cross-team standup", "min_years": None},
        ],
        "candidates": [
            {"employee_index": 33, "status": "appointed", "match_score": 88},  # Hannah Adler
            {"employee_index": 34, "status": "not_matched", "match_score": 61},  # Igor Sokolov
        ],
    },
    # --- Talent: no open headcount at all — a bench kept warm against a
    # role we expect to need. The gaps it finds are the input to a
    # development plan, which is what separates it from a vacancy.
    {
        "key": "tc-em-frontend",
        "title": "Engineering Manager — Frontend backfill (draft)",
        "description": (
            "No open headcount yet: a bench of people who could grow into the "
            "Frontend EM role. The gaps found here become development plans "
            "long before the vacancy opens."
        ),
        "card_type": "talent",
        "status": "draft",
        "division_key": "eng-frontend",
        "match_percent": 80,
        "specializations": [
            {"specialization_key": "frontend-dev", "grade_key": "g-senior", "min_years": 3},
        ],
        # Design systems at L3 is what the Frontend *Lead* ladder asks for
        # (see SPECIALIZATION_COMPETENCES) and it is the one required row
        # the bench candidate is short on: the card's promise is that the
        # gaps it finds become development plans, so it has to find one.
        # Without it the only candidate cleared every requirement and the
        # drawer said "Meets every requirement" with no plan to create.
        "competences": [
            {"competence_key": "c-react", "skill_level_key": "sl-l3"},
            {"competence_key": "c-typescript", "skill_level_key": "sl-l3"},
            {"competence_key": "c-design-systems", "skill_level_key": "sl-l3"},
        ],
        "requirements": [
            {"description": "Comfortable running a 5-7 person org", "min_years": 2},
        ],
        "candidates": [
            {"employee_index": 13, "status": "matched", "match_score": 85},  # Nadia Hassan
        ],
    },
    # --- Talent: cancelled before the matcher ever ran, which is why it
    # carries no candidates. Nobody in People has a done assessment, so
    # any roster here would be a number the product cannot reproduce.
    {
        "key": "tc-cancelled-recruiter-pool",
        "title": "Recruiter pool — Q4 expansion",
        "description": (
            "Cancelled before anyone was matched — the pool requirement was "
            "absorbed into the regular recruiter ladder."
        ),
        "card_type": "talent",
        "status": "cancelled",
        "division_key": "people",
        "match_percent": 70,
        "specializations": [
            {"specialization_key": "product-mgmt", "grade_key": "g-middle"},
        ],
        "competences": [
            {"competence_key": "c-hiring", "skill_level_key": "sl-l2"},
            {"competence_key": "c-async", "skill_level_key": "sl-l2"},
        ],
        "requirements": [
            {"description": "Bilingual EN + DE or EN + ES preferred", "min_years": None},
        ],
        "candidates": [],
    },
]
