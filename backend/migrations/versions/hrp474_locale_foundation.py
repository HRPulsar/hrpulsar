"""i18n F0: per-user language + tenant default locale

Revision ID: hrp474locale01
Revises: hrp432trunc01
Create Date: 2026-07-28 12:00:00.000000

Locale foundation for the i18n epic (HRP-473). Adds the two DB pieces of
the interface-locale resolution chain (user > tenant > Accept-Language >
deployment DEFAULT_LOCALE): ``users.language`` — personal interface
locale, and ``tenants.default_locale`` — tenant-wide default chosen on
the onboarding "Language" step. Both nullable: NULL means "inherit the
next level", so no backfill is needed and deployment-default changes
keep propagating to users who never made an explicit choice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp474locale01"
down_revision: str | None = "hrp432trunc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("default_locale", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "default_locale")
    op.drop_column("users", "language")
