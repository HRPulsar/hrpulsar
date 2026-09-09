"""HRP-379: notification template for a submitted external evaluation.

The external evaluator's page promises "{owner} will be notified" on
submit and nothing was ever sent. The owner now gets "Submitted
assessment for candidate {name}" with a link into the candidate's
Manager assessments block.

Both locales are seeded here: the recipient is an account holder, so the
template resolves against *their* interface locale and an en-only row
would leave a German user with an English email.

Revision ID: hrp379submittpl01
Revises: hrp714tmreactiongap
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp379submittpl01"
down_revision: str | None = "hrp714tmreactiongap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "recruitment.assessment_evaluator_submitted"

# The round name is prose, so it is rendered per locale from
# ``round_type`` / ``round_number`` rather than shipped pre-formatted
# (same shape as the hrp373 invitation template).
_ROUND_EN = (
    "{% if round_type == 'pre_interview' %}Pre-interview"
    "{% elif round_type == 'final' %}Final"
    "{% else %}Interview {{ round_number or 1 }}{% endif %}"
)
_ROUND_DE = (
    "{% if round_type == 'pre_interview' %}Vorgespräch"
    "{% elif round_type == 'final' %}Abschluss"
    "{% else %}Interview {{ round_number or 1 }}{% endif %}"
)

_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "en",
        "Submitted assessment for candidate {{ candidate_name }}",
        (
            "<p><b>{{ evaluator_name }}</b> has submitted an evaluation of "
            "<b>{{ candidate_name }}</b>"
            "{% if vacancy_title %} for the role of <b>{{ vacancy_title }}</b>"
            "{% endif %} — round <b>" + _ROUND_EN + "</b>.</p>"
            '<p><a href="{{ link_url }}">Open the candidate</a></p>'
        ),
    ),
    (
        "de",
        "Eingereichte Bewertung für den Kandidaten {{ candidate_name }}",
        (
            "<p><b>{{ evaluator_name }}</b> hat eine Bewertung von "
            "<b>{{ candidate_name }}</b>"
            "{% if vacancy_title %} für die Position <b>{{ vacancy_title }}</b>"
            "{% endif %} abgegeben — Runde <b>" + _ROUND_DE + "</b>.</p>"
            '<p><a href="{{ link_url }}">Kandidat öffnen</a></p>'
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for locale, subject, body in _TEMPLATES:
        bind.execute(
            sa.text("""
                INSERT INTO notification_templates
                    (id, code, locale, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :locale, :subject, :body,
                     'email', now(), now())
                ON CONFLICT (code, locale) DO NOTHING
                """),
            {"code": CODE, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    # In-app rows reference the template by FK; drop them first so the
    # delete cannot fail on an installation that already sent one.
    bind.execute(
        sa.text("""
            DELETE FROM notifications
            WHERE template_id IN (
                SELECT id FROM notification_templates WHERE code = :code
            )
            """),
        {"code": CODE},
    )
    bind.execute(
        sa.text("DELETE FROM notification_templates WHERE code = :code"),
        {"code": CODE},
    )
