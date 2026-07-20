"""R4c: recruitment notifications templates, onboarding state, report sharing.

Adds:
- ``tenants.recruitment_onboarding`` (JSONB) — wizard step + flags (SCR-A1..A5).
- ``consent_requests.requested_by`` — recruiter who issued the magic link
  (used to route the consent-signed notification to that user instead
  of the whole admin group).
- ``recruitment_report_shares`` (FR-22, SCR-84) — tokenised XLSX share links
  with expiry, recipients log and open counter.
- Seed rows in ``notification_templates`` for the ten recruitment events
  defined in §8.5 / SCR-03.

This migration is also the merge point between ``asr1a1b2c3d4e5`` (HRP-27
assessment statuses) and ``r4b2c3d4e5f6`` (one-active-scale invariant) so
``alembic upgrade head`` resolves to a single head after R4c.

Revision ID: r4c1b2c3d4e5
Revises: asr1a1b2c3d4e5, r4b2c3d4e5f6
Create Date: 2026-05-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r4c1b2c3d4e5"
down_revision: str | tuple[str, ...] | None = ("asr1a1b2c3d4e5", "r4b2c3d4e5f6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RECRUITMENT_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "recruitment.vacancy_assigned",
        "Vacancy assigned: {{ vacancy_title }}",
        "<p>You have been assigned as the owner of vacancy <b>{{ vacancy_title }}</b>.</p>",
    ),
    (
        "recruitment.candidate_attached",
        "New candidate on {{ vacancy_title }}",
        "<p>{{ candidate_name }} has been attached to <b>{{ vacancy_title }}</b>.</p>",
    ),
    (
        "recruitment.candidate_stage_changed",
        "{{ candidate_name }} moved to {{ stage_name }}",
        "<p>{{ candidate_name }} on <b>{{ vacancy_title }}</b> is now in stage <b>{{ stage_name }}</b>.</p>",
    ),
    (
        "recruitment.interview_scheduled",
        "Interview scheduled with {{ candidate_name }}",
        "<p>You are assigned to interview <b>{{ candidate_name }}</b>{% if interview_date %} on {{ interview_date }}{% endif %}.</p>",
    ),
    (
        "recruitment.interview_transcript_ready",
        "Transcript ready: {{ candidate_name }}",
        "<p>The interview transcript for <b>{{ candidate_name }}</b> is ready to review.</p>",
    ),
    (
        "recruitment.interview_analysis_ready",
        "AI analysis ready: {{ candidate_name }}",
        "<p>AI analysis of the interview with <b>{{ candidate_name }}</b> is complete.</p>",
    ),
    (
        "recruitment.report_generated",
        "Report ready: {{ vacancy_title }}",
        "<p>Your consolidated report for <b>{{ vacancy_title }}</b> is ready to download.</p>",
    ),
    (
        "recruitment.consent_signed",
        "Consent signed: {{ candidate_name }}",
        "<p>{{ candidate_name }} has signed the recruitment consent form.</p>",
    ),
    (
        "recruitment.invite_completed",
        "Evaluation submitted by {{ evaluator_name }}",
        "<p>{{ evaluator_name }} has submitted an evaluation for <b>{{ candidate_name }}</b>.</p>",
    ),
    (
        "recruitment.ai_task_failed",
        "Recruitment AI task failed",
        "<p>A background AI task failed: {{ task_type }}{% if error %} — {{ error }}{% endif %}.</p>",
    ),
    (
        "recruitment.report_shared",
        "{{ shared_by_name }} shared a recruitment report",
        "<p>You have been granted a temporary link to a recruitment report for <b>{{ vacancy_title }}</b>.</p><p><a href='{{ share_url }}'>Open report</a></p><p>The link expires on {{ expires_at }}.</p>",
    ),
)


def upgrade() -> None:
    # ── tenants.recruitment_onboarding ─────────────────────────────────
    op.add_column(
        "tenants",
        sa.Column(
            "recruitment_onboarding",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ── consent_requests.requested_by ──────────────────────────────────
    op.add_column(
        "consent_requests",
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_consent_requests_requested_by",
        "consent_requests",
        ["requested_by"],
    )

    # ── recruitment_report_shares ──────────────────────────────────────
    op.create_table(
        "recruitment_report_shares",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consolidated_reports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token", sa.String(length=100), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_opened_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "open_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
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
    )
    op.create_index(
        "ix_recruitment_report_shares_token",
        "recruitment_report_shares",
        ["token"],
        unique=True,
    )

    # ── notification_templates seed ────────────────────────────────────
    bind = op.get_bind()
    for code, subject, body in _RECRUITMENT_TEMPLATES:
        bind.execute(
            sa.text(
                """
                INSERT INTO notification_templates
                    (id, code, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :subject, :body,
                     'email', now(), now())
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [c for c, _, _ in _RECRUITMENT_TEMPLATES]
    bind.execute(
        sa.text("DELETE FROM notification_templates WHERE code = ANY(:codes)"),
        {"codes": codes},
    )
    op.drop_index(
        "ix_recruitment_report_shares_token",
        table_name="recruitment_report_shares",
    )
    op.drop_table("recruitment_report_shares")
    op.drop_index(
        "ix_consent_requests_requested_by", table_name="consent_requests"
    )
    op.drop_column("consent_requests", "requested_by")
    op.drop_column("tenants", "recruitment_onboarding")
