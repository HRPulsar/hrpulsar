"""Tenant branding set by the platform admin (HRP-808)

White-label sites brand the whole installation via env. These columns let
one tenant replace the site logo with its own, hide the version badge, and
pick a theme preset / accent color on top of the site's branding. Plain
columns: the admin form edits them one by one and /auth/me reads them on
every load.

Revision ID: hrp808branding
Revises: hrp781stagei18n01
Create Date: 2026-09-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp808branding"
down_revision: str | None = "hrp781stagei18n01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "hide_platform_logo", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "hide_app_version", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column("tenants", sa.Column("brand_theme", sa.String(32), nullable=True))
    op.add_column(
        "tenants", sa.Column("brand_accent_color", sa.String(7), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenants", "brand_accent_color")
    op.drop_column("tenants", "brand_theme")
    op.drop_column("tenants", "hide_app_version")
    op.drop_column("tenants", "hide_platform_logo")
