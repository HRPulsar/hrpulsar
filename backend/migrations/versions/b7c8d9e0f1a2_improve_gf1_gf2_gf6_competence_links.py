"""Improve: GF1/GF2 competence links, GF6 deputy manager

Revision ID: b7c8d9e0f1a2
Revises: a7b8c9d0e1f2
Create Date: 2026-04-18 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GF1: Work experience ↔ competence M2M
    op.create_table(
        "work_experience_competences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("work_experience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["work_experience_id"], ["work_experiences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_experience_id", "competence_id", name="uq_we_competence"
        ),
    )
    op.create_index(
        "ix_we_comp_we_id", "work_experience_competences", ["work_experience_id"]
    )

    # GF2: Course ↔ competence M2M
    op.create_table(
        "course_competences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "competence_id", name="uq_course_competence"),
    )
    op.create_index("ix_course_comp_course_id", "course_competences", ["course_id"])

    # GF6: Deputy manager on divisions
    op.add_column(
        "divisions",
        sa.Column(
            "deputy_manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "employees.id",
                ondelete="SET NULL",
                name="fk_divisions_deputy_manager_id",
                use_alter=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_divisions_deputy_manager_id", "divisions", ["deputy_manager_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_divisions_deputy_manager_id", table_name="divisions")
    op.drop_column("divisions", "deputy_manager_id")
    op.drop_index("ix_course_comp_course_id", table_name="course_competences")
    op.drop_table("course_competences")
    op.drop_index("ix_we_comp_we_id", table_name="work_experience_competences")
    op.drop_table("work_experience_competences")
