"""HRP-419: re-seed the "Interview scheduled" notification template.

The old copy never mentioned the vacancy the candidate is being considered
for. Both locales get a new body; the subject is unchanged, so only
``body_template`` is touched.

Every UPDATE is guarded by the currently seeded body (en came from
``r4c1b2c3d4e5``, de from ``hrp481detemplates01``): an installation that
customized this template keeps its own copy instead of having it silently
overwritten, and a re-run is a no-op. ``downgrade`` restores the old bodies
under the same guard.

Revision ID: hrp419ivmail01
Revises: hrp418ivarchive01
Create Date: 2026-08-07 10:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp419ivmail01"
down_revision: str | None = "hrp418ivarchive01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "recruitment.interview_scheduled"

# locale -> (previously seeded body, body with the vacancy title)
BODIES: dict[str, tuple[str, str]] = {
    "en": (
        "<p>You are assigned to interview <b>{{ candidate_name }}</b>"
        "{% if interview_date %} on {{ interview_date }}{% endif %}.</p>",
        "<p>You are assigned to interview <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} for the <b>{{ vacancy_title }}</b> position"
        "{% endif %}{% if interview_date %} on {{ interview_date }}{% endif %}.</p>",
    ),
    "de": (
        "<p>Sie wurden für das Interview mit <b>{{ candidate_name }}</b>"
        "{% if interview_date %} am {{ interview_date }}{% endif %} eingeteilt.</p>",
        "<p>Sie wurden für das Interview mit <b>{{ candidate_name }}</b>"
        "{% if vacancy_title %} für die Stelle <b>{{ vacancy_title }}</b>"
        "{% endif %}{% if interview_date %} am {{ interview_date }}"
        "{% endif %} eingeteilt.</p>",
    ),
}

_GUARDED_UPDATE = sa.text("""
    UPDATE notification_templates
       SET body_template = :new, updated_at = now()
     WHERE code = :code AND locale = :locale AND body_template = :old
""")


def _apply(*, forward: bool) -> None:
    conn = op.get_bind()
    for locale, (old_body, new_body) in BODIES.items():
        old, new = (old_body, new_body) if forward else (new_body, old_body)
        conn.execute(
            _GUARDED_UPDATE,
            {"code": _CODE, "locale": locale, "old": old, "new": new},
        )


def upgrade() -> None:
    _apply(forward=True)


def downgrade() -> None:
    _apply(forward=False)
