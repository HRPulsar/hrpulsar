"""Static fixtures for the investor-grade demo seed (HRP-250 — D2).

Two consumers:

* ``app.modules.demo.seed.clone_seed_into_demo_tenant`` — hosted demo
  sandbox endpoint (D3) clones these fixtures into a freshly created
  per-session ``Tenant``.
* ``scripts/seed_demo_investor.py`` — self-hosted CLI applies the same
  fixtures on top of the base ``Pulsar Technologies`` tenant.

One source of truth, two applications. The literals here are the
canonical demo dataset:
3 vacancies, 6 candidates, 2 completed interviews with deep AI
analysis (Elena + Tomás), and the matching interview transcript.

HRP-666: three candidates per vacancy, no more — and the three read as
strong / mixed / weak, so a visitor can see *why* one is recommended
without opening anything.
"""

from __future__ import annotations

import logging
import re
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


# HRP-275: the bundled transcripts are diarized on the page as
# ``[HH:MM:SS] Speaker: line``. Both writers of a demo transcript (the
# seed and the kill-switch replay) turn them back into InterviewSegment
# rows, so the transcript panel shows speakers and timecodes the way a
# diarizing provider would instead of one undifferentiated blob — the
# demo has no media to transcribe, but it should still look transcribed.
_SEGMENT_LINE = re.compile(
    r"^\[(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\]\s*(?P<speaker>[^:]{1,40}):\s*(?P<text>.+)$"
)

# Last line of a transcript has no successor to bound it.
TRAILING_SEGMENT_SECONDS = 30


def parse_transcript_segments(transcript: str) -> list[dict]:
    """Split a bundled demo transcript into segment dicts.

    Header lines (title, candidate, date) carry no timecode and are
    skipped. ``end_sec`` is the next segment's start, so the player's
    sync-scroll has a window to highlight; the last line gets a fixed
    tail. An unparseable transcript yields an empty list and the caller
    falls back to showing the blob.
    """
    rows: list[dict] = []
    for line in (transcript or "").splitlines():
        match = _SEGMENT_LINE.match(line.strip())
        if match is None:
            continue
        start = (
            int(match.group("h")) * 3600
            + int(match.group("m")) * 60
            + int(match.group("s"))
        )
        rows.append(
            {
                "speaker": match.group("speaker").strip(),
                "start_sec": float(start),
                "text": match.group("text").strip(),
            }
        )
    for current, following in zip(rows, rows[1:], strict=False):
        current["end_sec"] = following["start_sec"]
    if rows:
        rows[-1]["end_sec"] = rows[-1]["start_sec"] + TRAILING_SEGMENT_SECONDS
    return rows


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
        # HRP-667: the library-linked requirements the internal matcher
        # reads. The ``profile`` block below is what the AI scores a
        # *candidate* against — free-text slugs the talent-market matcher
        # cannot resolve — so without these rows the headline vacancy
        # could not be posted to the internal talent market at all.
        #
        # Two invariants, both inherited from ``seed_data_talent_market``:
        # only competences the demo actually assesses can carry a card
        # (``_comp_percent_from_map`` scores an unassessed one as 0), and
        # the set has to leave somebody above the bar. The bridge builds
        # the card at the product default of 80%, and the seeded backend
        # engineers clear python + distributed but not python +
        # distributed + postgres — a third row would put the whole pool
        # in the seventies and print "nobody inside fits" on the one
        # screen this feature exists to demonstrate.
        "library_competences": [
            {"competence_key": "c-python", "skill_level_key": "sl-l3"},
            {"competence_key": "c-distributed", "skill_level_key": "sl-l3"},
        ],
        "profile": {
            # Soft competences carry slug ids too so the AI analysis can
            # mint AIAssessment rows for them and the Compact matrix
            # surfaces every dimension Elena's interview was scored on
            # (ownership / mentorship would otherwise be silently dropped
            # because the matrix iterates ``profile.competences`` only).
            "competences": [
                {
                    "id": "python-advanced",
                    "name": "Python (advanced)",
                    "must_have": True,
                },
                {
                    "id": "distributed-systems",
                    "name": "Distributed systems",
                    "must_have": True,
                },
                {
                    "id": "postgres-advanced",
                    "name": "PostgreSQL (advanced)",
                    "must_have": True,
                },
                {"id": "system-design", "name": "System design", "must_have": True},
                {
                    "id": "streaming",
                    "name": "Streaming (Kafka/Kinesis)",
                    "must_have": False,
                },
                {
                    "id": "payments-domain",
                    "name": "Payments domain",
                    "must_have": False,
                },
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
                {
                    "id": "enterprise-accounts",
                    "name": "Enterprise accounts",
                    "must_have": True,
                },
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
            "status": "offer",
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
            # HRP-666: the hiring manager scored her too, and lands where
            # the AI did — the demo's "both sides agree" row. Levels of the
            # default 1..4 assessment scale, keyed by the profile slug.
            "manager_scores": {
                "python-advanced": 4,
                "distributed-systems": 4,
                "postgres-advanced": 3,
                "system-design": 4,
                "payments-domain": 3,
                "ownership": 4,
                "mentorship": 3,
            },
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
            "status": "interview",
            "ai_score": 0.83,
            "ai_verdict": "needs_check",
            "ai_summary": (
                "Direct payments-domain experience at Adyen with strong "
                "distributed-systems chops, but the screen never covered "
                "mentorship or cross-team work."
            ),
            "ai_strength": "Direct merchant-settlement experience at Adyen scale.",
            "ai_risk": "Likely to receive competing offers; comp negotiation may stretch.",
            "ai_mitigation": "Move fast; involve VP Engineering early to close.",
            "interview": True,
            # HRP-666: the demo's "the two sides disagree" row. The AI
            # rated the Adyen payments background near the top; the
            # manager who talked to him did not, so the Divergence badge
            # and the candidate-card divergence text have one concrete,
            # explainable cell to point at.
            "manager_scores": {
                "python-advanced": 3,
                "distributed-systems": 3,
                "payments-domain": 2,
                "mentorship": 3,
            },
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

# ``analysis_data`` mirrors ``InterviewAnalysisResult`` (prompts_interview.py)
# field for field — the same payload ``analyze_interview_task`` writes on the
# real path. The demo renders through the production components, so a shape
# that diverges here shows up as an empty panel on the demo and nowhere else
# (HRP-598). ``competence_id`` carries the slug used in
# ``VACANCIES[*].profile.competences``: the UI resolves the display name
# through the profile, and the killswitch mints the same UUID the Canvas /
# Compact matrix looks up. Scores are on the canonical 0..1 raw AI scale.

ELENA_INTERVIEW_ANALYSIS: dict = {
    "data_completeness": "full",
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
    "competence_assessments": [
        {
            "competence_id": "python-advanced",
            "score": 0.85,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Designed async pipeline boundaries on the fly, type-aware error handling, mentioned aiocache and FastAPI internals.",
                }
            ],
            "reasoning": "Designed async pipeline boundaries on the fly, type-aware error handling, mentioned aiocache and FastAPI internals.",
        },
        {
            "competence_id": "distributed-systems",
            "score": 0.9,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Articulated idempotency keys, exactly-once semantics, reconciliation loop, divergence detection.",
                }
            ],
            "reasoning": "Articulated idempotency keys, exactly-once semantics, reconciliation loop, divergence detection.",
        },
        {
            "competence_id": "postgres-advanced",
            "score": 0.8,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Discussed monthly partitioning, archive strategy, anti-pattern of partitioning by merchant_id.",
                }
            ],
            "reasoning": "Discussed monthly partitioning, archive strategy, anti-pattern of partitioning by merchant_id.",
        },
        {
            "competence_id": "system-design",
            "score": 0.9,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Led the design problem from clarifying questions to operational concerns (reconciliation, DST bug).",
                }
            ],
            "reasoning": "Led the design problem from clarifying questions to operational concerns (reconciliation, DST bug).",
        },
        {
            "competence_id": "payments-domain",
            "score": 0.55,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Worked on Klarna payments reconciliation but not EUR merchant settlements specifically.",
                }
            ],
            "reasoning": "Worked on Klarna payments reconciliation but not EUR merchant settlements specifically.",
        },
        {
            "competence_id": "ownership",
            "score": 0.85,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Concrete DST-incident story including post-mortem and process change.",
                }
            ],
            "reasoning": "Concrete DST-incident story including post-mortem and process change.",
        },
        {
            "competence_id": "mentorship",
            "score": 0.75,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Differentiated approach for mid-level vs junior, honest about lacking a clean metric.",
                }
            ],
            "reasoning": "Differentiated approach for mid-level vs junior, honest about lacking a clean metric.",
        },
    ],
    "process_findings": [
        {
            "finding_type": "leading_question",
            "severity": "minor",
            "citations": [],
            "full_description": "The settlement question already named idempotency keys, so the candidate was handed the concept the answer was supposed to surface.",
            "positive_reframe": "The design question worked well; next round, let the candidate reach for idempotency unprompted to see how she frames the problem herself.",
        },
        {
            "finding_type": "too_detailed",
            "severity": "minor",
            "citations": [],
            "full_description": "Eleven minutes went into PostgreSQL partitioning while mentorship and cross-team work were left to the last three minutes.",
            "positive_reframe": "The depth on partitioning was valuable; a time box on the database block would leave room for the collaboration questions.",
        },
    ],
    "blind_spots": [
        {
            "competence_id": "streaming",
            "human_score": None,
            "suggested_question": "How would you detect and recover from Kafka consumer lag in the settlement pipeline during a peak day?",
        },
    ],
    "red_flags": [],
}

TOMAS_INTERVIEW_ANALYSIS: dict = {
    "data_completeness": "partial",
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
        {
            "competence_id": "python-advanced",
            "score": 0.8,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Async-await fluency, comfortable with FastAPI tradeoffs.",
                }
            ],
            "reasoning": "Async-await fluency, comfortable with FastAPI tradeoffs.",
        },
        {
            "competence_id": "distributed-systems",
            "score": 0.8,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Walked through outbox pattern unprompted.",
                }
            ],
            "reasoning": "Walked through outbox pattern unprompted.",
        },
        {
            "competence_id": "payments-domain",
            "score": 0.9,
            "status": "assessed",
            "citations": [
                {
                    "segment_id": None,
                    "start_sec": None,
                    "end_sec": None,
                    "quote": "Adyen merchant settlement experience.",
                }
            ],
            "reasoning": "Adyen merchant settlement experience.",
        },
        {
            "competence_id": "mentorship",
            "score": None,
            "status": "not_covered",
            "citations": [],
            "reasoning": "Not assessed in this round.",
        },
    ],
    "process_findings": [
        {
            "finding_type": "overloaded_question",
            "severity": "moderate",
            "citations": [],
            "full_description": "Scale, on-call rotation and settlement reconciliation were asked in a single question, and the candidate answered only the last part.",
            "positive_reframe": "Splitting that question into three would give the candidate room to show what he knows about on-call as well.",
        },
    ],
    "blind_spots": [
        {
            "competence_id": "mentorship",
            "human_score": None,
            "suggested_question": "Tell me about a time you mentored a mid-level engineer through their first production incident.",
        },
    ],
    "red_flags": [
        {
            "flag_type": "resume_inconsistency",
            "severity": "minor",
            "evidence": [],
            "description": "The resume dates the merchant settlement work at three years; in the interview the same project was described as roughly eighteen months.",
        },
    ],
}


# ---------------------------------------------------------------------------
# Parsed resumes for the flagship pipeline (HRP-680)
# ---------------------------------------------------------------------------

# ``Candidate.parsed_resume_jsonb`` in the shape the LLM parser emits
# (RESUME_PARSE_PROMPT in prompts.py): ``position`` is the bare job
# title with ``role`` as its back-compat mirror, ``experience`` runs
# newest-first, ``end_date`` is null for the current role. The demo
# renders it through ``ParsedResumeEditor``, which anchors the
# resume-only citation chips on ``company`` + ``start_date — end_date``
# — so ``PRIYA_RESUME_ANALYSIS`` below quotes these entries verbatim.
#
# Keyed by the ASCII email, same lookup key ``_create_candidates`` uses.
# Only the three candidates on the flagship vacancy carry one: they are
# the pipeline the demo tour opens on, and every string here is a row in
# both locale catalogs.
PARSED_RESUMES: dict[str, dict] = {
    DEMO_FIRST_SCREEN_CANDIDATE_EMAIL: {
        "summary": (
            "Nine years in payments infrastructure. Owned the reconciliation "
            "pipeline at Klarna through a Ruby to Python rewrite. Comfortable "
            "on-call, writes ADRs, mentors mid-level engineers."
        ),
        "current_position": "Staff Engineer",
        "years_of_experience": 9,
        "location": "Berlin, Germany",
        "experience": [
            {
                "position": "Staff Engineer",
                "role": "Staff Engineer",
                "company": "Klarna",
                "start_date": "2021",
                "end_date": None,
                "description": (
                    "Owned the payments reconciliation pipeline end to end. Led "
                    "the Ruby to Python rewrite that cut settlement batch "
                    "latency from 40 minutes to 6. On-call for the settlement "
                    "domain; wrote the post-mortem process the team still uses."
                ),
            },
            {
                "position": "Senior Backend Engineer",
                "role": "Senior Backend Engineer",
                "company": "Klarna",
                "start_date": "2018",
                "end_date": "2021",
                "description": (
                    "Built the ledger service on PostgreSQL with monthly "
                    "partitioning and an archive tier. Introduced idempotency "
                    "keys across the payment intake API."
                ),
            },
            {
                "position": "Backend Engineer",
                "role": "Backend Engineer",
                "company": "SoundCloud",
                "start_date": "2016",
                "end_date": "2018",
                "description": (
                    "Python services behind the creator dashboard. First "
                    "exposure to Kafka consumers and at-least-once delivery."
                ),
            },
        ],
        "education": [
            {
                "institution": "TU Berlin",
                "degree": "MSc",
                "field": "Computer Science",
                "start_date": "2013",
                "end_date": "2016",
            },
        ],
        "skills": [
            "Python",
            "FastAPI",
            "asyncio",
            "PostgreSQL",
            "Kafka",
            "Redis",
            "Kubernetes",
            "Technical writing",
        ],
        "languages": [
            {"name": "Russian", "level": "C2"},
            {"name": "English", "level": "C2"},
            {"name": "German", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "AWS Certified Solutions Architect — Associate",
                "issuer": "Amazon Web Services",
                "issued_at": "2022",
            },
        ],
    },
    "priya.shah@example.com": {
        "summary": (
            "Backend developer with three years on customer-support SaaS. "
            "Python and Django services, REST APIs, a first taste of async "
            "work. Studying distributed systems on the side."
        ),
        "current_position": "Software Developer",
        "years_of_experience": 3,
        "location": "Bangalore, India",
        "experience": [
            {
                "position": "Software Developer",
                "role": "Software Developer",
                "company": "Freshworks",
                "start_date": "2023",
                "end_date": None,
                "description": (
                    "Built and maintained REST endpoints for the ticket-routing "
                    "service in Python and Django. Added Redis caching that cut "
                    "the busiest endpoint's p95 from 780 ms to 210 ms. Team of "
                    "four, no on-call rotation."
                ),
            },
            {
                "position": "Junior Backend Developer",
                "role": "Junior Backend Developer",
                "company": "Zoho",
                "start_date": "2022",
                "end_date": "2023",
                "description": (
                    "Maintained the internal reporting APIs and the nightly "
                    "export jobs. First production PostgreSQL work: indexes, "
                    "query plans, a few schema migrations under review."
                ),
            },
        ],
        "education": [
            {
                "institution": "PES University",
                "degree": "BTech",
                "field": "Computer Science",
                "start_date": "2018",
                "end_date": "2022",
            },
        ],
        "skills": [
            "Python",
            "Django",
            "REST APIs",
            "PostgreSQL",
            "Redis",
            "Unit testing",
        ],
        "languages": [
            {"name": "English", "level": "C1"},
            {"name": "Hindi", "level": "C2"},
        ],
        "certificates": [
            {
                "name": "AWS Certified Cloud Practitioner",
                "issuer": "Amazon Web Services",
                "issued_at": "2024",
            },
        ],
    },
    "tomas.becker@example.com": {
        "summary": (
            "Seven years of backend work, the last stretch on merchant "
            "settlement at Adyen. Python and Go services, event-driven "
            "pipelines, direct EUR settlement experience."
        ),
        "current_position": "Senior Backend Engineer",
        "years_of_experience": 7,
        "location": "Barcelona, Spain",
        "experience": [
            {
                "position": "Senior Backend Engineer",
                "role": "Senior Backend Engineer",
                "company": "Adyen",
                "start_date": "2021",
                "end_date": None,
                # Three years here on purpose: the seeded red flag on
                # TOMAS_INTERVIEW_ANALYSIS calls out exactly this
                # sentence against the eighteen months he gave in the
                # screen, so the flag now has a resume to point at.
                "description": (
                    "Merchant settlement pipeline for EUR payouts, three years "
                    "on the settlement reconciliation service. Introduced the "
                    "outbox pattern to stop double payouts on partial failures."
                ),
            },
            {
                "position": "Backend Engineer",
                "role": "Backend Engineer",
                "company": "Typeform",
                "start_date": "2018",
                "end_date": "2021",
                "description": (
                    "Python services behind the form-response API. Moved the "
                    "export pipeline onto Kafka."
                ),
            },
        ],
        "education": [
            {
                "institution": "Universitat Politecnica de Catalunya",
                "degree": "BSc",
                "field": "Computer Engineering",
                "start_date": "2014",
                "end_date": "2018",
            },
        ],
        "skills": [
            "Python",
            "Go",
            "FastAPI",
            "Kafka",
            "PostgreSQL",
            "Kubernetes",
            "Event-driven architecture",
        ],
        "languages": [
            {"name": "Spanish", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Certified Kubernetes Application Developer",
                "issuer": "Cloud Native Computing Foundation",
                "issued_at": "2021",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Resume-only AI analysis (HRP-680)
# ---------------------------------------------------------------------------

# Mirrors ``ResumeOnlyAnalysisResult`` (prompts_interview.py) — the
# payload ``run_resume_only_analysis_task`` writes. Priya is the only
# candidate this mode can honestly describe: she has no interview (so
# a full run has nothing to read) and her ``not_recommended`` verdict
# clears ``apply_resume_only_verdict_guard``, which rewrites
# ``recommended`` in this mode.
#
# ``resume_excerpts`` are verbatim slices of
# ``PARSED_RESUMES["priya.shah@example.com"]`` and carry the
# ``source_company`` / ``source_period`` pair the parsed-resume editor
# matches on — the citation chips have to land on a real resume item,
# not on a section header.
PRIYA_RESUME_ANALYSIS: dict = {
    "data_completeness": "partial",
    "competence_assessments": [
        {
            "competence_id": "python-advanced",
            "score": 0.45,
            "status": "assessed",
            "resume_excerpts": [
                {
                    "section": "experience",
                    "excerpt_text": "Built and maintained REST endpoints for the ticket-routing service in Python and Django.",
                    "source_company": "Freshworks",
                    "source_period": "2023",
                },
                {
                    "section": "skills",
                    "excerpt_text": "Python",
                    "source_company": None,
                    "source_period": None,
                },
            ],
            "reasoning": "Three years of Python service work, but nothing in the resume shows async, typing or framework-internals depth at the level this role asks for.",
            "confidence": "medium",
        },
        {
            "competence_id": "postgres-advanced",
            "score": 0.3,
            "status": "assessed",
            "resume_excerpts": [
                {
                    "section": "experience",
                    "excerpt_text": "First production PostgreSQL work: indexes, query plans, a few schema migrations under review.",
                    "source_company": "Zoho",
                    "source_period": "2022 — 2023",
                },
            ],
            "reasoning": "Indexes and query plans under review is junior-level exposure; no partitioning, replication or incident work is claimed.",
            "confidence": "high",
        },
        {
            "competence_id": "distributed-systems",
            "score": None,
            "status": "insufficient",
            "resume_excerpts": [
                {
                    "section": "summary",
                    "excerpt_text": "Studying distributed systems on the side.",
                    "source_company": None,
                    "source_period": None,
                },
                {
                    "section": "education",
                    "excerpt_text": "PES University",
                    "source_company": None,
                    "source_period": None,
                },
            ],
            "reasoning": "Self-study and a CS degree are mentioned; nothing in the work history shows a distributed system she operated.",
            "confidence": "low",
        },
        {
            "competence_id": "ownership",
            "score": None,
            "status": "insufficient",
            "resume_excerpts": [
                {
                    "section": "experience",
                    "excerpt_text": "Team of four, no on-call rotation.",
                    "source_company": "Freshworks",
                    "source_period": "2023",
                },
            ],
            "reasoning": "One measurable improvement is claimed, but the resume states there was no on-call rotation, so production ownership cannot be judged from it.",
            "confidence": "low",
        },
        {
            "competence_id": "system-design",
            "score": None,
            "status": "not_covered",
            "resume_excerpts": [],
            "reasoning": "The resume names no design work she led.",
            "confidence": "low",
        },
        {
            "competence_id": "streaming",
            "score": None,
            "status": "not_covered",
            "resume_excerpts": [],
            "reasoning": "No Kafka, Kinesis or queue work appears anywhere in the resume.",
            "confidence": "low",
        },
        {
            "competence_id": "payments-domain",
            "score": None,
            "status": "not_covered",
            "resume_excerpts": [],
            "reasoning": "Both employers are support and productivity SaaS; no payments exposure is claimed.",
            "confidence": "low",
        },
        {
            "competence_id": "mentorship",
            "score": None,
            "status": "not_covered",
            "resume_excerpts": [],
            "reasoning": "No mentoring, onboarding or review-leadership is mentioned.",
            "confidence": "low",
        },
    ],
    "blind_spots": [
        {
            "competence_id": "system-design",
            "human_score": None,
            "suggested_question": "Walk me through the largest change you designed yourself at Freshworks and what you would do differently now.",
        },
        {
            "competence_id": "streaming",
            "human_score": None,
            "suggested_question": "Have you worked with a queue or an event log in production, and what went wrong the first time?",
        },
        {
            "competence_id": "payments-domain",
            "human_score": None,
            "suggested_question": "What do you know about settlement and reconciliation, and where would you start reading?",
        },
        {
            "competence_id": "mentorship",
            "human_score": None,
            "suggested_question": "Who have you helped level up on your team, and how did you go about it?",
        },
    ],
    "red_flags": [],
    "verdict": "not_recommended",
    # The four verdict strings are the candidate fixture's own AI copy —
    # one analysis, one story, and no second set of catalog entries.
    "verdict_summary": (
        "Three years of experience overall, mostly small-team work, no "
        "senior-level backend ownership demonstrated."
    ),
    "key_strength": "Self-driven; has earned AWS Cloud Practitioner and pursues algorithmic study.",
    "key_risk": "Years of experience and scope are below the senior bar for this role.",
    "risk_mitigation": "Decline for senior role; consider for future mid-level opening if pipeline has room.",
    "recommendation_for_next_step": "reject",
}
