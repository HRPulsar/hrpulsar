"""R1: Recruitment module — persons + 17 tables + role seeds

Revision ID: r1a2b3c4d5e6
Revises: emp1a1b2c3d4e5
Create Date: 2026-04-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "r1a2b3c4d5e6"
down_revision: str | None = "emp1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. persons (global, no tenant_id) ────────────────────────────
    op.create_table(
        "persons",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_persons_email"), "persons", ["email"], unique=False)

    # ── 2. ALTER users — add person_id FK ────────────────────────────
    op.add_column(
        "users",
        sa.Column("person_id", sa.UUID(), nullable=True),
    )
    op.create_index(op.f("ix_users_person_id"), "users", ["person_id"], unique=False)
    op.create_foreign_key(
        "fk_users_person_id_persons",
        "users",
        "persons",
        ["person_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── 3. Backfill persons from existing users ──────────────────────
    op.execute("""
        INSERT INTO persons (id, email, phone, first_name, last_name, created_at, updated_at)
        SELECT gen_random_uuid(), email, NULL, first_name, last_name, now(), now()
        FROM users
        WHERE person_id IS NULL
    """)
    op.execute("""
        UPDATE users u SET person_id = p.id
        FROM persons p
        WHERE u.email = p.email AND u.person_id IS NULL
    """)

    # ── 4. vacancies ─────────────────────────────────────────────────
    op.create_table(
        "vacancies",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("specialization_id", sa.UUID(), nullable=True),
        sa.Column("grade_id", sa.UUID(), nullable=True),
        sa.Column("division_id", sa.UUID(), nullable=True),
        sa.Column(
            "status", sa.String(length=50), server_default="draft", nullable=False
        ),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("tasks_main", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "tasks_additional", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("tasks_kpi", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("employment_type", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("salary_min", sa.Numeric(), nullable=True),
        sa.Column("salary_max", sa.Numeric(), nullable=True),
        sa.Column("salary_currency", sa.String(length=10), nullable=True),
        sa.Column(
            "language", sa.String(length=10), server_default="en", nullable=False
        ),
        sa.Column("close_resolution", sa.String(length=50), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["specialization_id"], ["dictionary_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["grade_id"], ["dictionary_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["division_id"], ["divisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vacancies_tenant_id"), "vacancies", ["tenant_id"], unique=False
    )

    # ── 5. vacancy_profiles ──────────────────────────────────────────
    op.create_table(
        "vacancy_profiles",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("vacancy_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "language", sa.String(length=10), server_default="en", nullable=False
        ),
        sa.Column("coverage_note", sa.Text(), nullable=True),
        sa.Column("generated_by", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vacancy_id", name="uq_vacancy_profiles_vacancy_id"),
    )
    op.create_index(
        op.f("ix_vacancy_profiles_tenant_id"),
        "vacancy_profiles",
        ["tenant_id"],
        unique=False,
    )

    # ── 6. vacancy_stages ────────────────────────────────────────────
    op.create_table(
        "vacancy_stages",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("vacancy_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "is_terminal", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vacancy_stages_tenant_id"),
        "vacancy_stages",
        ["tenant_id"],
        unique=False,
    )

    # ── 7. candidates ────────────────────────────────────────────────
    op.create_table(
        "candidates",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id", "tenant_id", name="uq_candidate_person_tenant"
        ),
    )
    op.create_index(
        op.f("ix_candidates_tenant_id"), "candidates", ["tenant_id"], unique=False
    )

    # ── 8. candidate_vacancies ───────────────────────────────────────
    op.create_table(
        "candidate_vacancies",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("vacancy_id", sa.UUID(), nullable=False),
        sa.Column("stage_id", sa.UUID(), nullable=True),
        sa.Column(
            "status", sa.String(length=50), server_default="new", nullable=False
        ),
        sa.Column(
            "status_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("ranking_score", sa.Float(), nullable=True),
        sa.Column("attached_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"], ["vacancy_stages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["attached_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_vacancies_tenant_id"),
        "candidate_vacancies",
        ["tenant_id"],
        unique=False,
    )

    # ── 9. resumes ───────────────────────────────────────────────────
    op.create_table(
        "resumes",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column(
            "parsed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column(
            "parse_status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resumes_tenant_id"), "resumes", ["tenant_id"], unique=False
    )

    # ── 10. candidate_questions ──────────────────────────────────────
    op.create_table(
        "candidate_questions",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("vacancy_id", sa.UUID(), nullable=False),
        sa.Column("competence_id", sa.UUID(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("good_answer", sa.Text(), nullable=False),
        sa.Column("acceptable_answer", sa.Text(), nullable=False),
        sa.Column("poor_answer", sa.Text(), nullable=False),
        sa.Column("resume_fragment", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_questions_tenant_id"),
        "candidate_questions",
        ["tenant_id"],
        unique=False,
    )

    # ── 11. interviews ───────────────────────────────────────────────
    op.create_table(
        "interviews",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_vacancy_id", sa.UUID(), nullable=False),
        sa.Column("interviewer_id", sa.UUID(), nullable=True),
        sa.Column("interview_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("audio_file_id", sa.UUID(), nullable=True),
        sa.Column("video_file_id", sa.UUID(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_vacancy_id"],
            ["candidate_vacancies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interviewer_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["audio_file_id"], ["files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["video_file_id"], ["files.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interviews_tenant_id"), "interviews", ["tenant_id"], unique=False
    )

    # ── 12. interview_segments ───────────────────────────────────────
    op.create_table(
        "interview_segments",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("interview_id", sa.UUID(), nullable=False),
        sa.Column("speaker", sa.String(length=50), nullable=False),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["interview_id"], ["interviews.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interview_segments_tenant_id"),
        "interview_segments",
        ["tenant_id"],
        unique=False,
    )

    # ── 13. human_assessments ────────────────────────────────────────
    op.create_table(
        "human_assessments",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_vacancy_id", sa.UUID(), nullable=False),
        sa.Column("competence_id", sa.UUID(), nullable=False),
        sa.Column("evaluator_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_vacancy_id"],
            ["candidate_vacancies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evaluator_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_human_assessments_tenant_id"),
        "human_assessments",
        ["tenant_id"],
        unique=False,
    )

    # ── 14. ai_assessments ───────────────────────────────────────────
    op.create_table(
        "ai_assessments",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("interview_id", sa.UUID(), nullable=False),
        sa.Column("competence_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["interview_id"], ["interviews.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_assessments_tenant_id"),
        "ai_assessments",
        ["tenant_id"],
        unique=False,
    )

    # ── 15. assessment_invites ───────────────────────────────────────
    op.create_table(
        "assessment_invites",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("candidate_vacancy_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=100), nullable=False, unique=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_vacancy_id"],
            ["candidate_vacancies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assessment_invites_tenant_id"),
        "assessment_invites",
        ["tenant_id"],
        unique=False,
    )

    # ── 16. consolidated_reports ─────────────────────────────────────
    op.create_table(
        "consolidated_reports",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("vacancy_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=True),
        sa.Column(
            "report_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("generated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["generated_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_consolidated_reports_tenant_id"),
        "consolidated_reports",
        ["tenant_id"],
        unique=False,
    )

    # ── 17. scale_configs ────────────────────────────────────────────
    op.create_table(
        "scale_configs",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("step", sa.Float(), server_default="0.5", nullable=False),
        sa.Column(
            "labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_scale_configs_tenant_id"),
        "scale_configs",
        ["tenant_id"],
        unique=False,
    )

    # ── 18. report_templates ─────────────────────────────────────────
    op.create_table(
        "report_templates",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "template_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "is_default", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_templates_tenant_id"),
        "report_templates",
        ["tenant_id"],
        unique=False,
    )

    # ── 19. llm_provider_configs ─────────────────────────────────────
    op.create_table(
        "llm_provider_configs",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_provider_configs_tenant_id"),
        "llm_provider_configs",
        ["tenant_id"],
        unique=False,
    )

    # ── 20. transcription_provider_configs ───────────────────────────
    op.create_table(
        "transcription_provider_configs",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transcription_provider_configs_tenant_id"),
        "transcription_provider_configs",
        ["tenant_id"],
        unique=False,
    )

    # ── Seed: roles ──────────────────────────────────────────────────
    op.execute("""
        INSERT INTO roles (id, name, code, description, is_system, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Recruiter', 'recruiter', 'Creates vacancies, manages candidates and hiring pipeline', true, now(), now()),
            (gen_random_uuid(), 'Hiring Manager', 'hiring_manager', 'Reviews candidates for assigned vacancies, fills assessment sheets', true, now(), now())
        ON CONFLICT (code) DO NOTHING
    """)

    # ── Seed: default vacancy stages ─────────────────────────────────
    op.execute("""
        INSERT INTO vacancy_stages (id, tenant_id, vacancy_id, name, code, sort_order, is_terminal, color, created_at, updated_at)
        VALUES
            (gen_random_uuid(), NULL, NULL, 'New', 'new', 10, false, 'slate-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Screening', 'screening', 20, false, 'blue-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Interview', 'interview', 30, false, 'cyan-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Evaluation', 'evaluation', 40, false, 'violet-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Final Stage', 'final', 50, false, 'amber-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Offer', 'offer', 60, false, 'emerald-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Hired', 'hired', 70, true, 'emerald-700', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Rejected', 'rejected', 80, true, 'rose-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'On Hold', 'on_hold', 90, false, 'slate-300', now(), now())
    """)


def downgrade() -> None:
    # Drop seed data
    op.execute(
        "DELETE FROM vacancy_stages WHERE tenant_id IS NULL AND vacancy_id IS NULL"
    )
    op.execute("DELETE FROM roles WHERE code IN ('recruiter', 'hiring_manager')")

    # Drop tables in reverse dependency order
    op.drop_index(
        op.f("ix_transcription_provider_configs_tenant_id"),
        table_name="transcription_provider_configs",
    )
    op.drop_table("transcription_provider_configs")

    op.drop_index(
        op.f("ix_llm_provider_configs_tenant_id"),
        table_name="llm_provider_configs",
    )
    op.drop_table("llm_provider_configs")

    op.drop_index(
        op.f("ix_report_templates_tenant_id"), table_name="report_templates"
    )
    op.drop_table("report_templates")

    op.drop_index(
        op.f("ix_scale_configs_tenant_id"), table_name="scale_configs"
    )
    op.drop_table("scale_configs")

    op.drop_index(
        op.f("ix_consolidated_reports_tenant_id"),
        table_name="consolidated_reports",
    )
    op.drop_table("consolidated_reports")

    op.drop_index(
        op.f("ix_assessment_invites_tenant_id"),
        table_name="assessment_invites",
    )
    op.drop_table("assessment_invites")

    op.drop_index(
        op.f("ix_ai_assessments_tenant_id"), table_name="ai_assessments"
    )
    op.drop_table("ai_assessments")

    op.drop_index(
        op.f("ix_human_assessments_tenant_id"), table_name="human_assessments"
    )
    op.drop_table("human_assessments")

    op.drop_index(
        op.f("ix_interview_segments_tenant_id"),
        table_name="interview_segments",
    )
    op.drop_table("interview_segments")

    op.drop_index(
        op.f("ix_interviews_tenant_id"), table_name="interviews"
    )
    op.drop_table("interviews")

    op.drop_index(
        op.f("ix_candidate_questions_tenant_id"),
        table_name="candidate_questions",
    )
    op.drop_table("candidate_questions")

    op.drop_index(op.f("ix_resumes_tenant_id"), table_name="resumes")
    op.drop_table("resumes")

    op.drop_index(
        op.f("ix_candidate_vacancies_tenant_id"),
        table_name="candidate_vacancies",
    )
    op.drop_table("candidate_vacancies")

    op.drop_index(
        op.f("ix_candidates_tenant_id"), table_name="candidates"
    )
    op.drop_table("candidates")

    op.drop_index(
        op.f("ix_vacancy_stages_tenant_id"), table_name="vacancy_stages"
    )
    op.drop_table("vacancy_stages")

    op.drop_index(
        op.f("ix_vacancy_profiles_tenant_id"), table_name="vacancy_profiles"
    )
    op.drop_table("vacancy_profiles")

    op.drop_index(
        op.f("ix_vacancies_tenant_id"), table_name="vacancies"
    )
    op.drop_table("vacancies")

    # Remove person_id from users
    op.drop_constraint("fk_users_person_id_persons", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_person_id"), table_name="users")
    op.drop_column("users", "person_id")

    # Drop persons
    op.drop_index(op.f("ix_persons_email"), table_name="persons")
    op.drop_table("persons")
