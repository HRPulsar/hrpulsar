"""Few-shot Q/A pairs for the three generation scopes.

Each entry is a (question, answer) tuple. The question is rendered as a
compact JSON block describing the inputs (specialization, divisions,
projects, source tree, etc.); the answer is the JSON the model is expected
to return. Keep these short — Pydantic-validated `GeneratedTreeSchema`
and `GeneratedIndicatorsSchema` already constrain the shape, so examples
exist to teach the *style* (granularity, naming, type tagging), not the
syntax.

Adapted from the legacy generator semantics, but the legacy flat-string
format and Russian text are replaced with English JSON to match the
HRPulsar contract (Phase CR10b: `content_language` is currently `en` only).
"""

from __future__ import annotations

# (question_dict, answer_dict)
TREE_EXAMPLES: list[tuple[dict, dict]] = [
    (
        {
            "specialization": "Backend Engineer",
            "divisions": ["Engineering"],
            "projects": ["Payment platform"],
            "company": "B2B SaaS, ~150 people, Python + Postgres stack",
            "required_elements": ["API design", "SQL performance"],
            "source": {"groups": []},
        },
        {
            "groups": [
                {
                    "title": "Software engineering fundamentals",
                    "description": "Core skills for building reliable services.",
                    "children": [],
                    "competences": [
                        {
                            "title": "API design",
                            "description": "Designing REST and async APIs.",
                            "type": "hard_skill",
                            "indicators": [
                                {
                                    "title": "Knows REST resource modelling and HTTP semantics",
                                    "skill_level": "basic",
                                },
                                {
                                    "title": "Designs versioned, paginated, idempotent endpoints",
                                    "skill_level": "intermediate",
                                },
                            ],
                        },
                        {
                            "title": "SQL performance",
                            "description": "Reading and optimising queries.",
                            "type": "hard_skill",
                            "indicators": [
                                {
                                    "title": "Reads EXPLAIN ANALYZE and identifies missing indexes",
                                    "skill_level": "basic",
                                },
                                {
                                    "title": "Tunes joins and rewrites queries to remove sequential scans",
                                    "skill_level": "intermediate",
                                },
                            ],
                        },
                    ],
                },
                {
                    "title": "Collaboration",
                    "description": "Working effectively across teams.",
                    "children": [],
                    "competences": [
                        {
                            "title": "Code review",
                            "description": "Constructive review of peers' changes.",
                            "type": "soft_skill",
                            "indicators": [
                                {
                                    "title": "Leaves clear, actionable feedback referencing the diff",
                                    "skill_level": "basic",
                                },
                            ],
                        },
                    ],
                },
            ]
        },
    ),
]


GROUP_EXAMPLES: list[tuple[dict, dict]] = [
    (
        {
            "group": "Communication skills",
            "specialization": "Customer Support Lead",
            "required_elements": ["conflict resolution", "active listening"],
            "source": {
                "groups": [{"title": "Communication skills", "competences": []}]
            },
        },
        {
            "groups": [
                {
                    "title": "Communication skills",
                    "description": None,
                    "children": [],
                    "competences": [
                        {
                            "title": "Active listening",
                            "description": "Hearing intent behind a customer's words.",
                            "type": "soft_skill",
                            "indicators": [
                                {
                                    "title": "Paraphrases the user's request before answering",
                                    "skill_level": "basic",
                                },
                            ],
                        },
                        {
                            "title": "Conflict resolution",
                            "description": "De-escalating tense conversations.",
                            "type": "soft_skill",
                            "indicators": [
                                {
                                    "title": "Acknowledges the user's frustration and reframes the problem",
                                    "skill_level": "basic",
                                },
                            ],
                        },
                    ],
                }
            ]
        },
    ),
]


INDICATORS_EXAMPLES: list[tuple[dict, dict]] = [
    (
        {
            "competence": "Code review",
            "competence_type": "soft_skill",
            "skill_levels": ["basic", "intermediate", "advanced"],
            "parents": ["Collaboration"],
            "existing_indicators": [
                {"title": "Leaves clear feedback", "skill_level": "basic"}
            ],
        },
        {
            "indicators": [
                {
                    "title": "Spots logic errors and unsafe edge cases in a typical pull request",
                    "skill_level": "intermediate",
                },
                {
                    "title": "Coaches authors on architectural alternatives, not just the diff",
                    "skill_level": "advanced",
                },
            ]
        },
    ),
]
