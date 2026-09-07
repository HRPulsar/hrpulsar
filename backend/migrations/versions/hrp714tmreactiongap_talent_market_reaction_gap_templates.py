"""HRP-714: soft auto-reply on a below-the-bar talent-market reaction

Two templates. ``talent_market.reaction_gap`` goes to the employee who
just reacted to a card they do not clear: the reaction stands, they stay
on the candidate list, and the letter points at a development plan
instead of at a rejection. ``talent_market.plan_requested`` goes to their
manager when they ask for that plan — an employee cannot create one for
themselves. Russian bodies live in the ee branch (ee018 precedent):
Cyrillic must never reach the public migration tree.

Revision ID: hrp714tmreactiongap
Revises: hrp699ivlifecycle
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp714tmreactiongap"
down_revision: str | Sequence[str] | None = "hrp699ivlifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, locale, subject, body)
_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "talent_market.reaction_gap",
        "en",
        "About your response to {{ card_title }}",
        "<p>We noticed that some skills in your profile differ a little "
        "from what this opportunity requires. Passing the selection right "
        "now may be hard, but that is no reason to be discouraged!</p>"
        "<p>We believe in your growth: you stay on the candidate list for "
        "this and similar positions, and we will let you know when a new "
        "opportunity opens if you are not confirmed this time.</p>"
        "<p>Meanwhile you can close the gaps with a development plan, and "
        "next time your chances will be even higher."
        '{% if link_url %} <a href="{{ link_url }}">Open '
        "{{ card_title }}</a>{% endif %}</p>",
    ),
    (
        "talent_market.reaction_gap",
        "de",
        "Zu deiner Bewerbung auf {{ card_title }}",
        "<p>Uns ist aufgefallen, dass einige Kompetenzen in deinem Profil "
        "ein wenig von den Anforderungen dieser Gelegenheit abweichen. "
        "Die Auswahl jetzt zu bestehen, könnte schwierig werden — aber das "
        "ist kein Grund, den Mut zu verlieren!</p>"
        "<p>Wir glauben an deine Entwicklung: Du bleibst auf der "
        "Kandidatenliste für diese und ähnliche Positionen, und wir melden "
        "uns, sobald sich eine neue Gelegenheit ergibt, falls es diesmal "
        "nicht klappt.</p>"
        "<p>Bis dahin kannst du die Lücken mit einem Entwicklungsplan "
        "schließen, und beim nächsten Mal stehen deine Chancen noch besser."
        '{% if link_url %} <a href="{{ link_url }}">'
        "{{ card_title }} öffnen</a>{% endif %}</p>",
    ),
    (
        "talent_market.plan_requested",
        "en",
        "{{ employee_name }} asked for a development plan",
        "<p><b>{{ employee_name }}</b> asked for a development plan for "
        "<b>{{ card_title }}</b>.</p>"
        '{% if link_url %}<p><a href="{{ link_url }}">Open the '
        "candidate</a></p>{% endif %}",
    ),
    (
        "talent_market.plan_requested",
        "de",
        "{{ employee_name }} hat um einen Entwicklungsplan gebeten",
        "<p><b>{{ employee_name }}</b> hat um einen Entwicklungsplan für "
        "<b>{{ card_title }}</b> gebeten.</p>"
        '{% if link_url %}<p><a href="{{ link_url }}">Kandidatin bzw. '
        "Kandidat öffnen</a></p>{% endif %}",
    ),
)

_CODES = ("talent_market.reaction_gap", "talent_market.plan_requested")


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
