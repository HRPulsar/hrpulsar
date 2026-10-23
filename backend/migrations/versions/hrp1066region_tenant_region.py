"""HRP-1066: the company region, tenants.region

ISO 3166-1 alpha-2, upper case, nullable (NULL = not specified). It picks
regional reference sets such as the education levels on the employee
card; data residency is not driven by it.

Revision ID: hrp1066region
Revises: hrp714plansubject
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp1066region"
down_revision: str | Sequence[str] | None = "hrp714plansubject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("region", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "region")
