"""Static fixtures for the investor-grade demo seed (HRP-250 — D2).

Two consumers:

* ``app.modules.demo.seed.clone_seed_into_demo_tenant`` — hosted demo
  sandbox endpoint (D3) clones these fixtures into a freshly created
  per-session ``Tenant``.
* ``scripts/seed_demo_investor.py`` — self-hosted CLI applies the same
  fixtures on top of the base ``Pulsar Technologies`` tenant.

One source of truth, two applications. The literals here are the
canonical demo dataset:
3 vacancies, 8 candidates, 2 completed interviews with deep AI
analysis (Elena + Tomás), and the matching interview transcript.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# Marker used to tag every row that belongs to this seed pack, so the
# self-hosted CLI can wipe just the investor data without touching the
# base tenant. Hosted demo tenants don't need it — purge cascades drop
# the whole tenant anyway — but tagging stays consistent across both
# applications so downstream code (analytics, exports) can filter.
INVESTOR_MARKER = "demo-investor"


# Canonical email of the demo's headline candidate. Source-of-truth for
# seed_data.candidates() below and the analysis killswitch
# (``recruitment.tasks.demo_analysis``) — keep them in lockstep by
# importing from here instead of duplicating the string.
DEMO_FIRST_SCREEN_CANDIDATE_EMAIL = "elena.volkov@example.com"


# Transcript is packaged alongside the module so an installed wheel
# can read it without depending on the source tree layout.
TRANSCRIPT_PATH = (
    Path(__file__).resolve().parent / "seed_assets" / "interview-transcript-elena.txt"
)


_TRANSCRIPT_FALLBACK = "Transcript artifact not bundled."


def load_transcript() -> str:
    """Read the packaged Elena interview transcript.

    Picks the seed-locale variant (``interview-transcript-elena.<locale>.txt``)
    when one is bundled, falling back to the English asset, and finally
    to a one-line stub when no asset is present so the seed still
    produces a syntactically valid Interview row in a stripped-down
    distribution.
    """
    from app.modules.demo.seed_i18n import ee_asset_path, seed_locale

    locale = seed_locale()
    paths = [TRANSCRIPT_PATH]
    if locale != "en":
        name = f"interview-transcript-elena.{locale}.txt"
        ee_path = ee_asset_path(name)
        if ee_path is not None:
            paths.insert(0, ee_path)
        paths.insert(0, TRANSCRIPT_PATH.with_name(name))
    for path in paths:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    logger.warning(
        "demo seed: transcript missing at %s, using stub", TRANSCRIPT_PATH
    )
    return _TRANSCRIPT_FALLBACK


# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------

VACANCIES: list[dict] = [
    {
        "key": "senior-backend",
        "title": "Senior Backend Engineer — Payments",
        "description": (
            "Own the merchant settlement pipeline. Python, FastAPI, "
            "PostgreSQL, Kafka. 50,000 active merchants, 2M transactions/day."
        ),
        "language": "en",
        "location": "Berlin (hybrid)",
        "employment_type": "full_time",
        "salary_min": 90000,
        "salary_max": 115000,
        "salary_currency": "EUR",
        "status": "published",
        "profile": {
            # Soft competences carry slug ids too so the AI analysis can
            # mint AIAssessment rows for them and the Compact matrix
            # surfaces every dimension Elena's interview was scored on
            # (ownership / mentorship would otherwise be silently dropped
            # because the matrix iterates ``profile.competences`` only).
            "competences": [
                {"id": "python-advanced", "name": "Python (advanced)", "must_have": True},
                {"id": "distributed-systems", "name": "Distributed systems", "must_have": True},
                {"id": "postgres-advanced", "name": "PostgreSQL (advanced)", "must_have": True},
                {"id": "system-design", "name": "System design", "must_have": True},
                {"id": "streaming", "name": "Streaming (Kafka/Kinesis)", "must_have": False},
                {"id": "payments-domain", "name": "Payments domain", "must_have": False},
                {"id": "ownership", "name": "Ownership", "must_have": False},
                {"id": "mentorship", "name": "Mentorship", "must_have": False},
            ],
            "soft_competences": [
                "Written communication (ADRs, post-mortems)",
            ],
            "disqualifiers": [
                "No prior backend ownership of a production service",
                "Unexplained resume gap > 12 months",
            ],
        },
    },
    {
        "key": "product-designer",
        "title": "Product Designer — Recruiting Suite",
        "description": (
            "Shape the recruiter and hiring-manager surfaces. End-to-end "
            "ownership of vacancy, candidate and interview review flows."
        ),
        "language": "en",
        "location": "Remote (EU timezone)",
        "employment_type": "full_time",
        "salary_min": 75000,
        "salary_max": 100000,
        "salary_currency": "EUR",
        "status": "published",
        "profile": {
            "competences": [
                {"id": "product-design", "name": "Product design", "must_have": True},
                {"id": "design-systems", "name": "Design systems", "must_have": True},
                {"id": "user-research", "name": "User research", "must_have": True},
            ],
        },
    },
    {
        "key": "customer-success",
        "title": "Customer Success Lead — Enterprise",
        "description": (
            "First CS hire. Own onboarding, expansion and retention for our "
            "first 25 enterprise customers."
        ),
        "language": "en",
        "location": "Berlin or London",
        "employment_type": "full_time",
        "salary_min": 85000,
        "salary_max": 110000,
        "salary_currency": "EUR",
        "status": "published",
        "profile": {
            "competences": [
                {"id": "saas-cs", "name": "SaaS customer success", "must_have": True},
                {"id": "enterprise-accounts", "name": "Enterprise accounts", "must_have": True},
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def candidates() -> list[dict]:
    """Return the candidate fixtures.

    A function (not a module-level constant) so the literal isn't built
    at import time — the CLI imports this module for cleanup paths that
    never touch the candidate list, and we'd rather not eat the alloc.
    """
    return [
        # --- Senior Backend Engineer pipeline ---
        {
            "vacancy_key": "senior-backend",
            "first_name": "Elena",
            "last_name": "Volkov",
            "email": DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
            "phone": "+49 30 1234 5678",
            "location": "Berlin, Germany",
            "current_position": "Staff Engineer @ Klarna",
            "years": 9,
            "linkedin": "linkedin.com/in/elenavolkov",
            "status": "interview",
            "ai_score": 0.92,
            "ai_verdict": "recommended",
            "ai_summary": (
                "Nine years of payments-infra experience, owned a non-trivial "
                "Ruby→Python rewrite at Klarna with measurable latency wins. "
                "Strong systems thinking, comfortable on-call, mentors others."
            ),
            "ai_strength": "Owned end-to-end migration of payments reconciliation pipeline at scale.",
            "ai_risk": "Has not run merchant-side SEPA settlements specifically; ramp on domain expected.",
            "ai_mitigation": "Probe domain knowledge in a follow-up technical panel; pair with senior payments engineer on first sprint.",
            "interview": True,
        },
        {
            "vacancy_key": "senior-backend",
            "first_name": "Marcus",
            "last_name": "Okafor",
            "email": "marcus.okafor@example.com",
            "phone": "+234 803 555 0142",
            "location": "Lagos, Nigeria (open to remote)",
            "current_position": "Senior Engineer @ Flutterwave",
            "years": 5,
            "linkedin": "github.com/mokafor",
            "status": "screen",
            "ai_score": 0.71,
            "ai_verdict": "needs_check",
            "ai_summary": (
                "Solid fintech background in African market, good on Django/Python "
                "fundamentals, weaker on distributed-systems and streaming."
            ),
            "ai_strength": "Strong product-engineering instincts shipping consumer fintech features end-to-end.",
            "ai_risk": "No demonstrated experience with Kafka or event-sourced architectures.",
            "ai_mitigation": "Lead with a system-design question on event-driven payments; check growth trajectory in screen.",
            "interview": False,
        },
        {
            "vacancy_key": "senior-backend",
            "first_name": "Priya",
            "last_name": "Shah",
            "email": "priya.shah@example.com",
            "phone": "+91 98765 43210",
            "location": "Bangalore, India",
            "current_position": "Software Developer @ Freshworks",
            "years": 3,
            "linkedin": "linkedin.com/in/priyashah",
            "status": "new",
            "ai_score": 0.34,
            "ai_verdict": "not_recommended",
            "ai_summary": (
                "Three years of experience overall, mostly small-team work, no "
                "senior-level backend ownership demonstrated."
            ),
            "ai_strength": "Self-driven; has earned AWS Cloud Practitioner and pursues algorithmic study.",
            "ai_risk": "Years of experience and scope are below the senior bar for this role.",
            "ai_mitigation": "Decline for senior role; consider for future mid-level opening if pipeline has room.",
            "interview": False,
        },
        {
            "vacancy_key": "senior-backend",
            "first_name": "Tomás",
            "last_name": "Becker",
            "email": "tomas.becker@example.com",
            "phone": "+34 600 123 456",
            "location": "Barcelona, Spain",
            "current_position": "Senior Backend Engineer @ Adyen",
            "years": 7,
            "status": "offer",
            "ai_score": 0.88,
            "ai_verdict": "recommended",
            "ai_summary": (
                "Direct payments-domain experience at Adyen with strong distributed-systems chops."
            ),
            "ai_strength": "Direct merchant-settlement experience at Adyen scale.",
            "ai_risk": "Likely to receive competing offers; comp negotiation may stretch.",
            "ai_mitigation": "Move fast; involve VP Engineering early to close.",
            "interview": True,
        },
        {
            "vacancy_key": "senior-backend",
            "first_name": "Yuki",
            "last_name": "Tanaka",
            "email": "yuki.tanaka@example.com",
            "location": "Tokyo, Japan",
            "current_position": "Backend Engineer @ Mercari",
            "years": 6,
            "status": "screen",
            "ai_score": 0.66,
            "ai_verdict": "needs_check",
            "ai_summary": (
                "Solid Python+Go experience, but no European fintech context and "
                "timezone overlap is limited."
            ),
            "ai_strength": "Cross-language experience and strong on-call discipline.",
            "ai_risk": "Timezone gap with Berlin engineering team.",
            "ai_mitigation": "Confirm relocation appetite and overlap window in screen.",
            "interview": False,
        },
        # --- Product Designer pipeline ---
        {
            "vacancy_key": "product-designer",
            "first_name": "Sofia",
            "last_name": "Hartmann",
            "email": "sofia.hartmann@example.com",
            "location": "Munich, Germany",
            "current_position": "Senior Product Designer @ Personio",
            "years": 8,
            # ``screen`` so the funnel column matches her ``interview=False``
            # state — a previous fixture had her at the ``interview``
            # stage with no Interview row, which made her card show
            # "resume only" while she sat in the Interview column.
            "status": "screen",
            "ai_score": 0.87,
            "ai_verdict": "recommended",
            "ai_summary": "Strong HRtech design background, owns systems-thinking and research.",
            "ai_strength": "Built the HRIS design system at Personio from scratch.",
            "ai_risk": "Has only worked on B2B HRtech; broader range untested.",
            "ai_mitigation": "Probe motivation in next round; ask for portfolio across other domains if any.",
            "interview": False,
        },
        {
            "vacancy_key": "product-designer",
            "first_name": "James",
            "last_name": "O'Brien",
            "email": "james.obrien@example.com",
            "location": "Dublin, Ireland",
            "current_position": "Product Designer @ Workday",
            "years": 5,
            "status": "new",
            "ai_score": 0.72,
            "ai_verdict": "needs_check",
            "ai_summary": "Capable designer with relevant enterprise context.",
            "ai_strength": "Has shipped HR-adjacent enterprise workflows.",
            "ai_risk": "Portfolio leans heavily on dashboards; less evidence of editorial UX.",
            "ai_mitigation": "Request to see process work on a complex flow.",
            "interview": False,
        },
        # --- Customer Success pipeline ---
        {
            "vacancy_key": "customer-success",
            "first_name": "Aisha",
            "last_name": "Patel",
            "email": "aisha.patel@example.com",
            "location": "London, UK",
            "current_position": "Senior CSM @ Gong",
            "years": 7,
            "status": "interview",
            "ai_score": 0.90,
            "ai_verdict": "recommended",
            "ai_summary": "Top-of-funnel CS leader with measurable NRR impact.",
            "ai_strength": "Grew NRR from 108% to 124% at Gong over two years.",
            "ai_risk": "Comp expectations may exceed band.",
            "ai_mitigation": "Discuss equity-heavy package early.",
            "interview": False,
        },
    ]


# ---------------------------------------------------------------------------
# Deep AI analysis for the two completed interviews
# ---------------------------------------------------------------------------

ELENA_INTERVIEW_ANALYSIS: dict = {
    "data_completeness": "high",
    "verdict": "recommended",
    "verdict_summary": (
        "Strong recommend. Elena demonstrated senior-level systems thinking on "
        "the settlement design question, including idempotency, reconciliation "
        "and partition strategy. Self-aware about domain gaps and proposed a "
        "concrete ramp plan."
    ),
    "key_strength": (
        "Designed the settlement system in real-time including a reconciliation "
        "loop for the case where the SEPA gateway loses idempotency keys — a "
        "trap most candidates miss."
    ),
    "key_risk": (
        "No direct experience with EUR merchant settlements at our exact volume. "
        "Has shipped comparable systems in adjacent domains."
    ),
    "risk_mitigation": (
        "Pair with senior payments engineer for first sprint, provide domain "
        "onboarding doc, ramp expectation of 6 weeks not 6 months."
    ),
    # ``competence_id`` carries the slug used in ``VACANCIES[*].profile.competences``
    # so the killswitch can mint the same UUID the Canvas/Compact matrix
    # looks up. ``competence`` stays the human-readable label that lands
    # in citations + analysis_data for the UI.
    "competence_assessments": [
        {
            "competence_id": "python-advanced",
            "competence": "Python (advanced)",
            "verdict": "strong",
            "evidence": "Designed async pipeline boundaries on the fly, type-aware error handling, mentioned aiocache and FastAPI internals.",
        },
        {
            "competence_id": "distributed-systems",
            "competence": "Distributed systems",
            "verdict": "strong",
            "evidence": "Articulated idempotency keys, exactly-once semantics, reconciliation loop, divergence detection.",
        },
        {
            "competence_id": "postgres-advanced",
            "competence": "PostgreSQL (advanced)",
            "verdict": "strong",
            "evidence": "Discussed monthly partitioning, archive strategy, anti-pattern of partitioning by merchant_id.",
        },
        {
            "competence_id": "system-design",
            "competence": "System design",
            "verdict": "strong",
            "evidence": "Led the design problem from clarifying questions to operational concerns (reconciliation, DST bug).",
        },
        {
            "competence_id": "payments-domain",
            "competence": "Payments domain",
            "verdict": "partial",
            "evidence": "Worked on Klarna payments reconciliation but not EUR merchant settlements specifically.",
        },
        {
            "competence_id": "ownership",
            "competence": "Ownership",
            "verdict": "strong",
            "evidence": "Concrete DST-incident story including post-mortem and process change.",
        },
        {
            "competence_id": "mentorship",
            "competence": "Mentorship",
            "verdict": "strong",
            "evidence": "Differentiated approach for mid-level vs junior, honest about lacking a clean metric.",
        },
    ],
    # Items mirror the real ``ProcessFinding``/``BlindSpot`` shapes from
    # prompts_interview.py — the analysis panel reads those exact fields
    # (HRP-579); the plain strings seeded before crashed the interview
    # page render on ``finding_type``.
    "process_findings": [],
    "blind_spots": [
        {
            "competence_id": "streaming",
            "suggested_question": "How would you detect and recover from Kafka consumer lag in the settlement pipeline during a peak day?",
        },
    ],
    "red_flags": [],
}

TOMAS_INTERVIEW_ANALYSIS: dict = {
    "data_completeness": "medium",
    "verdict": "needs_check",
    "verdict_summary": (
        "Recommend with reservations. Direct payments-domain background and "
        "clear technical fundamentals, but candidate had limited time and the "
        "interview did not cover mentorship or cross-team work."
    ),
    "key_strength": "Direct experience operating EUR settlement systems at Adyen scale.",
    "key_risk": "Active in market — likely to entertain competing offers.",
    "risk_mitigation": "Compress remaining loops; involve VP Engineering for closing call.",
    "competence_assessments": [
        {"competence_id": "python-advanced", "competence": "Python (advanced)", "verdict": "strong", "evidence": "Async-await fluency, comfortable with FastAPI tradeoffs."},
        {"competence_id": "distributed-systems", "competence": "Distributed systems", "verdict": "strong", "evidence": "Walked through outbox pattern unprompted."},
        {"competence_id": "payments-domain", "competence": "Payments domain", "verdict": "strong", "evidence": "Adyen merchant settlement experience."},
        {"competence_id": "mentorship", "competence": "Mentorship", "verdict": "unknown", "evidence": "Not assessed in this round."},
    ],
    "process_findings": [],
    "blind_spots": [
        {
            "competence_id": "mentorship",
            "suggested_question": "Tell me about a time you mentored a mid-level engineer through their first production incident.",
        },
    ],
    "red_flags": [],
}
