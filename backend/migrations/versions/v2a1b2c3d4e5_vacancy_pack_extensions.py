"""HRP-131/135/136/181: vacancy library refs + manual params + attachments + competences + candidates

Adds:
- ``vacancies.library_refs`` (JSONB) — store position_ids /
  specialization_grade_pairs / division_ids selections (HRP-131).
- ``vacancies.requirements`` / ``responsibilities`` / ``conditions``
  TEXT columns and ``vacancy_attachments`` table (HRP-135).
- ``vacancy_competences`` table linking vacancy + competence id with
  required skill_levels JSONB (HRP-136).
- ``vacancy_candidates`` table for the lightweight candidate flow
  (HRP-181) — distinct from the existing ``candidate_vacancies``
  many-to-many because HRP-181 candidates can be external (no Person
  row) and carry their own recruiter/AI scores + resume file.

Revision ID: v2a1b2c3d4e5
Revises: v1a1b2c3d4e5
Create Date: 2026-05-29 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2a1b2c3d4e5"
down_revision: str | None = "v1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── HRP-131: library refs (JSONB on vacancies) ──────────────────────
    op.add_column(
        "vacancies",
        sa.Column(
            "library_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ── HRP-135: manual params + attachments ────────────────────────────
    op.add_column(
        "vacancies",
        sa.Column("requirements", sa.Text(), nullable=True),
    )
    op.add_column(
        "vacancies",
        sa.Column("responsibilities", sa.Text(), nullable=True),
    )
    op.add_column(
        "vacancies",
        sa.Column("conditions", sa.Text(), nullable=True),
    )

    op.create_table(
        "vacancy_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vacancy_attachments_vacancy_id",
        "vacancy_attachments",
        ["vacancy_id"],
    )

    # ── HRP-136: VacancyCompetence ──────────────────────────────────────
    op.create_table(
        "vacancy_competences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "competence_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skill_level_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "vacancy_id",
            "competence_id",
            name="uq_vacancy_competence",
        ),
    )

    # ── HRP-181: VacancyCandidate (light, external-friendly) ───────────
    op.create_table(
        "vacancy_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_name", sa.String(255), nullable=True),
        sa.Column("external_email", sa.String(255), nullable=True),
        sa.Column("external_phone", sa.String(50), nullable=True),
        sa.Column("current_position", sa.String(255), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column(
            "resume_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recruiter_score", sa.Float(), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column(
            "stage",
            sa.String(50),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vacancy_candidates_vacancy_id",
        "vacancy_candidates",
        ["vacancy_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_vacancy_candidates_vacancy_id", table_name="vacancy_candidates")
    op.drop_table("vacancy_candidates")
    op.drop_table("vacancy_competences")
    op.drop_index(
        "ix_vacancy_attachments_vacancy_id", table_name="vacancy_attachments"
    )
    op.drop_table("vacancy_attachments")
    op.drop_column("vacancies", "conditions")
    op.drop_column("vacancies", "responsibilities")
    op.drop_column("vacancies", "requirements")
    op.drop_column("vacancies", "library_refs")
