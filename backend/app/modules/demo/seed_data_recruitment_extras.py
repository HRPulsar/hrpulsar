"""Extra recruitment fixtures for the demo seed (HRP-281 — S7).

Layered on top of the HRP-250 recruitment seed (3 vacancies + 8
candidates + 2 deep-analyzed interviews). Adds four more vacancies,
twelve more candidates, and four more interviews covering the
non-completed states (scheduled / in_progress / completed without
analysis / archived) so the recruitment funnel shows every
status the kanban supports — not just the AI-analyzed entry point
the demo opens on.

Vacancy ``key`` strings live in the same namespace as
``seed_data.VACANCIES`` for consistency. Candidate ``vacancy_key``
fields target either an extras-vacancy key or one of the legacy keys
from seed_data.VACANCIES so the funnel for the original roles also
gains a few extra entries.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Extra vacancies
# ---------------------------------------------------------------------------

EXTRA_VACANCIES: list[dict] = [
    {
        "key": "em-frontend",
        "title": "Engineering Manager — Frontend",
        "description": (
            "Take over the Frontend org — design system, recruiter SPA, "
            "performance budgets. Light coding, heavy people work."
        ),
        "language": "en",
        "location": "Berlin or Remote (EU)",
        "employment_type": "full_time",
        "salary_min": 105000,
        "salary_max": 135000,
        "salary_currency": "EUR",
        "status": "published",
        "anchor_division_key": "eng-frontend",
        "profile": {
            "competences": [
                {"id": "react", "name": "React", "must_have": True},
                {"id": "design-systems", "name": "Design Systems", "must_have": True},
                {"id": "hiring", "name": "Hiring + interview craft", "must_have": True},
                {"id": "mentoring", "name": "Mentoring", "must_have": True},
            ],
            "soft_competences": [
                "Written communication",
                "Cross-functional partnership",
            ],
        },
    },
    {
        "key": "junior-backend",
        "title": "Junior Backend Engineer",
        "description": (
            "Entry-level role. Pair-program your way through your first sprint "
            "and ship a customer-facing feature in your first 90 days."
        ),
        "language": "en",
        "location": "Berlin (on-site preferred)",
        "employment_type": "full_time",
        "salary_min": 40000,
        "salary_max": 55000,
        "salary_currency": "EUR",
        "status": "published",
        "anchor_division_key": "eng-backend",
        "profile": {
            "competences": [
                {"id": "python", "name": "Python", "must_have": True},
                {"id": "sql-basics", "name": "SQL basics", "must_have": True},
            ],
            "soft_competences": ["Curiosity", "Coachability"],
        },
    },
    {
        "key": "designer-mobile",
        "title": "Senior Product Designer — Mobile",
        "description": (
            "Lead the design of our upcoming mobile app for hiring managers. "
            "Heavy interaction design, light visual."
        ),
        "language": "en",
        "location": "Remote (EU/UK)",
        "employment_type": "full_time",
        "salary_min": 80000,
        "salary_max": 110000,
        "salary_currency": "EUR",
        "status": "published",
        "anchor_division_key": "design",
        "profile": {
            "competences": [
                {"id": "ux-mobile", "name": "Mobile UX", "must_have": True},
                {"id": "design-systems", "name": "Design Systems", "must_have": True},
                {"id": "user-research", "name": "User Research", "must_have": True},
            ],
            "soft_competences": ["Cross-functional partnership"],
        },
    },
    {
        "key": "recruitment-lead",
        "title": "Recruitment Lead",
        "description": (
            "Build out the recruiting bench from 3 to 7 over the next 12 months. "
            "Half player, half coach."
        ),
        "language": "en",
        "location": "Berlin",
        "employment_type": "full_time",
        "salary_min": 85000,
        "salary_max": 115000,
        "salary_currency": "EUR",
        # HRP-281 review: a draft vacancy that owns a Candidate cannot be
        # hard-deleted (delete_vacancy guards against candidates on
        # drafts) AND a draft vacancy cannot be archived (archive only
        # accepts published / closed) — it would render as a paradoxical
        # stuck row in the demo. Publish it instead so the lifecycle is
        # reachable.
        "status": "published",
        "anchor_division_key": "people",
        "profile": {
            "competences": [
                {"id": "hiring", "name": "Hiring", "must_have": True},
                {"id": "people-ops", "name": "People ops fundamentals", "must_have": True},
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Extra candidates (12 entries across 6 vacancy keys)
# ---------------------------------------------------------------------------

EXTRA_CANDIDATES: list[dict] = [
    # --- em-frontend pipeline (3) ---
    {
        "vacancy_key": "em-frontend",
        "first_name": "Mateo",
        "last_name": "Garcia",
        "email": "mateo.garcia@example.com",
        "location": "Barcelona, Spain",
        "current_position": "Engineering Manager @ N26",
        "years": 8,
        "status": "interview",
        "ai_score": 0.84,
        "ai_verdict": "recommended",
        "ai_summary": "Solid EM with 4 years at N26 leading frontend org.",
        "ai_strength": "Built out the recruiter onboarding programme single-handedly.",
        "ai_risk": "Has not led a fully-remote team before.",
        "ai_mitigation": "Probe remote management approach in the panel.",
        "interview_kind": "completed_no_ai",
    },
    {
        "vacancy_key": "em-frontend",
        "first_name": "Helena",
        "last_name": "Brennan",
        "email": "helena.brennan@example.com",
        "location": "Dublin, Ireland",
        "current_position": "Tech Lead @ Stripe",
        "years": 9,
        "status": "screen",
        "ai_score": 0.79,
        "ai_verdict": "recommended",
        "ai_summary": "Strong tech-lead profile; transitioning into pure people management.",
        "ai_strength": "Owned the Stripe Dashboard React migration end-to-end.",
        "ai_risk": "Limited hands-on hiring experience.",
        "ai_mitigation": "Hiring panel will probe interview calibration.",
        "interview_kind": "in_progress_upload",
    },
    {
        "vacancy_key": "em-frontend",
        "first_name": "Pavel",
        "last_name": "Novak",
        "email": "pavel.novak@example.com",
        "location": "Prague, Czechia",
        "current_position": "Senior Frontend Engineer @ Productboard",
        "years": 7,
        "status": "new",
        "ai_score": 0.62,
        "ai_verdict": "needs_check",
        "ai_summary": "Strong IC, no formal management experience yet.",
        "ai_strength": "Owns the Productboard design system",
        "ai_risk": "Has not managed people.",
        "ai_mitigation": "Likely better fit for staff IC role.",
        "interview_kind": None,
    },
    # --- junior-backend pipeline (3) ---
    {
        "vacancy_key": "junior-backend",
        "first_name": "Isabella",
        "last_name": "Ferraro",
        "email": "isabella.ferraro@example.com",
        "location": "Milan, Italy",
        "current_position": "Bootcamp grad — Le Wagon Berlin",
        "years": 1,
        "status": "screen",
        "ai_score": 0.55,
        "ai_verdict": "needs_check",
        "ai_summary": "Bootcamp grad with strong portfolio of personal projects.",
        "ai_strength": "Three completed end-to-end side projects in Python.",
        "ai_risk": "No professional production experience.",
        "ai_mitigation": "Standard junior trial-task path.",
        "interview_kind": "scheduled",
    },
    {
        "vacancy_key": "junior-backend",
        "first_name": "Jonas",
        "last_name": "Werner",
        "email": "jonas.werner@example.com",
        "location": "Hamburg, Germany",
        "current_position": "Working student @ Zalando",
        "years": 1,
        "status": "new",
        "ai_score": 0.61,
        "ai_verdict": "needs_check",
        "ai_summary": "Working student with consistent Zalando track record.",
        "ai_strength": "Built internal tooling end-to-end at Zalando.",
        "ai_risk": "Limited algorithmic depth in resume.",
        "ai_mitigation": "Trial task to validate fundamentals.",
        "interview_kind": None,
    },
    {
        "vacancy_key": "junior-backend",
        "first_name": "Aline",
        "last_name": "Souza",
        "email": "aline.souza@example.com",
        "location": "Lisbon, Portugal",
        "current_position": "Self-taught — SaaS micro-projects",
        "years": 2,
        "status": "new",
        "ai_score": 0.46,
        "ai_verdict": "needs_check",
        "ai_summary": "Self-taught with two paying micro-SaaS projects.",
        "ai_strength": "Demonstrated ability to ship.",
        "ai_risk": "No team-based experience.",
        "ai_mitigation": "Pair-programming trial.",
        "interview_kind": None,
    },
    # --- designer-mobile pipeline (3) ---
    {
        "vacancy_key": "designer-mobile",
        "first_name": "Mei",
        "last_name": "Chen",
        "email": "mei.chen@example.com",
        "location": "Amsterdam, Netherlands",
        "current_position": "Senior Designer @ Booking.com",
        "years": 6,
        "status": "interview",
        "ai_score": 0.86,
        "ai_verdict": "recommended",
        "ai_summary": "Mobile-first designer with proven travel + booking flow craft.",
        "ai_strength": "Led the Booking.com flight-booking redesign.",
        "ai_risk": "Less B2B exposure than other candidates.",
        "ai_mitigation": "Walk through HR Mobile use cases in panel.",
        "interview_kind": "archived",
    },
    {
        "vacancy_key": "designer-mobile",
        "first_name": "Oskar",
        "last_name": "Lindgren",
        "email": "oskar.lindgren@example.com",
        "location": "Stockholm, Sweden",
        "current_position": "Senior Designer @ Klarna",
        "years": 7,
        "status": "screen",
        "ai_score": 0.78,
        "ai_verdict": "recommended",
        "ai_summary": "Strong UX background; lighter on mobile than Mei.",
        "ai_strength": "Strong systems-thinking and Figma library ownership.",
        "ai_risk": "Mobile portfolio is thin.",
        "ai_mitigation": "Ask for relevant mobile case studies in next round.",
        "interview_kind": None,
    },
    {
        "vacancy_key": "designer-mobile",
        "first_name": "Lina",
        "last_name": "Petrelli",
        "email": "lina.petrelli@example.com",
        "location": "Turin, Italy",
        "current_position": "Designer @ Satispay",
        "years": 4,
        "status": "new",
        "ai_score": 0.59,
        "ai_verdict": "needs_check",
        "ai_summary": "Solid mid-level designer; might be slightly below senior bar.",
        "ai_strength": "Owns Satispay's new mobile onboarding flow.",
        "ai_risk": "Less than expected years at senior level.",
        "ai_mitigation": "Calibrate level in screen.",
        "interview_kind": None,
    },
    # --- recruitment-lead pipeline (1) ---
    {
        "vacancy_key": "recruitment-lead",
        "first_name": "Karim",
        "last_name": "Haddad",
        "email": "karim.haddad@example.com",
        "location": "Berlin, Germany",
        "current_position": "Talent Lead @ HelloFresh",
        "years": 10,
        "status": "new",
        "ai_score": 0.74,
        "ai_verdict": "recommended",
        "ai_summary": "Career recruiter with EU SaaS expansion experience.",
        "ai_strength": "Built recruiting team from 3 to 12 at HelloFresh.",
        "ai_risk": "Vacancy still in draft — no full process yet.",
        "ai_mitigation": "Plan move to published before scheduling.",
        "interview_kind": None,
    },
    # --- senior-backend re-applications (2 — legacy vacancy from seed_data.py) ---
    {
        "vacancy_key": "senior-backend",
        "first_name": "Robin",
        "last_name": "Lehmann",
        "email": "robin.lehmann@example.com",
        "location": "Zurich, Switzerland",
        "current_position": "Backend Engineer @ Smallpdf",
        "years": 6,
        "status": "screen",
        "ai_score": 0.68,
        "ai_verdict": "needs_check",
        "ai_summary": "Solid backend engineer with PDF/B2C SaaS background.",
        "ai_strength": "Owns Smallpdf billing pipeline.",
        "ai_risk": "No payments-specific experience.",
        "ai_mitigation": "Probe domain knowledge in screen.",
        "interview_kind": None,
    },
    # --- product-designer extra (1) ---
    {
        "vacancy_key": "product-designer",
        "first_name": "Saira",
        "last_name": "Kapoor",
        "email": "saira.kapoor@example.com",
        "location": "London, UK",
        "current_position": "Senior Designer @ Monzo",
        "years": 7,
        "status": "screen",
        "ai_score": 0.81,
        "ai_verdict": "recommended",
        "ai_summary": "Strong fintech-design background, can carry a domain.",
        "ai_strength": "Owned Monzo's business onboarding flow.",
        "ai_risk": "Less HRtech exposure.",
        "ai_mitigation": "Walk through HR Pulsar workflows to gauge interest.",
        "interview_kind": None,
    },
]


# ---------------------------------------------------------------------------
# Interview shape per ``interview_kind``
# ---------------------------------------------------------------------------
#
# The seeder reads this map to decide which Interview row shape to lay
# down for the candidate. Values map onto status fields on the
# Interview model.

INTERVIEW_SHAPES: dict[str, dict] = {
    "completed_no_ai": {
        "status": "completed",
        "transcription_status": "completed",
        "analysis_status": "pending",
        "type": "technical",
        "title_prefix": "Technical interview — ",
        "transcript": (
            "[Transcript redacted for demo brevity. AI analysis has not been "
            "triggered yet — the Run analysis button is enabled.]"
        ),
        "duration_minutes": 40,
        "days_ago": 2,
    },
    "in_progress_upload": {
        "status": "in_progress",
        "transcription_status": "pending",
        "analysis_status": "pending",
        "type": "screen",
        "title_prefix": "Screen — ",
        "transcript": None,
        "duration_minutes": None,
        "days_ago": 0,
    },
    "scheduled": {
        "status": "scheduled",
        "transcription_status": "pending",
        "analysis_status": "pending",
        "type": "technical",
        "title_prefix": "Scheduled technical — ",
        "transcript": None,
        "duration_minutes": None,
        "days_ago": -3,  # in the future
    },
    "archived": {
        "status": "archived",
        "transcription_status": "completed",
        "analysis_status": "completed",
        "type": "screen",
        "title_prefix": "Archived screen — ",
        "transcript": "[Archived. Candidate withdrew before final round.]",
        "duration_minutes": 30,
        "days_ago": 21,
    },
}
