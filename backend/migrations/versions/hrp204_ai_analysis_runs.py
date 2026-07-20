"""HRP-204: per-(candidate, vacancy) AI analysis runs with two modes.

Adds the ``ai_analysis_runs`` table, plus tracking columns on
``candidate_vacancies`` that mirror the **active** run so the candidate
list can render mode + age without joining.

Each row represents one completed (or in-flight) AI run for a single
``candidate_vacancies`` pairing.

* ``mode`` is one of ``resume_only`` / ``full``.
* ``interview_id`` is non-null only when mode = ``full`` (full runs are
  still anchored to the interview they were derived from).
* ``analysis_data`` holds the unified payload — competence assessments,
  blind spots, red flags, process findings (full only), resume excerpts
  (resume-only only), verdict + summary, recommendation for next step.
* ``archived_at`` + ``replaced_by_id`` form the linkage when a top-up
  (resume-only → full) supersedes an older run.
* ``vacancy_profile_version`` is the snapshot taken at run time so the
  top-up eligibility check can refuse when the profile has since been
  edited.

Revision ID: hrp204analyses
Revises: hrp252cache
Create Date: 2026-06-14 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp204analyses"
down_revision: str | None = "hrp252cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_analysis_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("data_completeness", sa.String(length=20), nullable=True),
        sa.Column(
            "interview_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "candidate_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "vacancy_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancy_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("vacancy_profile_version", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=30), nullable=True),
        sa.Column("verdict_summary", sa.Text(), nullable=True),
        sa.Column("key_strength", sa.Text(), nullable=True),
        sa.Column("key_risk", sa.Text(), nullable=True),
        sa.Column("risk_mitigation", sa.Text(), nullable=True),
        sa.Column(
            "recommendation_for_next_step",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column(
            "analysis_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "credits_charged",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "mode IN ('resume_only', 'full')",
            name="ck_ai_analysis_runs_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_ai_analysis_runs_status",
        ),
    )
    op.create_index(
        "ix_ai_analysis_runs_tenant_id",
        "ai_analysis_runs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_ai_analysis_runs_candidate_vacancy_id",
        "ai_analysis_runs",
        ["candidate_vacancy_id"],
    )
    op.create_index(
        "ix_ai_analysis_runs_interview_id",
        "ai_analysis_runs",
        ["interview_id"],
    )
    # The "active" run per pair = archived_at IS NULL. Enforce uniqueness
    # so a successful run always shadows older active rows (the service
    # archives them in the same transaction).
    op.create_index(
        "uq_ai_analysis_runs_active_per_cv",
        "ai_analysis_runs",
        ["candidate_vacancy_id"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL AND status = 'completed'"),
    )

    # ── Mirror the active run on candidate_vacancies for fast list queries ──
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "ai_analysis_mode",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "ai_analysis_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "ai_data_completeness",
            sa.String(length=20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_vacancies", "ai_data_completeness")
    op.drop_column("candidate_vacancies", "ai_analysis_completed_at")
    op.drop_column("candidate_vacancies", "ai_analysis_mode")

    op.drop_index(
        "uq_ai_analysis_runs_active_per_cv", table_name="ai_analysis_runs"
    )
    op.drop_index(
        "ix_ai_analysis_runs_interview_id", table_name="ai_analysis_runs"
    )
    op.drop_index(
        "ix_ai_analysis_runs_candidate_vacancy_id",
        table_name="ai_analysis_runs",
    )
    op.drop_index(
        "ix_ai_analysis_runs_tenant_id", table_name="ai_analysis_runs"
    )
    op.drop_table("ai_analysis_runs")
