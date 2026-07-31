"""i18n F4 (HRP-478): per-locale NotificationTemplate rows.

Adds ``locale`` to ``notification_templates`` and widens the uniqueness
contract from ``code`` to ``(code, locale)``. Every existing template row
becomes the ``en`` row; a ``de`` row is seeded per code as an English
copy (the same convention as ``app/i18n/de.json`` — F7/HRP-481 replaces
the copies with real German). Rendering picks the recipient-locale row
and falls back to ``en``, so the seed is behaviour-neutral until then.

NOTE for future template seeds: the old code-only unique constraint is
gone, so a conflict target of just the code column (the pattern of the
pre-F4 seed migrations) now raises. Migrations ordered after this one
must target ``(code, locale)`` — guarded by a scan test in
tests/unit/test_i18n_coverage.py.

Revision ID: hrp478emaildb01
Revises: hrp474locale01
Create Date: 2026-07-29 17:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp478emaildb01"
down_revision: str | None = "hrp474locale01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_templates",
        sa.Column("locale", sa.String(length=10), server_default="en", nullable=False),
    )
    op.drop_constraint(
        "notification_templates_code_key", "notification_templates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_notification_templates_code_locale",
        "notification_templates",
        ["code", "locale"],
    )
    # Seed a de row per en template. Idempotent (NOT EXISTS) so a rerun
    # after a partial failure — or a template added by a later hotfix
    # migration ordered before this one — never violates the unique key.
    op.execute("""
        INSERT INTO notification_templates
            (id, code, locale, subject_template, body_template,
             notification_type, created_at, updated_at)
        SELECT gen_random_uuid(), t.code, 'de', t.subject_template,
               t.body_template, t.notification_type, now(), now()
        FROM notification_templates t
        WHERE t.locale = 'en'
          AND NOT EXISTS (
              SELECT 1 FROM notification_templates d
              WHERE d.code = t.code AND d.locale = 'de'
          )
    """)


def downgrade() -> None:
    # In-app notifications may reference a non-en template row; repoint
    # them at the en sibling before deleting so the FK survives. Only
    # rows WITH an en sibling are deleted — a locale-specific code with
    # no en row (possible after F7) stays, keeping its FK intact and the
    # restored code-only uniqueness valid.
    op.execute("""
        UPDATE notifications n
        SET template_id = en.id
        FROM notification_templates loc
        JOIN notification_templates en
          ON en.code = loc.code AND en.locale = 'en'
        WHERE n.template_id = loc.id AND loc.locale <> 'en'
    """)
    op.execute("""
        DELETE FROM notification_templates loc
        WHERE loc.locale <> 'en'
          AND EXISTS (
              SELECT 1 FROM notification_templates en
              WHERE en.code = loc.code AND en.locale = 'en'
          )
    """)
    op.drop_constraint(
        "uq_notification_templates_code_locale",
        "notification_templates",
        type_="unique",
    )
    op.create_unique_constraint(
        "notification_templates_code_key", "notification_templates", ["code"]
    )
    op.drop_column("notification_templates", "locale")
