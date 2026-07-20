"""Assessment cycle + PDP fixtures for the demo seed (HRP-281 — S4, HRP-314).

Minimal-but-complete enough to make the /assessments and /pdp pages
non-empty and surface every status in the kanban filters:

- Assessments span draft / in_progress / done / cancelled (status
  codes come from the origin assessment_statuses table seeded by
  migration ``c3fc300775f8``).
- PDPs span draft / in_progress / review / returned / done /
  cancelled (string enum on PDP.status, see
  ``pdp_service.PDP_STATUS_TRANSITIONS``).

Each assessment spec carries an explicit ``criteria_type`` (one of
``competences`` / ``target_position`` / ``current_positions``) — this
matches ``CriteriaUpdate.criteria_type`` and is required for the
Draft → Sent transition (``service.py::_assert_transitions`` checks
``criteria_type IS NOT NULL``). All current demo specs use
``competences`` so the explicit ``competence_keys`` list resolves
directly to AssessmentCompetence rows.

For 180/360 cycles the chosen ``employee_index`` MUST belong to a
sub-division (not a division_head), otherwise ``Division.manager_id``
points at the assessee themselves and the demo loses its manager-
participant.

``result_overrides`` is consumed only for done assessments — each
entry is ``(competence_key, avg_score_0_4, percent_0_100)`` and
produces one AssessmentResult row.

``employee_index`` fields refer to indices into the EMPLOYEE_ASSIGNMENTS
list (i.e. NAME_POOL) so the same seed run picks deterministic
employees without coupling to ID generation order.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

ASSESSMENTS: list[dict] = [
    # --- Done (with results) ---
    {
        "title": "Q4 360° review — Carlos Mendez",
        "employee_index": 2,  # Carlos Mendez, Backend L3 → manager Adam Kovacs (idx 0)
        "type_code": "360",
        "status_code": "done",
        "criteria_type": "competences",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "competence_keys": ["c-python", "c-postgres", "c-distributed", "c-mentoring"],
        "result_overrides": [
            ("c-python", 3.4, 85),
            ("c-postgres", 3.1, 78),
            ("c-distributed", 2.8, 70),
            ("c-mentoring", 3.0, 75),
        ],
    },
    {
        "title": "Q4 360° review — Nadia Hassan",
        "employee_index": 13,  # Nadia Hassan, Frontend L3 → manager Leila Karam (idx 11)
        "type_code": "360",
        "status_code": "done",
        "criteria_type": "competences",
        "specialization_key": "frontend-dev",
        "grade_key": "g-senior",
        "competence_keys": ["c-typescript", "c-react", "c-design-systems", "c-web-perf"],
        "result_overrides": [
            ("c-typescript", 3.6, 90),
            ("c-react", 3.5, 88),
            ("c-design-systems", 3.0, 75),
            ("c-web-perf", 2.7, 68),
        ],
    },
    # --- In progress (sent, awaiting answers) ---
    {
        "title": "Mid-year self assessment — Daria Volkova",
        "employee_index": 3,  # Daria Volkova
        "type_code": "self",
        "status_code": "in_progress",
        "criteria_type": "competences",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "competence_keys": ["c-python", "c-fastapi", "c-prompt"],
        "result_overrides": [],
    },
    {
        # Theo Bauer (idx 19) is a Senior PM under Sara Lindberg (idx 18 =
        # division_head Product). 180° needs a Division Manager who isn't
        # the assessee themselves — Sara would self-resolve and the cycle
        # would land without a manager-participant.
        "title": "Mid-year 180° review — Theo Bauer",
        "employee_index": 19,
        "type_code": "180",
        "status_code": "in_progress",
        "criteria_type": "competences",
        "specialization_key": "product-mgmt",
        "grade_key": "g-senior",
        "competence_keys": ["c-user-research", "c-roadmap", "c-cross-fn"],
        "result_overrides": [],
    },
    # --- Draft (not yet sent) ---
    {
        "title": "Q1 360° plan — Engineering Backend",
        "employee_index": 4,  # Ethan Williams, Backend L2 → manager Adam Kovacs (idx 0)
        "type_code": "360",
        "status_code": "draft",
        "criteria_type": "competences",
        "specialization_key": "backend-dev",
        "grade_key": "g-middle",
        "competence_keys": ["c-python", "c-fastapi", "c-postgres"],
        "result_overrides": [],
    },
    {
        "title": "Q1 self assessment — Yara Saito",
        "employee_index": 24,  # Yara Saito, Senior Designer (division_head — fine for self)
        "type_code": "self",
        "status_code": "draft",
        "criteria_type": "competences",
        "specialization_key": "product-design",
        "grade_key": "g-senior",
        "competence_keys": ["c-design-systems", "c-user-research"],
        "result_overrides": [],
    },
    # --- Cancelled ---
    {
        "title": "Cancelled — was duplicated assignment",
        "employee_index": 7,  # Hana Okafor, Platform → manager Gabriel Santos (idx 6)
        "type_code": "360",
        "status_code": "cancelled",
        "criteria_type": "competences",
        "specialization_key": "backend-dev",
        "grade_key": "g-lead",
        "competence_keys": ["c-python", "c-distributed"],
        "result_overrides": [],
    },
]


# ---------------------------------------------------------------------------
# Personal Development Plans
# ---------------------------------------------------------------------------
#
# Each PDP has an ``items`` list — every entry becomes one PDPItem row.

PDPS: list[dict] = [
    # --- Active (in_progress) ---
    {
        "title": "Growth path Q1–Q2 — Marcus Johnson",
        "employee_index": 12,  # Marcus Johnson, Frontend L3
        "status": "in_progress",
        "specialization_key": "frontend-dev",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-design-systems", "title": "Own a design system migration to v2 tokens", "is_passed": True},
            {"competence_key": "c-mentoring", "title": "Mentor two Frontend L1 hires through onboarding", "is_passed": False},
            {"competence_key": "c-written", "title": "Ship one RFC + post-mortem per quarter", "is_passed": False},
        ],
    },
    {
        "title": "Growth path Q1–Q2 — Daria Volkova",
        "employee_index": 3,
        "status": "in_progress",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-distributed", "title": "Lead the settlement reconciliation redesign", "is_passed": False},
            {"competence_key": "c-prompt", "title": "Adopt the AI code review workflow on PRs", "is_passed": True},
            {"competence_key": "c-mentoring", "title": "Pair-program weekly with a Backend L2", "is_passed": False},
        ],
    },
    {
        "title": "Growth path Q1–Q2 — Theo Bauer",
        "employee_index": 19,  # Theo Bauer, Senior PM
        "status": "in_progress",
        "specialization_key": "product-mgmt",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-customer-discovery", "title": "Run 12 enterprise discovery calls this quarter", "is_passed": False},
            {"competence_key": "c-okrs", "title": "Re-baseline team OKRs against new strategy", "is_passed": True},
        ],
    },
    # --- Under review ---
    {
        "title": "Plan in review — Ethan Williams",
        "employee_index": 4,
        "status": "review",
        "specialization_key": "backend-dev",
        "grade_key": "g-middle",
        "items": [
            {"competence_key": "c-python", "title": "Reach L2 Practitioner on the Python rubric", "is_passed": False},
            {"competence_key": "c-postgres", "title": "Own one schema migration end-to-end", "is_passed": False},
        ],
    },
    {
        "title": "Plan in review — Petra Nowak",
        "employee_index": 15,
        "status": "review",
        "specialization_key": "frontend-dev",
        "grade_key": "g-middle",
        "items": [
            {"competence_key": "c-react", "title": "Lead a React server-components migration spike", "is_passed": False},
        ],
    },
    # --- Returned ---
    {
        "title": "Returned — please expand items",
        "employee_index": 8,  # Ivan Petrov
        "status": "returned",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-distributed", "title": "TBD — needs concrete deliverable", "is_passed": False},
        ],
    },
    # --- Done ---
    {
        "title": "Plan completed — Carlos Mendez (Q3)",
        "employee_index": 2,
        "status": "done",
        "specialization_key": "backend-dev",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-python", "title": "Reached L3 Builder on Python rubric", "is_passed": True},
            {"competence_key": "c-mentoring", "title": "Mentored two L2 engineers through promotion", "is_passed": True},
        ],
    },
    # --- Cancelled ---
    {
        "title": "Cancelled — superseded by Q1 plan",
        "employee_index": 13,
        "status": "cancelled",
        "specialization_key": "frontend-dev",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-typescript", "title": "Outdated goal", "is_passed": False},
        ],
    },
    # --- Draft ---
    {
        "title": "Draft — Hannah Adler",
        "employee_index": 33,  # Hannah Adler, AE
        "status": "draft",
        "specialization_key": "product-mgmt",
        "grade_key": "g-senior",
        "items": [
            {"competence_key": "c-customer-discovery", "title": "Sketch out enterprise discovery script", "is_passed": False},
        ],
    },
    {
        "title": "Draft — Zoe Caron",
        "employee_index": 25,  # Zoe Caron, Senior Designer
        "status": "draft",
        "specialization_key": "product-design",
        "grade_key": "g-senior",
        "items": [],
    },
]
