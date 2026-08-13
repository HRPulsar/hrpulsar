"""Replace the hardcoded product name in NotificationTemplate rows (HRP-515).

The ``invite`` template seeds bake "HRPulsar" into the email text — en
(``c3fc300775f8``), de (``hrp481detemplates01``) and, on the ee branch,
ru (``ee011rutemplates``) — the only rows in the whole seed history
carrying the literal. The render path now injects ``brand_name`` from
the installation settings (``notification/service.py::render_db_template``),
and this migration rewrites those rows to reference ``{{ brand_name }}``.

Scoped to ``code = 'invite'`` and guarded by the literal itself — the
``hrp518deproofread01`` convention: idempotent, skips rows an
installation customised into something else, and bumps ``updated_at`` so
the rewrite is visible to drift reconciliation. The ee branch repeats
the statement after its ru seed (``ee012brandtpl``) because the two
branches are unordered below ``c47fc6f13693`` — on a fresh database the
ru row may be seeded after this REPLACE ran. Seed migration history is
not edited; a ratchet test in ``test_i18n_coverage.py`` keeps future
seeds from reintroducing the literal. The stock brand default renders
byte-identical output.

Revision ID: hrp515brandtpl
Revises: hrp457adminmod
Create Date: 2026-08-11 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "hrp515brandtpl"
down_revision: str | None = "hrp457adminmod"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE notification_templates
        SET subject_template = REPLACE(subject_template, 'HRPulsar', '{{ brand_name }}'),
            body_template = REPLACE(body_template, 'HRPulsar', '{{ brand_name }}'),
            updated_at = now()
        WHERE code = 'invite'
          AND (subject_template LIKE '%HRPulsar%' OR body_template LIKE '%HRPulsar%')
        """)


def downgrade() -> None:
    op.execute("""
        UPDATE notification_templates
        SET subject_template = REPLACE(subject_template, '{{ brand_name }}', 'HRPulsar'),
            body_template = REPLACE(body_template, '{{ brand_name }}', 'HRPulsar'),
            updated_at = now()
        WHERE code = 'invite'
          AND (subject_template LIKE '%{{ brand_name }}%'
               OR body_template LIKE '%{{ brand_name }}%')
        """)
