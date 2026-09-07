"""Extra recruitment fixtures for the demo seed (HRP-281 — S7).

Layered on top of the HRP-250 recruitment seed (3 vacancies + 6
candidates + 2 deep-analyzed interviews). Adds four more vacancies,
twelve more candidates, and the interview rows covering the
non-completed states (scheduled / in_progress / completed without
analysis / archived) so the recruitment funnel shows every
status the kanban supports — not just the AI-analyzed entry point
the demo opens on.

HRP-666: at most three candidates per vacancy (four on ``em-frontend``,
which carries the internal applicant). A funnel a visitor can read end
to end in one glance beats a long list where every row looks the same.

HRP-726: every candidate here now carries the same three things the
headline funnel's candidates carry — a parsed resume
(``EXTRA_PARSED_RESUMES``), an analysis run built from
``competence_notes``, and (bar one per funnel) a manager round from
``manager_scores``. Before that the list rows printed an AI score and a
verdict straight out of the ``ai_*`` mirror columns while the candidate
card behind them was blank, which is the bug this ticket names: the
list is supposed to summarise the card, not make claims of its own.
One candidate per funnel keeps an empty MANAGER column on purpose —
"Not scored yet" is a true state, and the demo should show it.

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
#
# ``position_key`` resolves against the seeded company ladder
# (``seed_data_company.POSITIONS``) and fills ``Vacancy.position_id`` —
# the Position column of the vacancy list reads it, and printed "---"
# for all seven roles until HRP-726. ``library_competences`` are the
# library-linked requirements the internal matcher scores employees on;
# without them the vacancy opens on the "add competences first" banner
# and "search inside first" has nothing to rank.

EXTRA_VACANCIES: list[dict] = [
    {
        "key": "em-frontend",
        "position_key": "p-em-frontend",
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
        "library_competences": [
            {"competence_key": "c-react", "skill_level_key": "sl-l3"},
            {"competence_key": "c-mentoring", "skill_level_key": "sl-l2"},
        ],
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
        "position_key": "p-be-l1",
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
        "library_competences": [
            {"competence_key": "c-python", "skill_level_key": "sl-l1"},
            {"competence_key": "c-postgres", "skill_level_key": "sl-l1"},
        ],
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
        "position_key": "p-designer-senior",
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
        "library_competences": [
            {"competence_key": "c-design-systems", "skill_level_key": "sl-l3"},
            {"competence_key": "c-user-research", "skill_level_key": "sl-l2"},
        ],
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
        "position_key": "p-recruiter",
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
        "library_competences": [
            {"competence_key": "c-hiring", "skill_level_key": "sl-l3"},
            {"competence_key": "c-cross-fn", "skill_level_key": "sl-l2"},
        ],
        "profile": {
            "competences": [
                {"id": "hiring", "name": "Hiring", "must_have": True},
                {
                    "id": "people-ops",
                    "name": "People ops fundamentals",
                    "must_have": True,
                },
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Seeded transcripts for the extras' interview-backed candidates (HRP-726)
# ---------------------------------------------------------------------------
#
# Inline strings, same reasoning as ``seed_data._SOFIA_TRANSCRIPT``: one
# ``transcript`` value is one catalog entry per interview instead of a
# three-file asset set per locale. Diarized ``[HH:MM:SS] Speaker: line``
# so ``parse_transcript_segments`` can lay down InterviewSegment rows.

_MARCUS_TRANSCRIPT = """Interview - Engineering Manager - Frontend
Candidate: Marcus Johnson

[00:00:15] Recruiter: You already run half of this org informally. Why apply for the title?

[00:01:00] Candidate: Because the half I do not run is the half that matters. I set technical direction and nobody asks me about headcount, performance or pay. I would rather own the whole thing than keep doing the easy part.

[00:03:20] Recruiter: You have never carried headcount. What worries you?

[00:04:05] Candidate: Saying no to people I have shipped with for three years. I know how that reads from the other side because I have been on the other side.

[00:07:10] Recruiter: The design system is yours today. Who takes it?

[00:07:55] Candidate: Anna. She has done the last four migrations and I have been reviewing less each time on purpose.

[00:10:30] Recruiter: Performance cycle - you have never run one. How would you start?

[00:11:15] Candidate: With the People Partner in the room for the first two quarters. I would rather be slow and calibrated than fast and wrong about somebody's year.

[00:14:40] Recruiter: What breaks first if we give you this?

[00:15:20] Candidate: The on-call rotation, because I am in it. I would hand it over in the first month rather than pretend I can do both.
"""

_MEI_TRANSCRIPT = """Interview - Senior Product Designer - Mobile
Candidate: Mei Chen

[00:00:14] Recruiter: The flight-booking redesign at Booking - what was the hardest call?

[00:01:10] Candidate: Cutting the fare comparison table on mobile. It tested well with power users and badly with everyone else. We shipped the simpler thing and the power users were louder for two weeks and then quiet.

[00:03:45] Recruiter: How did you know it was the right call?

[00:04:30] Candidate: Completion rate on small screens went up eleven percent and support contacts about fares did not move. If contacts had moved I would have put it back.

[00:07:20] Recruiter: This app is for hiring managers, not travellers. Different world.

[00:08:00] Candidate: It is, and I have not designed for B2B before. What I would keep is the method - watch five of them do the job on their own phone before I open Figma.

[00:11:15] Recruiter: Interaction design on a small screen with dense data. How do you approach it?

[00:12:00] Candidate: Decide what the one action is per screen, then fight for it. Everything else is progressive disclosure or it belongs on the desktop.

[00:15:10] Recruiter: What would you need from engineering?

[00:15:50] Candidate: A component library that is real, not a Figma file. I would rather ship four screens with real components than twelve mockups.
"""

_KARIM_TRANSCRIPT = """Interview - Recruitment Lead
Candidate: Karim Haddad

[00:00:12] Recruiter: You took HelloFresh recruiting from three to twelve. What did you get wrong?

[00:01:05] Candidate: I hired for volume before I hired for calibration. The first four recruiters each had their own bar and hiring managers noticed before I did.

[00:03:30] Recruiter: How did you fix it?

[00:04:10] Candidate: Scorecards per role, written before the first screen, and a monthly review of the rejections rather than the offers. Rejections are where the bar actually lives.

[00:07:00] Recruiter: We want three to seven, not three to twelve. Different problem?

[00:07:40] Candidate: Smaller and harder. At seven every hire is twelve percent of the team, so a bad one is visible for a year. I would go slower on the first two.

[00:10:45] Recruiter: Half player, half coach. Which half do you drop when it gets busy?

[00:11:30] Candidate: Honestly, the coaching - and that is the failure mode I would want you to watch me for. I would put a standing hour per recruiter in the calendar and treat it as unmovable.

[00:14:20] Recruiter: What would you change in our process in week one?

[00:15:00] Candidate: Nothing. I would sit in on eight interviews first. Changing a process you have not watched is how you lose the hiring managers.
"""


# ---------------------------------------------------------------------------
# Extra candidates (12 entries across 5 vacancy keys)
# ---------------------------------------------------------------------------
#
# ``analysis_mode`` picks the run ``build_candidate_analysis`` builds:
# ``full`` for the one interview-backed candidate per funnel (the row a
# presenter opens on), ``resume_only`` for the rest. The resume-only
# verdict guard forbids ``recommended`` in that mode, so a resume-only
# spec's ``ai_verdict`` is ``needs_check`` or ``not_recommended`` — and
# because the run reuses those same ``ai_*`` strings, the verdict a
# visitor reads in the list is literally the verdict on the card.

EXTRA_CANDIDATES: list[dict] = [
    # --- em-frontend pipeline (4) ---
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
        "ai_verdict": "needs_check",
        "ai_summary": "Solid EM with 4 years at N26 leading frontend org.",
        "ai_strength": "Built out the recruiter onboarding programme single-handedly.",
        "ai_risk": "Has not led a fully-remote team before.",
        "ai_mitigation": "Probe remote management approach in the panel.",
        "interview_kind": "completed_no_ai",
        "analysis_mode": "resume_only",
        "next_step": "second_interview",
        "competence_notes": [
            {
                "competence_id": "hiring",
                "score": 0.8,
                "status": "assessed",
                "reasoning": "Built the recruiter onboarding programme at N26 on his own.",
                "source_company": "N26",
                "source_period": "2022",
                "skill": "Hiring",
            },
            {
                "competence_id": "react",
                "score": 0.7,
                "status": "assessed",
                "reasoning": "Owned a large React application at Typeform before moving into management.",
                "source_company": "Typeform",
                "source_period": "2018 — 2022",
            },
            {
                "competence_id": "mentoring",
                "score": 0.65,
                "status": "assessed",
                "reasoning": "Leads three squads and twelve engineers, but the resume names no one he grew.",
                "source_company": "N26",
                "source_period": "2022",
            },
            {
                "competence_id": "design-systems",
                "score": None,
                "status": "not_covered",
                "reasoning": "No design-system ownership on the resume.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "design-systems",
                "human_score": None,
                "suggested_question": "Who owns the design system on your team today, and what do you do when a squad forks it?",
            },
        ],
        "manager_scores": {"react": 3, "hiring": 3, "mentoring": 3},
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
        "ai_verdict": "needs_check",
        "ai_summary": "Strong tech-lead profile; transitioning into pure people management.",
        "ai_strength": "Owned the Stripe Dashboard React migration end-to-end.",
        "ai_risk": "Limited hands-on hiring experience.",
        "ai_mitigation": "Hiring panel will probe interview calibration.",
        "interview_kind": "in_progress_upload",
        "analysis_mode": "resume_only",
        "next_step": "schedule_interview",
        "competence_notes": [
            {
                "competence_id": "react",
                "score": 0.9,
                "status": "assessed",
                "reasoning": "Ran the Stripe Dashboard React migration end to end.",
                "source_company": "Stripe",
                "source_period": "2019",
                "skill": "React",
            },
            {
                "competence_id": "design-systems",
                "score": 0.75,
                "status": "assessed",
                "reasoning": "Kept the dashboard component library through the migration.",
                "source_company": "Stripe",
                "source_period": "2019",
            },
            {
                "competence_id": "hiring",
                "score": 0.4,
                "status": "insufficient",
                "reasoning": "Interviews regularly, but has never owned a hiring bar.",
                "source_company": "Stripe",
                "source_period": "2019",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "hiring",
                "human_score": None,
                "suggested_question": "How do you calibrate two interviewers who disagree about the same candidate?",
            },
        ],
        "manager_scores": {"react": 4, "design-systems": 3, "hiring": 2},
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
        # The em-frontend funnel's honest "Not scored yet" row.
        "analysis_mode": "resume_only",
        "next_step": "reject",
        "competence_notes": [
            {
                "competence_id": "design-systems",
                "score": 0.85,
                "status": "assessed",
                "reasoning": "Owns the Productboard design system and its migration path.",
                "source_company": "Productboard",
                "source_period": "2021",
                "skill": "Design systems",
            },
            {
                "competence_id": "react",
                "score": 0.8,
                "status": "assessed",
                "reasoning": "Seven years of React, the last three on a component library.",
                "source_company": "Productboard",
                "source_period": "2021",
                "skill": "React",
            },
            {
                "competence_id": "mentoring",
                "score": None,
                "status": "not_covered",
                "reasoning": "No mentoring or lead work on the resume.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "mentoring",
                "human_score": None,
                "suggested_question": "What is the last thing you taught someone on your team, and how did you check it landed?",
            },
        ],
    },
    {
        # HRP-679: the demo's one internal applicant — the deputy head of
        # the very division this role manages, applying from the inside.
        # ``employee_index`` indexes the seeded employee roster
        # (``EMPLOYEE_ASSIGNMENTS`` / ``NAME_POOL``); the seed gives him
        # and his ``User`` row a shared ``Person`` so ``is_employee``
        # resolves true and the badge shows up on a live demo.
        #
        # ``first_name`` / ``last_name`` / ``email`` mirror that roster
        # entry so the i18n coverage guard sees a name it already knows,
        # but the seed reads the real identity off the resolved ``User``:
        # ``localized_name_pool`` translates both name and email, so a
        # de/ru demo would otherwise show an "internal" candidate whose
        # name matches nobody on staff.
        #
        # HRP-726: he is also this funnel's interview-backed candidate.
        # The badge is the demo's only internal-mobility moment, so the
        # card behind it has to be the fullest one on the vacancy.
        "vacancy_key": "em-frontend",
        "employee_index": 12,
        "first_name": "Marcus",
        "last_name": "Johnson",
        "email": "marcus.johnson@demo.example.com",
        "location": "Berlin (hybrid)",
        "current_position": "Frontend Engineer L3",
        "years": 6,
        "status": "interview",
        "ai_score": 0.88,
        "ai_verdict": "recommended",
        "ai_summary": "Already deputy head of the division this role manages.",
        "ai_strength": "Runs the design system and the frontend on-call rotation.",
        "ai_risk": "Never carried headcount or run a performance cycle.",
        "ai_mitigation": "Pair with the People Partner for the first two quarters.",
        "interview_kind": None,
        "analysis_mode": "full",
        "next_step": "final_decision",
        "title_prefix": "Technical interview — ",
        "interview_note": "Investor demo interview (S7 extras).",
        "duration_minutes": 45,
        "days_ago": 3,
        "transcript": _MARCUS_TRANSCRIPT,
        "competence_notes": [
            {
                "competence_id": "design-systems",
                "score": 0.9,
                "status": "assessed",
                "reasoning": "Owns the design system today and has already handed the last four migrations to someone else.",
            },
            {
                "competence_id": "react",
                "score": 0.85,
                "status": "assessed",
                "reasoning": "Six years on the frontend of this product; still in the on-call rotation.",
            },
            {
                "competence_id": "mentoring",
                "score": 0.8,
                "status": "assessed",
                "reasoning": "Named a successor and described reducing his own review load on purpose.",
            },
            {
                "competence_id": "hiring",
                "score": 0.45,
                "status": "insufficient",
                "reasoning": "Has interviewed, but never owned headcount or a performance cycle.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "hiring",
                "human_score": None,
                "suggested_question": "Walk me through a performance conversation you would dread having with someone you have shipped with.",
            },
        ],
        "process_findings": [
            {
                "finding_type": "leading_question",
                "severity": "minor",
                "citations": [],
                "full_description": "The question named the missing headcount experience, so the candidate answered the worry rather than surfacing his own.",
                "positive_reframe": "Ask what he expects to be worst at in the first quarter and let him name it.",
            },
        ],
        "manager_scores": {
            "react": 4,
            "design-systems": 4,
            "mentoring": 3,
            "hiring": 2,
        },
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
        "interview_kind": None,
        "analysis_mode": "resume_only",
        "next_step": "schedule_interview",
        "competence_notes": [
            {
                "competence_id": "python",
                "score": 0.6,
                "status": "assessed",
                "reasoning": "Three side projects in Python, each deployed and still running.",
                "source_company": "Le Wagon Berlin",
                "source_period": "2025 — 2026",
                "skill": "Python",
            },
            {
                "competence_id": "sql-basics",
                "score": 0.5,
                "status": "assessed",
                "reasoning": "Wrote the schema behind her booking project herself.",
                "source_company": "Le Wagon Berlin",
                "source_period": "2025 — 2026",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "python",
                "human_score": None,
                "suggested_question": "What broke in production on one of your projects, and how did you find it?",
            },
        ],
        "manager_scores": {"python": 2, "sql-basics": 2},
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
        "interview_kind": "scheduled",
        "analysis_mode": "resume_only",
        "next_step": "schedule_interview",
        "competence_notes": [
            {
                "competence_id": "python",
                "score": 0.62,
                "status": "assessed",
                "reasoning": "Two years of internal tooling at Zalando, shipped and maintained.",
                "source_company": "Zalando",
                "source_period": "2024",
                "skill": "Python",
            },
            {
                "competence_id": "sql-basics",
                "score": 0.55,
                "status": "assessed",
                "reasoning": "Reporting queries against the warehouse, reviewed by a senior.",
                "source_company": "Zalando",
                "source_period": "2024",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "sql-basics",
                "human_score": None,
                "suggested_question": "How would you find out why a query that used to be fast is now slow?",
            },
        ],
        "manager_scores": {"python": 3, "sql-basics": 2},
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
        "ai_verdict": "not_recommended",
        "ai_summary": "Self-taught with two paying micro-SaaS projects.",
        "ai_strength": "Demonstrated ability to ship.",
        "ai_risk": "No team-based experience.",
        "ai_mitigation": "Pair-programming trial.",
        "interview_kind": None,
        # The junior funnel's honest "Not scored yet" row.
        "analysis_mode": "resume_only",
        "next_step": "reject",
        "competence_notes": [
            {
                "competence_id": "python",
                "score": 0.5,
                "status": "assessed",
                "reasoning": "Two paying micro-SaaS products, both written and operated alone.",
                "source_company": "Independent",
                "source_period": "2024",
                "skill": "Python",
            },
            {
                "competence_id": "sql-basics",
                "score": None,
                "status": "not_covered",
                "reasoning": "The resume never says what the data layer was.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "sql-basics",
                "human_score": None,
                "suggested_question": "Which database is behind your products, and why that one?",
            },
        ],
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
        "interview_kind": None,
        "analysis_mode": "full",
        "next_step": "final_decision",
        "title_prefix": "Portfolio review — ",
        "interview_note": "Investor demo interview (S7 extras).",
        "duration_minutes": 45,
        "days_ago": 5,
        "transcript": _MEI_TRANSCRIPT,
        "competence_notes": [
            {
                "competence_id": "ux-mobile",
                "score": 0.9,
                "status": "assessed",
                "reasoning": "Cut the fare table on small screens and defended the call with a completion-rate number.",
            },
            {
                "competence_id": "user-research",
                "score": 0.8,
                "status": "assessed",
                "reasoning": "Would watch five hiring managers work on their own phone before opening Figma.",
            },
            {
                "competence_id": "design-systems",
                "score": 0.7,
                "status": "assessed",
                "reasoning": "Asks for a real component library rather than a Figma file, but has not built one.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "design-systems",
                "human_score": None,
                "suggested_question": "What would you put in the first version of a component library for this app?",
            },
        ],
        "process_findings": [
            {
                "finding_type": "too_detailed",
                "severity": "minor",
                "citations": [],
                "full_description": "Seven minutes on one Booking case study left the B2B gap with a single question.",
                "positive_reframe": "The case study was convincing; move it earlier and spend the saved time on the unfamiliar domain.",
            },
        ],
        "manager_scores": {"ux-mobile": 4, "user-research": 3, "design-systems": 3},
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
        "ai_verdict": "needs_check",
        "ai_summary": "Strong UX background; lighter on mobile than Mei.",
        "ai_strength": "Strong systems-thinking and Figma library ownership.",
        "ai_risk": "Mobile portfolio is thin.",
        "ai_mitigation": "Ask for relevant mobile case studies in next round.",
        "interview_kind": None,
        "analysis_mode": "resume_only",
        "next_step": "schedule_interview",
        "competence_notes": [
            {
                "competence_id": "design-systems",
                "score": 0.85,
                "status": "assessed",
                "reasoning": "Owns the Klarna Figma library and the rules around it.",
                "source_company": "Klarna",
                "source_period": "2020",
                "skill": "Design systems",
            },
            {
                "competence_id": "user-research",
                "score": 0.7,
                "status": "assessed",
                "reasoning": "Runs usability sessions per release, mostly on desktop.",
                "source_company": "Klarna",
                "source_period": "2020",
            },
            {
                "competence_id": "ux-mobile",
                "score": 0.45,
                "status": "insufficient",
                "reasoning": "Mobile work appears once, and only as a companion to the web product.",
                "source_company": "Spotify",
                "source_period": "2017 — 2020",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "ux-mobile",
                "human_score": None,
                "suggested_question": "Which of your screens would you redraw for a phone, and what would you drop?",
            },
        ],
        "manager_scores": {"design-systems": 4, "user-research": 3, "ux-mobile": 2},
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
        "interview_kind": "archived",
        # The designer-mobile funnel's honest "Not scored yet" row.
        "analysis_mode": "resume_only",
        "next_step": "reject",
        "competence_notes": [
            {
                "competence_id": "ux-mobile",
                "score": 0.7,
                "status": "assessed",
                "reasoning": "Owns the Satispay mobile onboarding flow end to end.",
                "source_company": "Satispay",
                "source_period": "2022",
            },
            {
                "competence_id": "design-systems",
                "score": None,
                "status": "not_covered",
                "reasoning": "Consumes a design system; the resume shows no ownership.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "user-research",
                "human_score": None,
                "suggested_question": "What did the last round of user testing change in your onboarding flow?",
            },
        ],
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
        # HRP-726: the previous pair described this vacancy as still a
        # draft. It has been published since the HRP-281 review, so the
        # card was contradicting the vacancy it sat on.
        "ai_risk": "Coaching is the first thing he drops when the pipeline gets busy.",
        "ai_mitigation": "Agree a standing weekly hour per recruiter before the first hire.",
        "interview_kind": None,
        "analysis_mode": "full",
        "next_step": "final_decision",
        "title_prefix": "Hiring manager interview — ",
        "interview_note": "Investor demo interview (S7 extras).",
        "duration_minutes": 40,
        "days_ago": 2,
        "transcript": _KARIM_TRANSCRIPT,
        "competence_notes": [
            {
                "competence_id": "hiring",
                "score": 0.85,
                "status": "assessed",
                "reasoning": "Reviews rejections rather than offers, because that is where the bar actually lives.",
            },
            {
                "competence_id": "people-ops",
                "score": 0.7,
                "status": "assessed",
                "reasoning": "Named his own failure mode and proposed the calendar fix for it unprompted.",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "people-ops",
                "human_score": None,
                "suggested_question": "How would you handle a hiring manager who keeps rejecting everyone you send?",
            },
        ],
        "process_findings": [
            {
                "finding_type": "leading_question",
                "severity": "minor",
                "citations": [],
                "full_description": "The half-player-half-coach question named the trade-off, so the candidate confirmed it rather than choosing it.",
                "positive_reframe": "Ask how he spent last week instead, and let the split show itself.",
            },
        ],
        "manager_scores": {"hiring": 4, "people-ops": 3},
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
        "ai_verdict": "needs_check",
        "ai_summary": "Strong fintech-design background, can carry a domain.",
        "ai_strength": "Owned Monzo's business onboarding flow.",
        "ai_risk": "Less HRtech exposure.",
        "ai_mitigation": "Walk through HR Pulsar workflows to gauge interest.",
        "interview_kind": None,
        "analysis_mode": "resume_only",
        "next_step": "schedule_interview",
        "competence_notes": [
            {
                "competence_id": "product-design",
                "score": 0.8,
                "status": "assessed",
                "reasoning": "Owned the Monzo business onboarding flow from first draft to launch.",
                "source_company": "Monzo",
                "source_period": "2021",
            },
            {
                "competence_id": "user-research",
                "score": 0.65,
                "status": "assessed",
                "reasoning": "Interviews her own users, with a researcher on the larger studies.",
                "source_company": "Monzo",
                "source_period": "2021",
                "skill": "User research",
            },
            {
                "competence_id": "design-systems",
                "score": 0.6,
                "status": "assessed",
                "reasoning": "Contributes to a shared library rather than owning one.",
                "source_company": "Monzo",
                "source_period": "2021",
            },
        ],
        "blind_spots": [
            {
                "competence_id": "design-systems",
                "human_score": None,
                "suggested_question": "What would you change first in a design system you inherited?",
            },
        ],
        "manager_scores": {
            "product-design": 3,
            "user-research": 3,
            "design-systems": 3,
        },
    },
]


# ---------------------------------------------------------------------------
# Parsed resumes for the extras (HRP-726)
# ---------------------------------------------------------------------------
#
# Same payload shape as ``seed_data.PARSED_RESUMES`` — the parser's field
# names, newest-first experience — and held to the same guard. Keyed by
# the spec ``email`` (the structural key), not by the display name: the
# internal applicant's real address comes off his seeded ``User`` row,
# so the seed looks the resume up by the fixture key and writes it onto
# whichever Candidate that spec produced.
#
# ``company`` / ``start_date`` / ``end_date`` are load-bearing beyond
# display: a resume-only citation chip anchors on (company, period), so
# a ``source_company`` in ``competence_notes`` that names no experience
# entry here is a chip that opens the resume on nothing.

EXTRA_PARSED_RESUMES: dict[str, dict] = {
    "mateo.garcia@example.com": {
        "summary": (
            "Eight years in frontend, the last four managing. Runs three "
            "squads at N26 and built the recruiter onboarding programme "
            "the org still uses."
        ),
        "current_position": "Engineering Manager",
        "years_of_experience": 8,
        "location": "Barcelona, Spain",
        "experience": [
            {
                "position": "Engineering Manager",
                "role": "Engineering Manager",
                "company": "N26",
                "start_date": "2022",
                "end_date": None,
                "description": (
                    "Leads three frontend squads, twelve engineers. Built the "
                    "recruiter onboarding programme single-handedly."
                ),
            },
            {
                "position": "Senior Frontend Engineer",
                "role": "Senior Frontend Engineer",
                "company": "Typeform",
                "start_date": "2018",
                "end_date": "2022",
                "description": (
                    "Owned the form-builder React application and the "
                    "component library it shipped on."
                ),
            },
        ],
        "education": [
            {
                "institution": "Universitat Politecnica de Catalunya",
                "degree": "BSc",
                "field": "Computer Science",
                "start_date": "2013",
                "end_date": "2017",
            },
        ],
        "skills": ["React", "TypeScript", "Hiring", "Mentoring"],
        "languages": [
            {"name": "Spanish", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Certified ScrumMaster",
                "issuer": "Scrum Alliance",
                "issued_at": "2019",
            },
        ],
    },
    "helena.brennan@example.com": {
        "summary": (
            "Nine years of frontend engineering, four of them as tech lead. "
            "Wants the people half of the job next."
        ),
        "current_position": "Tech Lead",
        "years_of_experience": 9,
        "location": "Dublin, Ireland",
        "experience": [
            {
                "position": "Tech Lead",
                "role": "Tech Lead",
                "company": "Stripe",
                "start_date": "2019",
                "end_date": None,
                "description": (
                    "Ran the Dashboard React migration end to end and kept "
                    "the component library through it. Interviews weekly."
                ),
            },
            {
                "position": "Frontend Engineer",
                "role": "Frontend Engineer",
                "company": "Intercom",
                "start_date": "2016",
                "end_date": "2019",
                "description": (
                    "Built the messenger settings surface and its first "
                    "automated visual tests."
                ),
            },
        ],
        "education": [
            {
                "institution": "Trinity College Dublin",
                "degree": "BSc",
                "field": "Computer Science",
                "start_date": "2012",
                "end_date": "2016",
            },
        ],
        "skills": ["React", "TypeScript", "Design systems", "Technical writing"],
        "languages": [
            {"name": "English", "level": "C2"},
        ],
        "certificates": [
            {
                "name": "Certified ScrumMaster",
                "issuer": "Scrum Alliance",
                "issued_at": "2021",
            },
        ],
    },
    "pavel.novak@example.com": {
        "summary": (
            "Seven years of frontend work, the last three owning a design "
            "system. Deliberately an individual contributor so far."
        ),
        "current_position": "Senior Frontend Engineer",
        "years_of_experience": 7,
        "location": "Prague, Czechia",
        "experience": [
            {
                "position": "Senior Frontend Engineer",
                "role": "Senior Frontend Engineer",
                "company": "Productboard",
                "start_date": "2021",
                "end_date": None,
                "description": (
                    "Owns the design system and its migration path across "
                    "five product surfaces."
                ),
            },
            {
                "position": "Frontend Engineer",
                "role": "Frontend Engineer",
                "company": "Kiwi.com",
                "start_date": "2018",
                "end_date": "2021",
                "description": (
                    "Search and booking screens; first exposure to shared "
                    "component work."
                ),
            },
        ],
        "education": [
            {
                "institution": "Czech Technical University in Prague",
                "degree": "BSc",
                "field": "Computer Science",
                "start_date": "2014",
                "end_date": "2018",
            },
        ],
        "skills": ["React", "TypeScript", "Design systems", "Accessibility"],
        "languages": [
            {"name": "Czech", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Web Accessibility Specialist",
                "issuer": "International Association of Accessibility Professionals",
                "issued_at": "2023",
            },
        ],
    },
    "marcus.johnson@demo.example.com": {
        "summary": (
            "Six years on this product's frontend. Deputy head of the "
            "division, owns the design system and sits in the on-call "
            "rotation."
        ),
        "current_position": "Frontend Engineer L3",
        "years_of_experience": 6,
        "location": "Berlin (hybrid)",
        "experience": [
            {
                "position": "Frontend Engineer L3",
                "role": "Frontend Engineer L3",
                "company": "Pulsar Technologies",
                "start_date": "2022",
                "end_date": None,
                "description": (
                    "Owns the design system and the frontend on-call "
                    "rotation. Deputy head of the division since 2024."
                ),
            },
            {
                "position": "Frontend Engineer",
                "role": "Frontend Engineer",
                "company": "Delivery Hero",
                "start_date": "2020",
                "end_date": "2022",
                "description": (
                    "Courier-facing web app; first component library work."
                ),
            },
        ],
        "education": [
            {
                "institution": "TU Berlin",
                "degree": "BSc",
                "field": "Computer Science",
                "start_date": "2016",
                "end_date": "2020",
            },
        ],
        "skills": ["React", "TypeScript", "Design systems", "Mentoring"],
        "languages": [
            {"name": "German", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Web Accessibility Specialist",
                "issuer": "International Association of Accessibility Professionals",
                "issued_at": "2024",
            },
        ],
    },
    "isabella.ferraro@example.com": {
        "summary": (
            "Career changer out of a Berlin bootcamp. Three Python projects "
            "built end to end and still running."
        ),
        "current_position": "Bootcamp graduate",
        "years_of_experience": 1,
        "location": "Milan, Italy",
        "experience": [
            {
                "position": "Bootcamp graduate",
                "role": "Bootcamp graduate",
                "company": "Le Wagon Berlin",
                "start_date": "2025",
                "end_date": "2026",
                "description": (
                    "Three end-to-end Python projects, each deployed and "
                    "still running. Wrote the schemas herself."
                ),
            },
            {
                "position": "Operations Analyst",
                "role": "Operations Analyst",
                "company": "Esselunga",
                "start_date": "2021",
                "end_date": "2025",
                "description": (
                    "Warehouse reporting. Automated the weekly figures in "
                    "Python, which is how the career change started."
                ),
            },
        ],
        "education": [
            {
                "institution": "University of Milan",
                "degree": "BA",
                "field": "Economics",
                "start_date": "2017",
                "end_date": "2020",
            },
        ],
        "skills": ["Python", "SQL", "FastAPI", "Git"],
        "languages": [
            {"name": "Italian", "level": "C2"},
            {"name": "English", "level": "B2"},
        ],
        "certificates": [
            {
                "name": "Le Wagon Web Development Bootcamp",
                "issuer": "Le Wagon",
                "issued_at": "2026",
            },
        ],
    },
    "jonas.werner@example.com": {
        "summary": (
            "Working student at Zalando for two years alongside a computer "
            "science degree. Ships internal tooling that other people use."
        ),
        "current_position": "Working student",
        "years_of_experience": 1,
        "location": "Hamburg, Germany",
        "experience": [
            {
                "position": "Working student",
                "role": "Working student",
                "company": "Zalando",
                "start_date": "2024",
                "end_date": None,
                "description": (
                    "Built and maintained internal tooling for the logistics "
                    "team. Reporting queries against the warehouse."
                ),
            },
            {
                "position": "Intern",
                "role": "Intern",
                "company": "Otto Group",
                "start_date": "2023",
                "end_date": "2024",
                "description": "Test automation for the checkout service.",
            },
        ],
        "education": [
            {
                "institution": "University of Hamburg",
                "degree": "BSc",
                "field": "Computer Science",
                "start_date": "2022",
                "end_date": "2026",
            },
        ],
        "skills": ["Python", "SQL", "Docker", "Git"],
        "languages": [
            {"name": "German", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "AWS Certified Cloud Practitioner",
                "issuer": "Amazon Web Services",
                "issued_at": "2025",
            },
        ],
    },
    "aline.souza@example.com": {
        "summary": (
            "Self-taught developer with two paying micro-SaaS products. "
            "Everything so far has been built alone."
        ),
        "current_position": "Independent developer",
        "years_of_experience": 2,
        "location": "Lisbon, Portugal",
        "experience": [
            {
                "position": "Independent developer",
                "role": "Independent developer",
                "company": "Independent",
                "start_date": "2024",
                "end_date": None,
                "description": (
                    "Two paying micro-SaaS products, written and operated "
                    "alone. Around 200 paying users between them."
                ),
            },
            {
                "position": "Support Specialist",
                "role": "Support Specialist",
                "company": "Talkdesk",
                "start_date": "2022",
                "end_date": "2024",
                "description": (
                    "Second-line support. Wrote the internal scripts that "
                    "turned into the first product."
                ),
            },
        ],
        "education": [
            {
                "institution": "Instituto Superior Tecnico",
                "degree": "BA",
                "field": "Management",
                "start_date": "2018",
                "end_date": "2021",
            },
        ],
        "skills": ["Python", "FastAPI", "Git"],
        "languages": [
            {"name": "Portuguese", "level": "C2"},
            {"name": "English", "level": "B2"},
        ],
        "certificates": [
            {
                "name": "Le Wagon Web Development Bootcamp",
                "issuer": "Le Wagon",
                "issued_at": "2023",
            },
        ],
    },
    "mei.chen@example.com": {
        "summary": (
            "Six years of mobile-first product design in travel. Owns the "
            "decisions she ships and the numbers behind them."
        ),
        "current_position": "Senior Designer",
        "years_of_experience": 6,
        "location": "Amsterdam, Netherlands",
        "experience": [
            {
                "position": "Senior Designer",
                "role": "Senior Designer",
                "company": "Booking.com",
                "start_date": "2021",
                "end_date": None,
                "description": (
                    "Led the flight-booking redesign. Cut the fare "
                    "comparison table on small screens and lifted completion "
                    "rate by eleven percent."
                ),
            },
            {
                "position": "Product Designer",
                "role": "Product Designer",
                "company": "TravelPerk",
                "start_date": "2019",
                "end_date": "2021",
                "description": (
                    "Trip approval and expense flows for business travellers."
                ),
            },
        ],
        "education": [
            {
                "institution": "Design Academy Eindhoven",
                "degree": "BA",
                "field": "Interaction Design",
                "start_date": "2015",
                "end_date": "2019",
            },
        ],
        "skills": ["Figma", "Mobile UX", "Prototyping", "User research"],
        "languages": [
            {"name": "Chinese", "level": "C2"},
            {"name": "English", "level": "C1"},
            {"name": "Dutch", "level": "B1"},
        ],
        "certificates": [
            {
                "name": "UX Design Certificate",
                "issuer": "Interaction Design Foundation",
                "issued_at": "2020",
            },
        ],
    },
    "oskar.lindgren@example.com": {
        "summary": (
            "Seven years of product design in fintech. Systems thinker; "
            "most of the portfolio is desktop."
        ),
        "current_position": "Senior Designer",
        "years_of_experience": 7,
        "location": "Stockholm, Sweden",
        "experience": [
            {
                "position": "Senior Designer",
                "role": "Senior Designer",
                "company": "Klarna",
                "start_date": "2020",
                "end_date": None,
                "description": (
                    "Owns the Figma library and the rules around it. Runs "
                    "usability sessions every release, mostly on desktop."
                ),
            },
            {
                "position": "Product Designer",
                "role": "Product Designer",
                "company": "Spotify",
                "start_date": "2017",
                "end_date": "2020",
                "description": (
                    "Web player surfaces, with one mobile companion screen."
                ),
            },
        ],
        "education": [
            {
                "institution": "Konstfack",
                "degree": "BA",
                "field": "Visual Communication",
                "start_date": "2013",
                "end_date": "2017",
            },
        ],
        "skills": ["Figma", "Design systems", "User research", "Prototyping"],
        "languages": [
            {"name": "Swedish", "level": "C2"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "UX Design Certificate",
                "issuer": "Interaction Design Foundation",
                "issued_at": "2019",
            },
        ],
    },
    "lina.petrelli@example.com": {
        "summary": (
            "Four years of product design in payments. Owns one flow "
            "end to end; consumes the design system rather than shaping it."
        ),
        "current_position": "Designer",
        "years_of_experience": 4,
        "location": "Turin, Italy",
        "experience": [
            {
                "position": "Designer",
                "role": "Designer",
                "company": "Satispay",
                "start_date": "2022",
                "end_date": None,
                "description": (
                    "Owns the mobile onboarding flow end to end, from first "
                    "screen to identity check."
                ),
            },
            {
                "position": "Junior Designer",
                "role": "Junior Designer",
                "company": "Reply",
                "start_date": "2020",
                "end_date": "2022",
                "description": "Client work: landing pages and small apps.",
            },
        ],
        "education": [
            {
                "institution": "Politecnico di Torino",
                "degree": "BA",
                "field": "Design and Visual Communication",
                "start_date": "2016",
                "end_date": "2020",
            },
        ],
        "skills": ["Figma", "Mobile UX", "Prototyping"],
        "languages": [
            {"name": "Italian", "level": "C2"},
            {"name": "English", "level": "B2"},
        ],
        "certificates": [
            {
                "name": "UX Design Certificate",
                "issuer": "Interaction Design Foundation",
                "issued_at": "2022",
            },
        ],
    },
    "karim.haddad@example.com": {
        "summary": (
            "Ten years in recruiting, the last four leading. Took the "
            "HelloFresh bench from three to twelve and learned what that "
            "costs in calibration."
        ),
        "current_position": "Talent Lead",
        "years_of_experience": 10,
        "location": "Berlin, Germany",
        "experience": [
            {
                "position": "Talent Lead",
                "role": "Talent Lead",
                "company": "HelloFresh",
                "start_date": "2020",
                "end_date": None,
                "description": (
                    "Grew the recruiting team from three to twelve. "
                    "Introduced per-role scorecards and a monthly review of "
                    "rejections rather than offers."
                ),
            },
            {
                "position": "Senior Recruiter",
                "role": "Senior Recruiter",
                "company": "Zalando",
                "start_date": "2016",
                "end_date": "2020",
                "description": ("Technical hiring across two engineering divisions."),
            },
        ],
        "education": [
            {
                "institution": "Humboldt University of Berlin",
                "degree": "MA",
                "field": "Organisational Psychology",
                "start_date": "2012",
                "end_date": "2015",
            },
        ],
        "skills": ["Hiring", "Interview calibration", "Employer branding"],
        "languages": [
            {"name": "Arabic", "level": "C2"},
            {"name": "German", "level": "C1"},
            {"name": "English", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Certified ScrumMaster",
                "issuer": "Scrum Alliance",
                "issued_at": "2018",
            },
        ],
    },
    "saira.kapoor@example.com": {
        "summary": (
            "Seven years of product design in fintech. Carries a domain "
            "rather than a screen; new to HR software."
        ),
        "current_position": "Senior Designer",
        "years_of_experience": 7,
        "location": "London, UK",
        "experience": [
            {
                "position": "Senior Designer",
                "role": "Senior Designer",
                "company": "Monzo",
                "start_date": "2021",
                "end_date": None,
                "description": (
                    "Owned the business onboarding flow from first draft to "
                    "launch. Interviews her own users."
                ),
            },
            {
                "position": "Product Designer",
                "role": "Product Designer",
                "company": "Starling Bank",
                "start_date": "2018",
                "end_date": "2021",
                "description": "Card controls and account switching flows.",
            },
        ],
        "education": [
            {
                "institution": "University of the Arts London",
                "degree": "BA",
                "field": "Graphic Design",
                "start_date": "2014",
                "end_date": "2017",
            },
        ],
        "skills": ["Figma", "User research", "Prototyping", "Design systems"],
        "languages": [
            {"name": "English", "level": "C2"},
            {"name": "Hindi", "level": "C1"},
        ],
        "certificates": [
            {
                "name": "Google UX Design Certificate",
                "issuer": "Google",
                "issued_at": "2019",
            },
        ],
    },
}


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
