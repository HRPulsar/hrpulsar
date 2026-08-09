"""Deep links in question-set notifications (HRP-442, HRP-460).

"Interview questions ready" told the recruiter a set existed but gave no
way to reach it; the failure notice likewise said "open the candidate
page" without linking there. Both templates gain a click-through to the
candidate card, anchored on the Interview questions block and — for the
ready notice — with the generated set preselected.

``{{ link_url }}`` is supplied by the notification dispatcher, which
prefixes the payload's relative ``link`` with FRONTEND_URL.

Every UPDATE is guarded by the currently seeded body, so the migration
is idempotent and skips rows an installation has customized.
``downgrade`` restores the linkless bodies under the same guard.

Revision ID: hrp442qslinks01
Revises: hrp486qenums01
Create Date: 2026-08-05 17:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp442qslinks01"
down_revision: str | None = "hrp486qenums01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, locale, body without link, body with link)
BODIES: list[tuple[str, str, str, str]] = [
    (
        "recruitment.question_set_ready",
        "en",
        "<p>A new interview question set for <b>{{ candidate_name }}</b> is ready to review.</p>",
        "<p>A new interview question set for <b>{{ candidate_name }}</b> is ready to review.</p>"
        "<p><a href='{{ link_url }}'>Open question set</a></p>",
    ),
    (
        "recruitment.question_set_failed",
        "en",
        "<p>AI question generation for <b>{{ candidate_name }}</b> failed. Open the candidate page to retry.</p>",
        "<p>AI question generation for <b>{{ candidate_name }}</b> failed.</p>"
        "<p><a href='{{ link_url }}'>Open candidate page to retry</a></p>",
    ),
    (
        "recruitment.question_set_ready",
        "de",
        "<p>Ein neues Fragenset für das Interview mit <b>{{ candidate_name }}</b> steht zur Überprüfung bereit.</p>",
        "<p>Ein neues Fragenset für das Interview mit <b>{{ candidate_name }}</b> steht zur Überprüfung bereit.</p>"
        "<p><a href='{{ link_url }}'>Fragenset öffnen</a></p>",
    ),
    (
        "recruitment.question_set_failed",
        "de",
        "<p>Die KI-Fragengenerierung für <b>{{ candidate_name }}</b> ist fehlgeschlagen. Öffnen Sie die Kandidatenseite, um es erneut zu versuchen.</p>",
        "<p>Die KI-Fragengenerierung für <b>{{ candidate_name }}</b> ist fehlgeschlagen.</p>"
        "<p><a href='{{ link_url }}'>Kandidatenseite öffnen und erneut versuchen</a></p>",
    ),
]


def _apply(pairs: list[tuple[str, str, str, str]], *, forward: bool) -> None:
    conn = op.get_bind()
    for code, locale, without, with_link in pairs:
        old, new = (without, with_link) if forward else (with_link, without)
        conn.execute(
            sa.text(
                "UPDATE notification_templates SET body_template = :new, "
                "updated_at = now() "
                "WHERE code = :code AND locale = :locale AND body_template = :old"
            ),
            {"new": new, "old": old, "code": code, "locale": locale},
        )


def upgrade() -> None:
    _apply(BODIES, forward=True)


def downgrade() -> None:
    _apply(BODIES, forward=False)
