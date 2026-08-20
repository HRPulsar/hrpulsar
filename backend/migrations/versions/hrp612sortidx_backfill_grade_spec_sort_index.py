"""Backfill grade_specializations.sort_index from the grade's own order

The personal dashboard's "next grade" card (HRP-612) walks the ladder by
``GradeSpecialization.sort_index``, but rows created before the seed (and
any client that never sent an explicit order) sit on the server default
``0`` — so ``next(g for g in ladder if g.sort_index > current.sort_index)``
finds nothing and the growth block never renders. Copy the linked grade
dictionary item's sort_index onto every cell still carrying the default;
rows with an explicit non-zero order are left untouched.

Revision ID: hrp612sortidx
Revises: demokeepdata01
Create Date: 2026-08-20 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp612sortidx"
down_revision: str | None = "demokeepdata01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE grade_specializations gs
        SET sort_index = di.sort_index
        FROM dictionary_items di
        WHERE di.id = gs.grade_id
          AND gs.sort_index = 0
          AND di.sort_index <> 0
        """
    )


def downgrade() -> None:
    # Backfill only — nothing to restore.
    pass
