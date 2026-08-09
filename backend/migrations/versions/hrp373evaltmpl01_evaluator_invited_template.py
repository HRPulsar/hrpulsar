"""HRP-373: notification template for an internal evaluator invitation.

Adding a colleague through `+ Add evaluator` sends them
"Invitation to evaluate candidate {name}" with a link straight to the
candidate page in the vacancy's context, round preselected.

Both locales are seeded here: the recipient is an account holder, so the
template resolves against *their* interface locale and an en-only row
would leave a German user with an English email.

Revision ID: hrp373evaltmpl01
Revises: 933b005f65e8
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp373evaltmpl01"
down_revision: str | None = "933b005f65e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "recruitment.assessment_evaluator_invited"

# The round name is prose, so it is rendered per locale from
# ``round_type`` / ``round_number`` rather than shipped pre-formatted.
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
        "Invitation to evaluate candidate {{ candidate_name }}",
        (
            "<p>You have been asked to evaluate <b>{{ candidate_name }}</b>"
            "{% if vacancy_title %} for the role of <b>{{ vacancy_title }}</b>"
            "{% endif %} — round <b>" + _ROUND_EN + "</b>.</p>"
            '<p><a href="{{ link_url }}">Open the evaluation sheet</a></p>'
        ),
    ),
    (
        "de",
        "Einladung zur Bewertung des Kandidaten {{ candidate_name }}",
        (
            "<p>Sie wurden gebeten, <b>{{ candidate_name }}</b>"
            "{% if vacancy_title %} für die Position <b>{{ vacancy_title }}</b>"
            "{% endif %} zu bewerten — Runde <b>" + _ROUND_DE + "</b>.</p>"
            '<p><a href="{{ link_url }}">Bewertungsbogen öffnen</a></p>'
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
