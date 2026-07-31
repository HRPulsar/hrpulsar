"""German notification template proofread fixes (HRP-518).

Post-release native-style proofread of the de rows seeded by
``hrp481detemplates01``. That seed is already applied in production, so
the fixes ship as a new data migration instead of editing the seed.
Every UPDATE is guarded by the seeded value: the migration is idempotent
and skips rows an installation has customized since seeding.
``downgrade`` restores the seeded strings under the same guard.

Revision ID: hrp518deproofread01
Revises: hrp481detemplates01
Create Date: 2026-07-31 12:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp518deproofread01"
down_revision: str | None = "hrp481detemplates01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, column, seeded value, corrected value)
FIXES: list[tuple[str, str, str, str]] = [
    (
        "employee_terminated",
        "body_template",
        "<p>Hallo {{ employee_name }},</p><p>Ihr Arbeitsverhältnis wurde als <b>ausgeschieden</b> markiert. Sie haben keinen Zugriff mehr auf das System.</p><p>Sollte dies ein Fehler sein, wenden Sie sich an Ihren Administrator.</p>",
        "<p>Hallo {{ employee_name }},</p><p>Ihr Status wurde auf <b>ausgeschieden</b> gesetzt. Sie haben keinen Zugriff mehr auf das System.</p><p>Sollte dies ein Fehler sein, wenden Sie sich an Ihren Administrator.</p>",
    ),
    (
        "exam.assigned",
        "body_template",
        "<p>Hallo {{ recipient_name }},</p><p>Sie wurden der Prüfung <b>{{ exam_title }}</b> zugewiesen.</p><p>Frist: {{ deadline }}</p>",
        "<p>Hallo {{ recipient_name }},</p><p>Ihnen wurde die Prüfung <b>{{ exam_title }}</b> zugewiesen.</p><p>Frist: {{ deadline }}</p>",
    ),
    (
        "recruitment.vacancy_assigned",
        "body_template",
        "<p>Sie wurden als Verantwortlicher der Stelle <b>{{ vacancy_title }}</b> zugewiesen.</p>",
        "<p>Sie wurden als Verantwortlicher für die Stelle <b>{{ vacancy_title }}</b> benannt.</p>",
    ),
    (
        "recruitment.invite_completed",
        "subject_template",
        "Bewertung abgegeben von {{ evaluator_name }}",
        "Bewertung von {{ evaluator_name }} abgegeben",
    ),
]

_UPDATE: dict[str, sa.TextClause] = {
    column: sa.text(
        f"UPDATE notification_templates SET {column} = :new, updated_at = now() "
        f"WHERE code = :code AND locale = 'de' AND {column} = :old"
    )
    for column in ("subject_template", "body_template")
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, column, old, new in FIXES:
        conn.execute(_UPDATE[column], {"code": code, "old": old, "new": new})


def downgrade() -> None:
    conn = op.get_bind()
    for code, column, old, new in FIXES:
        conn.execute(_UPDATE[column], {"code": code, "old": new, "new": old})
