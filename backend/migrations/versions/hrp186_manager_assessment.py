"""HRP-186: manager assessment + invited evaluator.

Adds structured scales (levels), assessment rounds, per-evaluator
assessment records with competence + indicator scores, hashed invite
tokens with round binding, vacancy scale snapshot, and the denormalized
manager_score on candidate_vacancies.

Recruitment tables get a ``recruitment_`` prefix because plain
``assessments`` is already taken by the 360-review module.

Revision ID: hrp186managerassess
Revises: hrp84inappnotif
Create Date: 2026-06-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp186managerassess"
down_revision: str | None = "hrp84inappnotif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # recruitment_assessment_scales -------------------------------------
    op.create_table(
        "recruitment_assessment_scales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "divergence_threshold",
            sa.Integer,
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_recr_assess_scales_one_default",
        "recruitment_assessment_scales",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND archived_at IS NULL"),
    )

    # recruitment_assessment_scale_levels ------------------------------
    op.create_table(
        "recruitment_assessment_scale_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scale_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_scales.id", ondelete="CASCADE"
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("value", sa.Integer, nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("weight", sa.Integer, nullable=False),
        sa.Column("color", sa.String(length=30), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "scale_id", "value", name="uq_recr_scale_level_value"
        ),
    )

    # Vacancy scale binding + snapshot ---------------------------------
    op.add_column(
        "vacancies",
        sa.Column(
            "assessment_scale_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_scales.id", ondelete="SET NULL"
            ),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "vacancies",
        sa.Column(
            "assessment_scale_snapshot",
            postgresql.JSONB,
            nullable=True,
        ),
    )

    # recruitment_assessment_rounds ------------------------------------
    op.create_table(
        "recruitment_assessment_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "candidate_vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("round_number", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_recr_rounds_cv_type_num",
        "recruitment_assessment_rounds",
        ["candidate_vacancy_id", "type", "round_number"],
    )

    # recruitment_assessment_round_evaluators --------------------------
    op.create_table(
        "recruitment_assessment_round_evaluators",
        sa.Column(
            "round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_rounds.id", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # recruitment_assessments (per evaluator, per round) ---------------
    op.create_table(
        "recruitment_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_rounds.id", ondelete="CASCADE"
            ),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "evaluator_type",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "evaluator_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "evaluator_invite_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_invites.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "evaluator_display_name",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_notes", sa.Text, nullable=True),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_recr_assessments_round_user",
        "recruitment_assessments",
        ["round_id", "evaluator_user_id"],
        unique=True,
        postgresql_where=sa.text("evaluator_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_recr_assessments_round_invite",
        "recruitment_assessments",
        ["round_id", "evaluator_invite_id"],
        unique=True,
        postgresql_where=sa.text("evaluator_invite_id IS NOT NULL"),
    )

    # recruitment_assessment_competence_scores -------------------------
    op.create_table(
        "recruitment_assessment_competence_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recruitment_assessments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "competence_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("score_value", sa.Integer, nullable=True),
        sa.Column(
            "score_source",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "competence_id",
            name="uq_recr_assessment_competence",
        ),
    )

    # recruitment_assessment_indicator_scores --------------------------
    op.create_table(
        "recruitment_assessment_indicator_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recruitment_assessments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "indicator_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "competence_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("score_value", sa.Integer, nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "indicator_id",
            name="uq_recr_assessment_indicator",
        ),
    )

    # AssessmentInvite extensions --------------------------------------
    op.add_column(
        "assessment_invites",
        sa.Column(
            "token_hash",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_assessment_invites_token_hash",
        "assessment_invites",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("token_hash IS NOT NULL"),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_rounds.id", ondelete="SET NULL"
            ),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "allow_reediting",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "personal_message",
            sa.Text,
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "declined_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "revoked_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "purged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "delivery_status",
            sa.String(length=30),
            nullable=False,
            server_default="queued",
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "delivery_error",
            sa.Text,
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "delivery_retry_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "assessment_invites",
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # candidate_vacancies aggregated manager score --------------------
    op.add_column(
        "candidate_vacancies",
        sa.Column("manager_score", sa.Float, nullable=True),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "manager_score_weight",
            sa.Float,
            nullable=True,
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "manager_score_source_round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "recruitment_assessment_rounds.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "manager_score_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # public-endpoint deny list (rate limit / brute-force protection) --
    op.create_table(
        "public_assessment_ip_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ip", sa.String(length=64), nullable=False, index=True),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column(
            "blocked_until",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "failures",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_public_assessment_ip_blocks_until",
        "public_assessment_ip_blocks",
        ["ip", "blocked_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_public_assessment_ip_blocks_until",
        table_name="public_assessment_ip_blocks",
    )
    op.drop_table("public_assessment_ip_blocks")

    op.drop_column("candidate_vacancies", "manager_score_updated_at")
    op.drop_column("candidate_vacancies", "manager_score_source_round_id")
    op.drop_column("candidate_vacancies", "manager_score_weight")
    op.drop_column("candidate_vacancies", "manager_score")

    op.drop_column("assessment_invites", "invited_by")
    op.drop_column("assessment_invites", "delivery_retry_count")
    op.drop_column("assessment_invites", "delivery_error")
    op.drop_column("assessment_invites", "delivery_status")
    op.drop_column("assessment_invites", "purged_at")
    op.drop_column("assessment_invites", "revoked_by")
    op.drop_column("assessment_invites", "revoked_at")
    op.drop_column("assessment_invites", "declined_at")
    op.drop_column("assessment_invites", "submitted_at")
    op.drop_column("assessment_invites", "opened_at")
    op.drop_column("assessment_invites", "personal_message")
    op.drop_column("assessment_invites", "allow_reediting")
    op.drop_column("assessment_invites", "round_id")
    op.drop_index(
        "ix_assessment_invites_token_hash",
        table_name="assessment_invites",
    )
    op.drop_column("assessment_invites", "token_hash")

    op.drop_table("recruitment_assessment_indicator_scores")
    op.drop_table("recruitment_assessment_competence_scores")
    op.drop_index(
        "ix_recr_assessments_round_invite",
        table_name="recruitment_assessments",
    )
    op.drop_index(
        "ix_recr_assessments_round_user",
        table_name="recruitment_assessments",
    )
    op.drop_table("recruitment_assessments")
    op.drop_table("recruitment_assessment_round_evaluators")
    op.drop_index(
        "ix_recr_rounds_cv_type_num",
        table_name="recruitment_assessment_rounds",
    )
    op.drop_table("recruitment_assessment_rounds")

    op.drop_column("vacancies", "assessment_scale_snapshot")
    op.drop_column("vacancies", "assessment_scale_id")

    op.drop_table("recruitment_assessment_scale_levels")
    op.drop_index(
        "ix_recr_assess_scales_one_default",
        table_name="recruitment_assessment_scales",
    )
    op.drop_table("recruitment_assessment_scales")
