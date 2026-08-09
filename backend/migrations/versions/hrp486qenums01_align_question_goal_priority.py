"""Align interview-question goal and priority vocabularies (HRP-486).

The ``questions`` table shipped with two ad-hoc vocabularies that did not
match the ones the product spec asks for:

* goal     ``clarification | depth | risk | motivation | fit``
* priority ``must | should | nice_to_ask``

Both are renamed in place to the canonical codes shared by AI
generation, manual add and the UI. The rename is a pure relabelling —
each old code maps onto exactly one new code, so no rows are lost and
``downgrade`` is lossless too.

Column defaults move with the data; the columns are plain ``String(32)``
(no Postgres enum type), so only ``ALTER COLUMN ... SET DEFAULT`` is
needed.

Revision ID: hrp486qenums01
Revises: hrp518deproofread01
Create Date: 2026-08-05 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "hrp486qenums01"
down_revision: str | None = "hrp518deproofread01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# old code -> new code
GOAL_MAP: dict[str, str] = {
    "clarification": "clarify_experience",
    "depth": "verify_skill",
    "risk": "probe_risk",
    "motivation": "explore_motivation",
    "fit": "assess_fit",
}

PRIORITY_MAP: dict[str, str] = {
    "must": "must_ask",
    "should": "should_ask",
    # nice_to_ask already matches the target vocabulary.
}


def _remap(column: str, mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(
            f"UPDATE questions SET {column} = '{new}' WHERE {column} = '{old}'"  # noqa: S608
        )


def upgrade() -> None:
    _remap("goal", GOAL_MAP)
    _remap("priority", PRIORITY_MAP)
    op.execute("ALTER TABLE questions ALTER COLUMN goal SET DEFAULT 'verify_skill'")
    op.execute("ALTER TABLE questions ALTER COLUMN priority SET DEFAULT 'should_ask'")


def downgrade() -> None:
    op.execute("ALTER TABLE questions ALTER COLUMN goal SET DEFAULT 'clarification'")
    op.execute("ALTER TABLE questions ALTER COLUMN priority SET DEFAULT 'should'")
    _remap("goal", {new: old for old, new in GOAL_MAP.items()})
    _remap("priority", {new: old for old, new in PRIORITY_MAP.items()})
