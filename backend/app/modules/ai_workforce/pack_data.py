"""Built-in agent packs — the nine of decision O5 (2026-08-31).

A pack is a class of agents covering a fixed set of capability primitives.
The construction is dictated by the catalog (REFACTOR_PLAN §2.4): every
pack reads its input (P1) and adds the one capability the catalog says an
agent does well; ``coordinator`` and ``scripted_dialogue`` carry the v1.1
"yes" codes P11 / P12. No pack declares P6 / P7 / P8 (verdict "no") or a
boundary code — ``tests/unit/test_ai_workforce_packs.py`` pins that.

English only: this file reaches the public tree. Labels for the UI live in
``frontend/messages/*.json`` under ``reference.agentPack.<i18n_key>``.

``seed_statements()`` is shared by migration ``v2agnt01`` and
``service.seed_packs`` so a test of the seed exercises what production runs.
It resolves ``primitives.id`` by code at run time — the table, not
``catalog_data``, is the source of truth once the catalog is seeded.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import Executable

PACKS: list[dict[str, Any]] = [
    {
        "code": "extraction",
        "title_en": "Extraction",
        "description_en": (
            "Turns documents, messages and forms into structured fields; "
            "a deterministic pipeline checked against a reference set"
        ),
        "i18n_key": "extraction",
        "sort_index": 0,
        "primitives": ["P1"],
    },
    {
        "code": "compliance_check",
        "title_en": "Compliance check",
        "description_en": (
            "Checks a document or a record against a fixed reference and "
            "reports every discrepancy; exhaustive where a person samples"
        ),
        "i18n_key": "compliance_check",
        "sort_index": 1,
        "primitives": ["P1", "P2"],
    },
    {
        "code": "triage_router",
        "title_en": "Triage and routing",
        "description_en": (
            "Classifies incoming items by known rules and routes each one "
            "to a queue or an owner"
        ),
        "i18n_key": "triage_router",
        "sort_index": 2,
        "primitives": ["P1", "P2", "P3"],
    },
    {
        "code": "drafting",
        "title_en": "Drafting",
        "description_en": (
            "Produces a first draft of text in a given register; a person "
            "accepts it before it leaves the company"
        ),
        "i18n_key": "drafting",
        "sort_index": 3,
        "primitives": ["P1", "P5"],
    },
    {
        "code": "investigation",
        "title_en": "Investigation",
        "description_en": (
            "Builds a draft hypothesis about a cause from logs, records and "
            "statements; a person confirms it"
        ),
        "i18n_key": "investigation",
        "sort_index": 4,
        "primitives": ["P1", "P4"],
    },
    {
        "code": "artifact_builder",
        "title_en": "Artifact builder",
        "description_en": (
            "Produces a working artifact from a specification \u2014 code, a "
            "schema, a course; checked by whether it works"
        ),
        "i18n_key": "artifact_builder",
        "sort_index": 5,
        "primitives": ["P1", "P9"],
    },
    {
        "code": "experiment_design",
        "title_en": "Experiment design",
        "description_en": (
            "Drafts a measurement or an experiment \u2014 metric, sample, "
            "control; a person approves the design"
        ),
        "i18n_key": "experiment_design",
        "sort_index": 6,
        "primitives": ["P1", "P10"],
    },
    {
        "code": "coordinator",
        "title_en": "Coordinator",
        "description_en": (
            "Runs coordination by calendar, triggers and lists: reminders, "
            "follow-ups, status collection"
        ),
        "i18n_key": "coordinator",
        "sort_index": 7,
        "primitives": ["P1", "P11"],
    },
    {
        "code": "scripted_dialogue",
        "title_en": "Scripted dialogue",
        "description_en": (
            "Holds a dialogue that follows a script, a questionnaire or a "
            "procedure, handing over to a person when it leaves the script"
        ),
        "i18n_key": "scripted_dialogue",
        "sort_index": 8,
        "primitives": ["P1", "P12"],
    },
]

# Lightweight table handles: the migration runs these before the ORM
# models exist in its process, so nothing here imports ``models``.
_packs = sa.table(
    "ai_agent_packs",
    sa.column("id"),
    sa.column("code"),
    sa.column("title_en"),
    sa.column("description_en"),
    sa.column("i18n_key"),
    sa.column("sort_index"),
    sa.column("is_active"),
    sa.column("tenant_id"),
)
_pack_primitives = sa.table(
    "ai_agent_pack_primitives", sa.column("pack_id"), sa.column("primitive_id")
)
_primitives = sa.table("primitives", sa.column("id"), sa.column("code"))


def seed_statements() -> list[Executable]:
    """Idempotent seed of the built-in packs and their primitives.

    A built-in is identified by ``(code, tenant_id IS NULL)``; the plain
    unique constraint cannot express that (NULLs are distinct), so both
    inserts are ``ON CONFLICT DO NOTHING`` — the pack against the partial
    unique index ``uq_agent_packs_builtin_code``, the link against
    ``(pack_id, primitive_id)``. A re-run never rewrites a row a later
    revision may have retired or renamed.
    """
    statements: list[Executable] = []
    for pack in PACKS:
        statements.append(
            insert(_packs)
            .from_select(
                ["code", "title_en", "description_en", "i18n_key", "sort_index"],
                sa.select(
                    sa.literal(pack["code"]),
                    sa.literal(pack["title_en"]),
                    sa.literal(pack["description_en"]),
                    sa.literal(pack["i18n_key"]),
                    sa.literal(pack["sort_index"]),
                ),
            )
            .on_conflict_do_nothing(
                index_elements=[_packs.c.code],
                index_where=sa.text("tenant_id IS NULL"),
            )
        )
        statements.append(
            insert(_pack_primitives)
            .from_select(
                ["pack_id", "primitive_id"],
                # One pack row × its primitive rows: a cross join on purpose.
                sa.select(_packs.c.id, _primitives.c.id)
                .join_from(_packs, _primitives, sa.true())
                .where(
                    _packs.c.code == pack["code"],
                    _packs.c.tenant_id.is_(None),
                    _primitives.c.code.in_(pack["primitives"]),
                ),
            )
            .on_conflict_do_nothing()
        )
    return statements
