"""i18n F6 (HRP-480): drop the content_language CHECK constraint.

``tenant_ai_settings.content_language`` was pinned to ``'en'`` by a DB
CHECK. Allowed values are now governed by the ``ContentLanguage``
Literal in ``ai_settings/schemas.py`` (en, de as of HRP-480), so adding
a language is a code change, not a migration.

Downgrade resets non-English rows back to ``'en'`` before re-creating
the original CHECK — otherwise the constraint could not be applied.

Revision ID: hrp480ailang01
Revises: hrp479refdata01
Create Date: 2026-07-30 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "hrp480ailang01"
down_revision: str | None = "hrp479refdata01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_tenant_ai_settings_content_language",
        "tenant_ai_settings",
        type_="check",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_ai_settings SET content_language = 'en' "
        "WHERE content_language <> 'en'"
    )
    op.create_check_constraint(
        "ck_tenant_ai_settings_content_language",
        "tenant_ai_settings",
        "content_language IN ('en')",
    )
