"""AI Insights analysis notifications (HRP-494).

The only analysis notification in the catalog was
``recruitment.interview_analysis_ready``, fired from the interview
pipeline with ``candidate_name=None`` — the email read "AI analysis
ready: None" and offered no way back into the product.

This migration seeds the four codes the AI Insights block reports
under, in both locales:

* ``recruitment.resume_analysis_ready`` / ``_failed``
* ``recruitment.full_analysis_ready`` / ``_failed``

Each body names the candidate, says which mode ran, and links straight
to the AI Insights block for that vacancy (``{{ link_url }}`` is the
absolute URL the notification dispatcher derives from the payload's
relative ``link``).

The legacy ``recruitment.interview_analysis_ready`` row is also
repaired: it stays in service for the interview-page cache-hit path,
which has no candidate context, so its subject and body now degrade to
a name-less wording instead of printing "None". That UPDATE is guarded
by the currently seeded text, so an installation that customized the
template keeps its own copy.

Revision ID: hrp494ainotify01
Revises: 933b005f65e8
Create Date: 2026-08-07 12:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp494ainotify01"
down_revision: str | None = "933b005f65e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, locale, subject, body)
TEMPLATES: list[tuple[str, str, str, str]] = [
    (
        "recruitment.resume_analysis_ready",
        "en",
        "Resume analysis ready for {{ candidate_name }}",
        "<p>The resume-only AI analysis for <b>{{ candidate_name }}</b> is "
        "complete.</p>"
        "<p><a href='{{ link_url }}'>Open AI Insights</a></p>",
    ),
    (
        "recruitment.resume_analysis_ready",
        "de",
        "Lebenslauf-Analyse für {{ candidate_name }} ist fertig",
        "<p>Die KI-Analyse auf Basis des Lebenslaufs für "
        "<b>{{ candidate_name }}</b> ist abgeschlossen.</p>"
        "<p><a href='{{ link_url }}'>KI-Insights öffnen</a></p>",
    ),
    (
        "recruitment.resume_analysis_failed",
        "en",
        "Resume analysis failed for {{ candidate_name }}",
        "<p>The resume-only AI analysis for <b>{{ candidate_name }}</b> "
        "failed.</p>"
        "<p><a href='{{ link_url }}'>Open AI Insights to retry</a></p>",
    ),
    (
        "recruitment.resume_analysis_failed",
        "de",
        "Lebenslauf-Analyse für {{ candidate_name }} fehlgeschlagen",
        "<p>Die KI-Analyse auf Basis des Lebenslaufs für "
        "<b>{{ candidate_name }}</b> ist fehlgeschlagen.</p>"
        "<p><a href='{{ link_url }}'>KI-Insights öffnen und erneut "
        "versuchen</a></p>",
    ),
    (
        "recruitment.full_analysis_ready",
        "en",
        "Interview analysis ready for {{ candidate_name }}",
        "<p>The resume + interview AI analysis for "
        "<b>{{ candidate_name }}</b> is complete.</p>"
        "<p><a href='{{ link_url }}'>Open AI Insights</a></p>",
    ),
    (
        "recruitment.full_analysis_ready",
        "de",
        "Interview-Analyse für {{ candidate_name }} ist fertig",
        "<p>Die KI-Analyse aus Lebenslauf und Interview für "
        "<b>{{ candidate_name }}</b> ist abgeschlossen.</p>"
        "<p><a href='{{ link_url }}'>KI-Insights öffnen</a></p>",
    ),
    (
        "recruitment.full_analysis_failed",
        "en",
        "Interview analysis failed for {{ candidate_name }}",
        "<p>The resume + interview AI analysis for "
        "<b>{{ candidate_name }}</b> failed.</p>"
        "<p><a href='{{ link_url }}'>Open AI Insights to retry</a></p>",
    ),
    (
        "recruitment.full_analysis_failed",
        "de",
        "Interview-Analyse für {{ candidate_name }} fehlgeschlagen",
        "<p>Die KI-Analyse aus Lebenslauf und Interview für "
        "<b>{{ candidate_name }}</b> ist fehlgeschlagen.</p>"
        "<p><a href='{{ link_url }}'>KI-Insights öffnen und erneut "
        "versuchen</a></p>",
    ),
]


_UPSERT = sa.text(
    """
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
    """
)

# In-app rows reference the template by FK with no ON DELETE clause, so
# an installation that already sent one of these notices cannot drop the
# template row. Clear the children first — same order as
# ``hrp373evaltmpl01``.
_DELETE_NOTIFICATIONS = sa.text(
    """
    DELETE FROM notifications
    WHERE template_id IN (
        SELECT id FROM notification_templates
        WHERE code = :code AND locale = :locale
    )
    """
)

_DELETE = sa.text(
    "DELETE FROM notification_templates WHERE code = :code AND locale = :locale"
)


# (locale, old subject, old body, new subject, new body) for the legacy
# interview-analysis template.
LEGACY: list[tuple[str, str, str, str, str]] = [
    (
        "en",
        "AI analysis ready: {{ candidate_name }}",
        "<p>AI analysis of the interview with <b>{{ candidate_name }}</b> "
        "is complete.</p>",
        "AI analysis ready{% if candidate_name %}: {{ candidate_name }}{% endif %}",
        "<p>AI analysis of the interview{% if candidate_name %} with "
        "<b>{{ candidate_name }}</b>{% endif %} is complete.</p>",
    ),
    (
        "de",
        "KI-Analyse bereit: {{ candidate_name }}",
        "<p>Die KI-Analyse des Interviews mit <b>{{ candidate_name }}</b> "
        "ist abgeschlossen.</p>",
        "KI-Analyse bereit{% if candidate_name %}: {{ candidate_name }}{% endif %}",
        "<p>Die KI-Analyse des Interviews{% if candidate_name %} mit "
        "<b>{{ candidate_name }}</b>{% endif %} ist abgeschlossen.</p>",
    ),
]

_LEGACY_UPDATE = sa.text(
    """
    UPDATE notification_templates
    SET subject_template = :new_subject,
        body_template = :new_body,
        updated_at = now()
    WHERE code = 'recruitment.interview_analysis_ready'
      AND locale = :locale
      AND subject_template = :old_subject
      AND body_template = :old_body
    """
)


def _apply_legacy(*, forward: bool) -> None:
    conn = op.get_bind()
    for locale, old_subject, old_body, new_subject, new_body in LEGACY:
        params = (
            {
                "locale": locale,
                "old_subject": old_subject,
                "old_body": old_body,
                "new_subject": new_subject,
                "new_body": new_body,
            }
            if forward
            else {
                "locale": locale,
                "old_subject": new_subject,
                "old_body": new_body,
                "new_subject": old_subject,
                "new_body": old_body,
            }
        )
        conn.execute(_LEGACY_UPDATE, params)


def upgrade() -> None:
    conn = op.get_bind()
    for code, locale, subject, body in TEMPLATES:
        conn.execute(
            _UPSERT,
            {"code": code, "locale": locale, "subject": subject, "body": body},
        )
    _apply_legacy(forward=True)


def downgrade() -> None:
    conn = op.get_bind()
    _apply_legacy(forward=False)
    for code, locale, _subject, _body in TEMPLATES:
        conn.execute(_DELETE_NOTIFICATIONS, {"code": code, "locale": locale})
        conn.execute(_DELETE, {"code": code, "locale": locale})
