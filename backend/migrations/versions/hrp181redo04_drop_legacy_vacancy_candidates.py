"""HRP-181 REDO Stage 5: drop the legacy ``vacancy_candidates`` table

Stages 1-4 moved every candidate flow onto the canonical
``candidates`` + ``candidate_vacancies`` pair. The v1.9.5 lite
``vacancy_candidates`` table no longer has any callers — the router
endpoints, service helpers, schemas, billing entries, and the
frontend ``LiteCandidatesSection`` are all removed in the Stage 5
cleanup. Production never opened the lite UI before the QA REDO, so
the table is expected to be empty in every tenant.

Revision ID: hrp181redo04
Revises: hrp181redo03
Create Date: 2026-06-08 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp181redo04"
down_revision: str | None = "hrp181redo03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Refuse to drop a populated table. Production never opened the lite UI
    # before the QA REDO, so the table is expected to be empty in every
    # tenant — but if any tenant did exercise the v1.9.5 router, abort here
    # so the operator can decide how to migrate the data instead of losing
    # it silently.
    conn = op.get_bind()
    exists = conn.exec_driver_sql(
        "SELECT to_regclass('public.vacancy_candidates') IS NOT NULL"
    ).scalar()
    if exists:
        row_count = conn.exec_driver_sql(
            "SELECT count(*) FROM vacancy_candidates"
        ).scalar()
        if row_count and int(row_count) > 0:
            raise RuntimeError(
                f"vacancy_candidates has {row_count} row(s); refuse to "
                "drop. Archive or migrate the rows manually, then re-run "
                "`alembic upgrade head`."
            )
        op.drop_index(
            "ix_vacancy_candidates_vacancy_id",
            table_name="vacancy_candidates",
            if_exists=True,
        )
        op.execute("DROP TABLE IF EXISTS vacancy_candidates")


def downgrade() -> None:
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
