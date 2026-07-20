"""Exam fixtures for the demo seed (HRP-281 — S5).

Lays down four MassExams covering every lifecycle status (draft / sent
/ in_progress / done) plus the corresponding ExamPassMarks and a few
Exam assignments per template so the /exams index has chips in every
state.

Question banks are deliberately small (8 single_choice questions per
exam) — the demo lands on the index more than the question editor and
the seed_data file would balloon past the size budget if we materialised
realistic full quizzes here.

``employee_indices`` lists the NAME_POOL indices that get an Exam
assignment for that template; the first entries get ``status=done``
with deterministic scores, the rest sit at ``status=assigned`` or
``in_progress`` based on the template's overall lifecycle.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Mass exams
# ---------------------------------------------------------------------------

MASS_EXAMS: list[dict] = [
    {
        "key": "onboarding-quiz",
        "title": "Engineering Onboarding Quiz",
        "description": "Covers our repo conventions, on-call playbook and security baseline.",
        "status": "in_progress",
        "pass_mark_percent": 70,
        "questions": [
            {
                "title": "Which branch do production deploys merge from?",
                "type": "single_choice",
                "options": [
                    {"title": "main", "is_correct": True},
                    {"title": "develop", "is_correct": False},
                    {"title": "release/latest", "is_correct": False},
                    {"title": "trunk", "is_correct": False},
                ],
            },
            {
                "title": "Pick the practices that belong to our PR review checklist.",
                "type": "multiple_choice",
                "options": [
                    {"title": "Run the test suite locally first", "is_correct": True},
                    {"title": "Include a screenshot for UI changes", "is_correct": True},
                    {"title": "Bypass pre-commit hooks for speed", "is_correct": False},
                    {"title": "Link the Jira ticket in the description", "is_correct": True},
                ],
            },
            {
                "title": "How long is the demo session TTL?",
                "type": "single_choice",
                "options": [
                    {"title": "30 minutes", "is_correct": False},
                    {"title": "4 hours", "is_correct": True},
                    {"title": "24 hours", "is_correct": False},
                    {"title": "7 days", "is_correct": False},
                ],
            },
            {
                "title": "Which database is the primary store?",
                "type": "single_choice",
                "options": [
                    {"title": "PostgreSQL 17", "is_correct": True},
                    {"title": "MySQL 8", "is_correct": False},
                    {"title": "SQLite", "is_correct": False},
                    {"title": "MongoDB", "is_correct": False},
                ],
            },
            {
                "title": "Which task tools must run before READY FOR REVIEW?",
                "type": "multiple_choice",
                "options": [
                    {"title": "ruff check", "is_correct": True},
                    {"title": "Relevant pytest suite", "is_correct": True},
                    {"title": "REDO_REVIEW_CHECKLIST", "is_correct": True},
                    {"title": "git push --force-with-lease", "is_correct": False},
                ],
            },
            {
                "title": "What does the INVESTOR_MARKER tag identify?",
                "type": "single_choice",
                "options": [
                    {"title": "Demo seed rows", "is_correct": True},
                    {"title": "Paying customers", "is_correct": False},
                    {"title": "Beta participants", "is_correct": False},
                    {"title": "Internal employees", "is_correct": False},
                ],
            },
            {
                "title": "Where do enterprise-only Celery beat extras live?",
                "type": "single_choice",
                "options": [
                    {"title": "backend/ee/celery_extras.py", "is_correct": True},
                    {"title": "backend/app/core/celery_app.py", "is_correct": False},
                    {"title": "enterprise/overlay/celery.py", "is_correct": False},
                    {"title": "Nowhere — beat is core-only", "is_correct": False},
                ],
            },
            {
                "title": "Pick the rules that apply to changelog entries.",
                "type": "multiple_choice",
                "options": [
                    {"title": "Entries are English-only", "is_correct": True},
                    {"title": "Enterprise lines are prefixed [Enterprise]", "is_correct": True},
                    {"title": "Include the full PR description", "is_correct": False},
                    {"title": "Public changelog rewrites internal-only items in marketing voice", "is_correct": True},
                ],
            },
        ],
        "employee_indices": [
            (5, "done", 88),
            (17, "done", 65),
            (10, "in_progress", None),
            (15, "in_progress", None),
            (36, "assigned", None),
        ],
    },
    {
        "key": "python-fundamentals",
        "title": "Python Fundamentals",
        "description": "Baseline check for new backend hires before the first sprint.",
        "status": "done",
        "pass_mark_percent": 75,
        "questions": [
            {
                "title": "Which is the correct way to declare a coroutine?",
                "type": "single_choice",
                "options": [
                    {"title": "async def fn(): ...", "is_correct": True},
                    {"title": "def fn(): yield ...", "is_correct": False},
                    {"title": "async fn(): ...", "is_correct": False},
                    {"title": "coroutine fn(): ...", "is_correct": False},
                ],
            },
            {
                "title": "What does the @dataclass decorator generate by default?",
                "type": "multiple_choice",
                "options": [
                    {"title": "__init__", "is_correct": True},
                    {"title": "__repr__", "is_correct": True},
                    {"title": "__eq__", "is_correct": True},
                    {"title": "__hash__", "is_correct": False},
                ],
            },
            {
                "title": "Which type hint represents a list of integers?",
                "type": "single_choice",
                "options": [
                    {"title": "list[int]", "is_correct": True},
                    {"title": "List<int>", "is_correct": False},
                    {"title": "int[]", "is_correct": False},
                    {"title": "Array[int]", "is_correct": False},
                ],
            },
            {
                "title": "How do you safely run an async coroutine from sync code in Python 3.14?",
                "type": "single_choice",
                "options": [
                    {"title": "asyncio.run(coro)", "is_correct": True},
                    {"title": "coro()", "is_correct": False},
                    {"title": "await coro", "is_correct": False},
                    {"title": "asyncio.get_event_loop().run(coro)", "is_correct": False},
                ],
            },
            {
                "title": "What is a typical use of contextlib.asynccontextmanager?",
                "type": "single_choice",
                "options": [
                    {"title": "Wrapping an async setup/teardown into a context manager", "is_correct": True},
                    {"title": "Replacing __init_subclass__", "is_correct": False},
                    {"title": "Synchronising threads", "is_correct": False},
                    {"title": "Memoising functions", "is_correct": False},
                ],
            },
            {
                "title": "Pick all valid SQLAlchemy 2.0 patterns.",
                "type": "multiple_choice",
                "options": [
                    {"title": "Mapped[int] = mapped_column(...)", "is_correct": True},
                    {"title": "session.execute(select(Model))", "is_correct": True},
                    {"title": "Model.query.filter_by(...)", "is_correct": False},
                    {"title": "session.scalars(...).one_or_none()", "is_correct": True},
                ],
            },
            {
                "title": "What does Pydantic v2 use for typed config?",
                "type": "single_choice",
                "options": [
                    {"title": "BaseSettings from pydantic-settings", "is_correct": True},
                    {"title": "BaseConfig from pydantic", "is_correct": False},
                    {"title": "TypedDict", "is_correct": False},
                    {"title": "configparser", "is_correct": False},
                ],
            },
            {
                "title": "Which testing tool do we use for backend unit tests?",
                "type": "single_choice",
                "options": [
                    {"title": "pytest", "is_correct": True},
                    {"title": "unittest", "is_correct": False},
                    {"title": "nose", "is_correct": False},
                    {"title": "tox", "is_correct": False},
                ],
            },
        ],
        "employee_indices": [
            (5, "done", 82),
            (10, "done", 91),
            (4, "done", 68),  # below pass mark
            (17, "done", 78),
        ],
    },
    {
        "key": "security-annual",
        "title": "Security & Compliance Annual",
        "description": "Mandatory annual review of GDPR, secret handling and access policy.",
        "status": "sent",
        "pass_mark_percent": 80,
        "questions": [
            {
                "title": "Where should production secrets be stored?",
                "type": "single_choice",
                "options": [
                    {"title": "In the platform's secret manager", "is_correct": True},
                    {"title": "Committed to .env in the repo", "is_correct": False},
                    {"title": "On engineer laptops", "is_correct": False},
                    {"title": "Pasted into Slack DMs", "is_correct": False},
                ],
            },
            {
                "title": "What is the maximum window to report a personal data breach to the DPO?",
                "type": "single_choice",
                "options": [
                    {"title": "Within 72 hours of detection", "is_correct": True},
                    {"title": "Within 7 days", "is_correct": False},
                    {"title": "Within 30 days", "is_correct": False},
                    {"title": "Only when public", "is_correct": False},
                ],
            },
            {
                "title": "Pick the behaviours that violate our access policy.",
                "type": "multiple_choice",
                "options": [
                    {"title": "Sharing your password with a teammate", "is_correct": True},
                    {"title": "Using SSO for all internal tools", "is_correct": False},
                    {"title": "Storing a customer export on a personal laptop", "is_correct": True},
                    {"title": "Rotating API keys after a known compromise", "is_correct": False},
                ],
            },
            {
                "title": "What is required before processing a candidate's interview recording?",
                "type": "single_choice",
                "options": [
                    {"title": "Signed consent for recording", "is_correct": True},
                    {"title": "Just a verbal okay", "is_correct": False},
                    {"title": "Notification after the fact", "is_correct": False},
                    {"title": "Nothing if internal only", "is_correct": False},
                ],
            },
            {
                "title": "Which artefacts must be encrypted at rest?",
                "type": "multiple_choice",
                "options": [
                    {"title": "Database backups", "is_correct": True},
                    {"title": "Resume uploads", "is_correct": True},
                    {"title": "Public marketing site assets", "is_correct": False},
                    {"title": "Customer audio recordings", "is_correct": True},
                ],
            },
            {
                "title": "Where is GDPR erasure handled in the recruitment module?",
                "type": "single_choice",
                "options": [
                    {"title": "GDPRErasureLog + RecruitmentRetentionConfig TTLs", "is_correct": True},
                    {"title": "Manually by support per ticket", "is_correct": False},
                    {"title": "Never — retention is forever", "is_correct": False},
                    {"title": "By dropping the tenant row", "is_correct": False},
                ],
            },
            {
                "title": "How are external reviewer tokens scoped?",
                "type": "single_choice",
                "options": [
                    {"title": "Single assessment, single reviewer, fixed expiry", "is_correct": True},
                    {"title": "All assessments for the tenant", "is_correct": False},
                    {"title": "Persistent until revoked manually", "is_correct": False},
                    {"title": "Reusable across tenants", "is_correct": False},
                ],
            },
            {
                "title": "Pick the actions that always require MFA.",
                "type": "multiple_choice",
                "options": [
                    {"title": "Production admin login", "is_correct": True},
                    {"title": "Pulling encrypted backups", "is_correct": True},
                    {"title": "Reading public marketing pages", "is_correct": False},
                    {"title": "Issuing a one-off platform-admin token", "is_correct": True},
                ],
            },
        ],
        "employee_indices": [
            (0, "assigned", None),
            (6, "assigned", None),
            (11, "assigned", None),
            (18, "assigned", None),
            (28, "assigned", None),
        ],
    },
    {
        "key": "discovery-basics",
        "title": "Product Discovery Basics",
        "description": "Draft — being assembled by the People team for the next PM cohort.",
        "status": "draft",
        "pass_mark_percent": 70,
        "questions": [
            {
                "title": "What is the goal of a discovery interview?",
                "type": "single_choice",
                "options": [
                    {"title": "Validate problem and willingness to pay", "is_correct": True},
                    {"title": "Demo the product", "is_correct": False},
                    {"title": "Close the deal", "is_correct": False},
                    {"title": "Collect feature requests", "is_correct": False},
                ],
            },
            {
                "title": "Pick the signals that suggest a strong problem fit.",
                "type": "multiple_choice",
                "options": [
                    {"title": "User describes the workaround they currently use", "is_correct": True},
                    {"title": "User asks how much it costs", "is_correct": True},
                    {"title": "User politely says they would use it", "is_correct": False},
                    {"title": "User immediately changes the subject", "is_correct": False},
                ],
            },
            {
                "title": "How many discovery interviews per problem hypothesis is a reasonable baseline?",
                "type": "single_choice",
                "options": [
                    {"title": "5–8", "is_correct": True},
                    {"title": "1", "is_correct": False},
                    {"title": "50+", "is_correct": False},
                    {"title": "It depends — but always under 3", "is_correct": False},
                ],
            },
            {
                "title": "Which framework helps size enterprise opportunity?",
                "type": "single_choice",
                "options": [
                    {"title": "MEDDIC", "is_correct": True},
                    {"title": "SOLID", "is_correct": False},
                    {"title": "DRY", "is_correct": False},
                    {"title": "KISS", "is_correct": False},
                ],
            },
        ],
        "employee_indices": [],
    },
]
