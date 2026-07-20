"""HRP-180: link vacancies to Position + spec/grade multi-select.

Adds:
- ``vacancies.position_id`` FK to ``positions(id)`` (SET NULL on delete).
- ``vacancy_specializations`` junction table (vacancy_id, specialization_id).
- ``vacancy_grades`` junction table (vacancy_id, grade_id).

Legacy ``vacancies.specialization_id`` / ``grade_id`` (single-value FKs to
dictionary_items) are intentionally kept for back-compat — they will be
deprecated in a follow-up after data migration is done.

Revision ID: hrp180vacancyposlink
Revises: hrp84inappnotif
Create Date: 2026-06-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp180vacancyposlink"
down_revision: str | None = "hrp84inappnotif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_vacancies_position_id", "vacancies", ["position_id"]
    )

    op.create_table(
        "vacancy_specializations",
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "specialization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vacancy_specializations_vacancy_id",
        "vacancy_specializations",
        ["vacancy_id"],
    )

    op.create_table(
        "vacancy_grades",
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vacancy_grades_vacancy_id",
        "vacancy_grades",
        ["vacancy_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vacancy_grades_vacancy_id", table_name="vacancy_grades"
    )
    op.drop_table("vacancy_grades")
    op.drop_index(
        "ix_vacancy_specializations_vacancy_id",
        table_name="vacancy_specializations",
    )
    op.drop_table("vacancy_specializations")
    op.drop_index("ix_vacancies_position_id", table_name="vacancies")
    op.drop_column("vacancies", "position_id")
