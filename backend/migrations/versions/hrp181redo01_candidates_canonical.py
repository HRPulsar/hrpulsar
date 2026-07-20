"""HRP-181 REDO: canonical Candidate model + AI fields + candidate_files rename

Stage 1 of the rework. Converges the two parallel junction shapes
(``candidate_vacancies`` + the v1.9.5 lite ``vacancy_candidates``) on a
single canonical model and prepares it for the full spec UX:

- ``candidates.person_id`` becomes nullable so externally-sourced
  candidates (no tenant ``Person`` row) can live in the same table.
- Denormalised display fields land on ``candidates`` (``full_name``,
  ``email``, ``phone``, ``linkedin_url``, ``location``,
  ``current_position``, ``years_of_experience``, ``parsed_resume_jsonb``,
  ``archived_at``). Existing rows are backfilled from the linked
  ``persons`` row.
- Partial unique index on ``(tenant_id, lower(email))`` filtered by
  ``archived_at IS NULL`` — duplicate-detect for the Upload-resume flow.
- ``candidate_vacancies`` gains the FR-23 AI block
  (``ai_score / ai_readiness / ai_verdict / ai_verdict_summary /
   ai_key_strength / ai_key_risk / ai_risk_mitigation``), ``version`` for
  ETag concurrency, and ``added_at`` (backfilled from ``created_at``).
- ``resumes`` is renamed to ``candidate_files`` and gains a ``file_type``
  discriminator (``'resume'`` default; ``'interview'`` once the upload
  flow lands).
- ``vacancy_stages`` gains a ``stage_type`` enum-as-string
  (``active`` / ``terminal_positive`` / ``terminal_negative`` /
  ``terminal_neutral``). ``is_terminal`` is retained for back-compat but
  ``stage_type`` is the source of truth going forward.

The v1.9.5 ``vacancy_candidates`` table is *not* dropped here — Stage 5
will remove it after the frontend migrates off ``/lite-candidates``.

Revision ID: hrp181redo01
Revises: b5479f096f8b
Create Date: 2026-06-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp181redo01"
down_revision: str | None = "b5479f096f8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── vacancy_stages: stage_type ──────────────────────────────────────
    op.add_column(
        "vacancy_stages",
        sa.Column(
            "stage_type",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    )
    op.execute(
        """
        UPDATE vacancy_stages
        SET stage_type = CASE
            WHEN code = 'hired' THEN 'terminal_positive'
            WHEN code = 'rejected' THEN 'terminal_negative'
            WHEN code IN ('withdrew', 'on_hold') THEN 'terminal_neutral'
            ELSE 'active'
        END
        """
    )

    # ── candidates: nullable person_id + denormalised fields ────────────
    op.alter_column(
        "candidates",
        "person_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "candidates", sa.Column("full_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("email", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("phone", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "candidates",
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "candidates", sa.Column("location", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "candidates",
        sa.Column("current_position", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "candidates", sa.Column("years_of_experience", sa.Integer(), nullable=True)
    )
    op.add_column(
        "candidates",
        sa.Column(
            "parsed_resume_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill denormalised fields from the linked Person, if any.
    op.execute(
        """
        UPDATE candidates c
        SET full_name = NULLIF(
            TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)),
            ''
        ),
            email = p.email,
            phone = p.phone
        FROM persons p
        WHERE c.person_id = p.id
          AND c.full_name IS NULL
        """
    )
    # Anything still NULL — orphaned legacy row, fall back to a sentinel
    # so we can promote the column to NOT NULL without losing it.
    op.execute(
        "UPDATE candidates SET full_name = 'Unnamed candidate' "
        "WHERE full_name IS NULL OR full_name = ''"
    )
    op.alter_column(
        "candidates",
        "full_name",
        existing_type=sa.String(length=255),
        nullable=False,
    )

    op.create_index(
        "ix_candidates_archived_at",
        "candidates",
        ["archived_at"],
    )
    # Partial unique on lower(email), scoped to active (non-archived) rows
    # so a previously-archived candidate can be re-created on the same
    # address without colliding. Uses raw SQL because Alembic doesn't
    # express ``lower()`` in expression indexes cleanly.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_candidates_tenant_email_active
        ON candidates (tenant_id, lower(email))
        WHERE email IS NOT NULL AND archived_at IS NULL
        """
    )

    # ── candidate_vacancies: AI block + version + added_at ──────────────
    op.add_column(
        "candidate_vacancies", sa.Column("ai_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "ai_readiness",
            sa.String(length=30),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "ai_verdict",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column("ai_verdict_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column("ai_key_strength", sa.Text(), nullable=True),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column("ai_key_risk", sa.Text(), nullable=True),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column("ai_risk_mitigation", sa.Text(), nullable=True),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "candidate_vacancies",
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE candidate_vacancies SET added_at = created_at "
        "WHERE added_at IS NULL"
    )
    op.alter_column(
        "candidate_vacancies",
        "added_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    # ── resumes → candidate_files (+ file_type discriminator) ───────────
    op.rename_table("resumes", "candidate_files")
    op.add_column(
        "candidate_files",
        sa.Column(
            "file_type",
            sa.String(length=20),
            nullable=False,
            server_default="resume",
        ),
    )


def downgrade() -> None:
    # ── candidate_files → resumes ───────────────────────────────────────
    op.drop_column("candidate_files", "file_type")
    op.rename_table("candidate_files", "resumes")

    # ── candidate_vacancies ─────────────────────────────────────────────
    op.drop_column("candidate_vacancies", "added_at")
    op.drop_column("candidate_vacancies", "version")
    op.drop_column("candidate_vacancies", "ai_risk_mitigation")
    op.drop_column("candidate_vacancies", "ai_key_risk")
    op.drop_column("candidate_vacancies", "ai_key_strength")
    op.drop_column("candidate_vacancies", "ai_verdict_summary")
    op.drop_column("candidate_vacancies", "ai_verdict")
    op.drop_column("candidate_vacancies", "ai_readiness")
    op.drop_column("candidate_vacancies", "ai_score")

    # ── candidates ──────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ux_candidates_tenant_email_active")
    op.drop_index("ix_candidates_archived_at", table_name="candidates")
    op.drop_column("candidates", "archived_at")
    op.drop_column("candidates", "parsed_resume_jsonb")
    op.drop_column("candidates", "years_of_experience")
    op.drop_column("candidates", "current_position")
    op.drop_column("candidates", "location")
    op.drop_column("candidates", "linkedin_url")
    op.drop_column("candidates", "phone")
    op.drop_column("candidates", "email")
    op.drop_column("candidates", "full_name")
    op.alter_column(
        "candidates",
        "person_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    # ── vacancy_stages ──────────────────────────────────────────────────
    op.drop_column("vacancy_stages", "stage_type")
