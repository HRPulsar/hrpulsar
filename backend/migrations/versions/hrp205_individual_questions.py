"""HRP-205: per-candidate AI question sets (FR-12/13)

Revision ID: hrp205indqs01
Revises: hrp84inappnotif
Create Date: 2026-06-02 12:00:00.000000

Introduces three tables for the new individual-questions subsystem:

* ``question_sets`` — versioned bundles of questions tied to a single
  ``candidate_vacancies`` row, optionally scoped to a specific interview
  round so dynamic-next sets can evolve per round.
* ``questions`` — the questions themselves, soft-deletable, with rich
  metadata: source (ai / manual / from_indicator / from_blind_spot),
  resume anchor, expected indicators, follow-ups, rationale, covered
  state.
* ``question_set_jobs`` — async generation jobs (Celery task tracking).

Old ``candidate_questions`` table is left untouched (kept for backward
compatibility with R1 endpoints).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp205indqs01"
down_revision: str | None = "hrp84inappnotif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_sets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
        sa.Column(
            "round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_type",
            sa.String(length=32),
            nullable=False,
            server_default="pre_interview",
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column(
            "generation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="initial",
        ),
        sa.Column(
            "source_round_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("coverage_note", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_sets_tenant_id",
        "question_sets",
        ["tenant_id"],
    )
    op.create_index(
        "ix_question_sets_cv",
        "question_sets",
        ["candidate_vacancy_id"],
    )
    op.create_index(
        "ix_question_sets_round",
        "question_sets",
        ["round_id"],
    )

    op.create_table(
        "questions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
            "question_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("question_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "goal",
            sa.String(length=32),
            nullable=False,
            server_default="clarification",
        ),
        sa.Column(
            "priority",
            sa.String(length=32),
            nullable=False,
            server_default="should",
        ),
        sa.Column(
            "competence_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "resume_anchor_jsonb", postgresql.JSONB(), nullable=True
        ),
        sa.Column(
            "expected_answer_indicators",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "follow_ups",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="ai_generated",
        ),
        sa.Column(
            "source_blind_spot_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "covered_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "covered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "covered_method", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_tenant_id", "questions", ["tenant_id"])
    op.create_index(
        "ix_questions_set", "questions", ["question_set_id"]
    )
    op.create_index(
        "ix_questions_competence_id", "questions", ["competence_id"]
    )

    op.create_table(
        "question_set_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
            "question_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("question_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_set_jobs_tenant_id",
        "question_set_jobs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_question_set_jobs_set",
        "question_set_jobs",
        ["question_set_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_question_set_jobs_set", table_name="question_set_jobs")
    op.drop_index(
        "ix_question_set_jobs_tenant_id", table_name="question_set_jobs"
    )
    op.drop_table("question_set_jobs")
    op.drop_index("ix_questions_competence_id", table_name="questions")
    op.drop_index("ix_questions_set", table_name="questions")
    op.drop_index("ix_questions_tenant_id", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_question_sets_round", table_name="question_sets")
    op.drop_index("ix_question_sets_cv", table_name="question_sets")
    op.drop_index("ix_question_sets_tenant_id", table_name="question_sets")
    op.drop_table("question_sets")
