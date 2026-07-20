"""Add missing updated_at to competence link tables

Revision ID: c4d5e6f7a8b9
Revises: e25d0812c8be
Create Date: 2026-04-21 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "e25d0812c8be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    for table in ("work_experience_competences", "course_competences"):
        if not _column_exists(table, "updated_at"):
            op.add_column(
                table,
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
            )


def downgrade() -> None:
    op.drop_column("course_competences", "updated_at")
    op.drop_column("work_experience_competences", "updated_at")
