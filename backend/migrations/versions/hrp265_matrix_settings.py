"""HRP-265: per-tenant assessment matrix settings.

Adds ``tenants.recruitment_matrix_settings`` (JSONB) used by the
Assessments tab / Canvas to compute the Manager vs AI divergence flag
and the % match aggregates. Today the JSONB only carries the
``divergence_threshold`` float; HRP-206b/c will add toolbar defaults
(default view, paste-overwrite confirmation, etc.) into the same blob
so each new knob does not need a migration.

Revision ID: hrp265matrix
Revises: hrp204analyses
Create Date: 2026-06-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp265matrix"
down_revision: str | None = "hrp204analyses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "recruitment_matrix_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "recruitment_matrix_settings")
