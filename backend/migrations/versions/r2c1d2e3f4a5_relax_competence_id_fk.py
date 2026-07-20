"""R2c: relax competence_id FK on recruitment tables

AI-generated vacancy profiles describe competences as JSON items with
deterministic id slugs (uuid5 namespace). Those ids are not registered in
the `competences` table — that table is the company's curated competence
library, owned by the Competence module. R2 needs scoring and questions to
work against AI-generated profiles, so we drop the FK constraint on the
competence_id column for the three recruitment tables and treat the column
as an opaque UUID reference.

Future R-phases may reintroduce the FK once we backfill ad-hoc competences
into the curated library or introduce a separate `recruitment_competences`
table; until then no referential integrity is enforced server-side.

Revision ID: r2c1d2e3f4a5
Revises: r2b1c2d3e4f5
Create Date: 2026-05-07 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "r2c1d2e3f4a5"
down_revision: str | None = "r2b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = (
    "candidate_questions",
    "human_assessments",
    "ai_assessments",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "
            f"{table}_competence_id_fkey"
        )


def downgrade() -> None:
    op.create_foreign_key(
        "candidate_questions_competence_id_fkey",
        "candidate_questions",
        "competences",
        ["competence_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "human_assessments_competence_id_fkey",
        "human_assessments",
        "competences",
        ["competence_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "ai_assessments_competence_id_fkey",
        "ai_assessments",
        "competences",
        ["competence_id"],
        ["id"],
        ondelete="CASCADE",
    )
