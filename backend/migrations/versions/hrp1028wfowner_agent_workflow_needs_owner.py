"""HRP-1028: an agent workflow whose owner left needs a new one

``agent_workflows.needs_owner``: when the owner stops working, each active
workflow they own is flagged until an owner at work is named. The admins
learn it from the HRP-984 letter ``ai_workforce.owner_needed``, which now
also counts the workflows (``workflow_count``). Without workflows the en/de
letter renders word for word as before. The Russian row lives in the ee
branch (ee031aiwfownerru), ee029aiownerru precedent.

Downgrade drops the column and puts the HRP-984 wording back.

Revision ID: hrp1028wfowner
Revises: rf3e_gdpr_blob_cleanup
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp1028wfowner"
down_revision: str | Sequence[str] | None = "rf3e_gdpr_blob_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "ai_workforce.owner_needed"

# (locale, subject, body)
_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "en",
        "{% set wc = workflow_count or 0 %}"
        "{% if count %}{{ count }} AI agent "
        "{% if count == 1 %}assignment{% else %}assignments{% endif %}"
        "{% if wc %} and {% endif %}{% endif %}"
        "{% if wc %}{{ wc }} AI "
        "{% if wc == 1 %}workflow{% else %}workflows{% endif %}{% endif %}"
        " {% if count + wc == 1 %}needs{% else %}need{% endif %} a new "
        "{% if count %}accountable {% endif %}owner",
        "{% set wc = workflow_count or 0 %}"
        "<p><b>{{ employee_name }}</b> is no longer an active employee"
        "{% if count %} and was the accountable owner of {{ count }} AI agent "
        "{% if count == 1 %}assignment. It is{% else %}assignments. They are"
        "{% endif %} suspended until a new accountable owner is named"
        "{% endif %}.</p>"
        "{% if wc %}<p>{% if wc == 1 %}One AI workflow they owned has "
        "nobody answering for it{% else %}{{ wc }} AI workflows they owned "
        "have nobody answering for them{% endif %} any more and "
        "{% if wc == 1 %}is{% else %}are"
        "{% endif %} marked as needing a new owner.</p>{% endif %}"
        '{% if link_url %}<p><a href="{{ link_url }}">Open Coverage</a></p>'
        "{% endif %}",
    ),
    (
        "de",
        "{% set wc = workflow_count or 0 %}"
        "{% if count %}{{ count }} "
        "{% if count == 1 %}KI-Agenten-Zuweisung{% else %}"
        "KI-Agenten-Zuweisungen{% endif %}{% if wc %} und {% endif %}{% endif %}"
        "{% if wc %}{{ wc }} "
        "{% if wc == 1 %}KI-Workflow{% else %}KI-Workflows{% endif %}{% endif %}"
        " {% if count + wc == 1 %}braucht{% else %}brauchen{% endif %} eine "
        "neue verantwortliche Person",
        "{% set wc = workflow_count or 0 %}"
        "<p><b>{{ employee_name }}</b> ist nicht mehr aktiv beschäftigt"
        "{% if count %} und war für {{ count }} "
        "{% if count == 1 %}KI-Agenten-Zuweisung{% else %}"
        "KI-Agenten-Zuweisungen{% endif %} verantwortlich. Bis eine neue "
        "verantwortliche Person benannt ist, {% if count == 1 %}ist sie"
        "{% else %}sind sie{% endif %} ausgesetzt{% endif %}.</p>"
        "{% if wc %}<p>{% if wc == 1 %}Ein KI-Workflow dieser Person hat"
        "{% else %}{{ wc }} KI-Workflows dieser Person haben{% endif %} keine "
        "verantwortliche Person mehr und {% if wc == 1 %}ist{% else %}sind"
        "{% endif %} entsprechend markiert.</p>{% endif %}"
        '{% if link_url %}<p><a href="{{ link_url }}">Abdeckung öffnen</a>'
        "</p>{% endif %}",
    ),
)

# The HRP-984 wording (hrp984aiownerneeded), for the downgrade.
_PREVIOUS: tuple[tuple[str, str, str], ...] = (
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


def _write(templates: tuple[tuple[str, str, str], ...]) -> None:
    bind = op.get_bind()
    for locale, subject, body in templates:
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


def upgrade() -> None:
    op.add_column(
        "agent_workflows",
        sa.Column("needs_owner", sa.Boolean(), nullable=False, server_default="false"),
    )
    _write(_TEMPLATES)


def downgrade() -> None:
    _write(_PREVIOUS)
    op.drop_column("agent_workflows", "needs_owner")
