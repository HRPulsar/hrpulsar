"""HRP-984: an AI agent grant whose accountable owner left needs a new one

``ai_usage_assignments.status`` gains ``needs_owner``: when an employee
stops working, the grants in force they answer for are suspended until a
new owner at work is named, and the tenant's admins get one notification
per departure - ``ai_workforce.owner_needed`` (en/de here; the Russian row
lives in the ee branch with depends_on, ee019 / ee021 precedent).

Downgrade puts the suspended rows back to ``active`` - what they were
before the feature - restores the old CHECK and drops the template.

Revision ID: hrp984aiownerneeded
Revises: hrp982stagetpl01
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp984aiownerneeded"
down_revision: str | Sequence[str] | None = "hrp982stagetpl01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "ai_workforce.owner_needed"
_CHECK = "ck_ai_assignments_status"
_OLD = "status IN ('pending', 'active', 'rejected', 'revoked')"
_NEW = "status IN ('pending', 'active', 'rejected', 'revoked', 'needs_owner')"

# (locale, subject, body)
_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "en",
        "{{ count }} AI agent {% if count == 1 %}assignment needs"
        "{% else %}assignments need{% endif %} a new accountable owner",
        "<p><b>{{ employee_name }}</b> is no longer an active employee and "
        "was the accountable owner of {{ count }} AI agent "
        "{% if count == 1 %}assignment. It is{% else %}assignments. They are"
        "{% endif %} suspended until a new accountable owner is named.</p>"
        '{% if link_url %}<p><a href="{{ link_url }}">Open Coverage</a></p>'
        "{% endif %}",
    ),
    (
        "de",
        "{{ count }} {% if count == 1 %}KI-Agenten-Zuweisung braucht"
        "{% else %}KI-Agenten-Zuweisungen brauchen{% endif %} eine neue "
        "verantwortliche Person",
        "<p><b>{{ employee_name }}</b> ist nicht mehr aktiv beschäftigt und "
        "war für {{ count }} {% if count == 1 %}KI-Agenten-Zuweisung"
        "{% else %}KI-Agenten-Zuweisungen{% endif %} verantwortlich. Bis eine "
        "neue verantwortliche Person benannt ist, {% if count == 1 %}ist sie"
        "{% else %}sind sie{% endif %} ausgesetzt.</p>"
        '{% if link_url %}<p><a href="{{ link_url }}">Abdeckung öffnen</a>'
        "</p>{% endif %}",
    ),
)


def upgrade() -> None:
    op.drop_constraint(_CHECK, "ai_usage_assignments", type_="check")
    op.create_check_constraint(_CHECK, "ai_usage_assignments", _NEW)
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
                ON CONFLICT (code, locale) DO UPDATE SET
                    subject_template = EXCLUDED.subject_template,
                    body_template = EXCLUDED.body_template,
                    updated_at = now()
                """),
            {"code": _CODE, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE ai_usage_assignments SET status = 'active' "
            "WHERE status = 'needs_owner'"
        )
    )
    op.drop_constraint(_CHECK, "ai_usage_assignments", type_="check")
    op.create_check_constraint(_CHECK, "ai_usage_assignments", _OLD)
    # In-app rows reference the template by FK with no ON DELETE clause,
    # so the children have to go first.
    bind.execute(
        sa.text("""
            DELETE FROM notifications
            WHERE template_id IN (
                SELECT id FROM notification_templates WHERE code = :code
            )
            """),
        {"code": _CODE},
    )
    bind.execute(
        sa.text("DELETE FROM notification_templates WHERE code = :code"),
        {"code": _CODE},
    )
