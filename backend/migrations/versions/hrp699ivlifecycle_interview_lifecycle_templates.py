"""HRP-699: interview rescheduled / removed / cancelled templates

The scheduling lifecycle beyond the initial invite. ``interview_scheduled``
already exists (R4c seed, HRP-419 body) and is reused for someone added to
an interview later; these three cover the moves, the drops and the
cancellations. Russian bodies live in the ee branch (ee011 precedent) —
Cyrillic must never reach the public migration tree.

Revision ID: hrp699ivlifecycle
Revises: hrp684consentresend
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp699ivlifecycle"
down_revision: str | Sequence[str] | None = "hrp684consentresend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, locale, subject, body)
_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "recruitment.interview_rescheduled",
        "en",
        "Interview with {{ candidate_name }} moved",
        "<p>The interview with <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} for the <b>{{ vacancy_title }}</b> position"
        "{% endif %} has been moved"
        "{% if interview_date %} to <b>{{ interview_date }}</b>{% endif %}.</p>",
    ),
    (
        "recruitment.interview_rescheduled",
        "de",
        "Interview mit {{ candidate_name }} verschoben",
        "<p>Das Interview mit <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} für die Position <b>{{ vacancy_title }}</b>"
        "{% endif %} wurde"
        "{% if interview_date %} auf <b>{{ interview_date }}</b>{% endif %} "
        "verschoben.</p>",
    ),
    (
        "recruitment.interview_interviewer_removed",
        "en",
        "You were removed from the interview with {{ candidate_name }}",
        "<p>You are no longer an interviewer for <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} on the <b>{{ vacancy_title }}</b> position"
        "{% endif %}{% if interview_date %} ({{ interview_date }})"
        "{% endif %}.</p>",
    ),
    (
        "recruitment.interview_interviewer_removed",
        "de",
        "Sie wurden aus dem Interview mit {{ candidate_name }} entfernt",
        "<p>Sie sind nicht mehr als Interviewer für <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} auf die Position <b>{{ vacancy_title }}</b>"
        "{% endif %}{% if interview_date %} ({{ interview_date }})"
        "{% endif %} eingeteilt.</p>",
    ),
    (
        "recruitment.interview_cancelled",
        "en",
        "Interview with {{ candidate_name }} cancelled",
        "<p>The interview with <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} for the <b>{{ vacancy_title }}</b> position"
        "{% endif %}{% if interview_date %} on {{ interview_date }}{% endif %} "
        "has been cancelled.</p>",
    ),
    (
        "recruitment.interview_cancelled",
        "de",
        "Interview mit {{ candidate_name }} abgesagt",
        "<p>Das Interview mit <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} für die Position <b>{{ vacancy_title }}</b>"
        "{% endif %}{% if interview_date %} am {{ interview_date }}{% endif %} "
        "wurde abgesagt.</p>",
    ),
)

_CODES = (
    "recruitment.interview_rescheduled",
    "recruitment.interview_interviewer_removed",
    "recruitment.interview_cancelled",
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, locale, subject, body in _TEMPLATES:
        bind.execute(
            sa.text("""
                INSERT INTO notification_templates
                    (id, code, locale, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :locale, :subject, :body,
                     'email', now(), now())
                ON CONFLICT (code, locale) DO UPDATE SET
                    subject_template = EXCLUDED.subject_template,
                    body_template = EXCLUDED.body_template,
                    updated_at = now()
                """),
            {"code": code, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    # In-app rows reference the template by FK with no ON DELETE clause,
    # so the children have to go first.
    for code in _CODES:
        bind.execute(
            sa.text("""
                DELETE FROM notifications
                WHERE template_id IN (
                    SELECT id FROM notification_templates WHERE code = :code
                )
                """),
            {"code": code},
        )
        bind.execute(
            sa.text("DELETE FROM notification_templates WHERE code = :code"),
            {"code": code},
        )
