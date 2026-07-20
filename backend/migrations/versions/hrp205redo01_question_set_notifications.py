"""HRP-205 REDO: question_set_ready / question_set_failed notification templates.

Revision ID: hrp205redo01
Revises: hrp274backfillnorm
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from alembic import op

revision: str = "hrp205redo01"
down_revision: str | None = "hrp274backfillnorm"
branch_labels = None
depends_on = None

_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "recruitment.question_set_ready",
        "Interview questions ready: {{ candidate_name }}",
        (
            "<p>A new interview question set for <b>{{ candidate_name }}</b>"
            " is ready to review.</p>"
        ),
    ),
    (
        "recruitment.question_set_failed",
        "Question generation failed: {{ candidate_name }}",
        (
            "<p>AI question generation for <b>{{ candidate_name }}</b>"
            " failed. Open the candidate page to retry.</p>"
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, subject, body in _TEMPLATES:
        bind.execute(
            sa.text("""
                INSERT INTO notification_templates
                    (id, code, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :subject, :body,
                     'email', now(), now())
                ON CONFLICT (code) DO NOTHING
                """),
            {"code": code, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [c for c, _, _ in _TEMPLATES]
    bind.execute(
        sa.text("DELETE FROM notification_templates WHERE code = ANY(:codes)"),
        {"codes": codes},
    )
