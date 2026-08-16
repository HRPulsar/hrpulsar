"""HRP-570: drop the 'RUB' server_default on grade_specializations.salary_currency

``pos1a1b2c3d4e5`` created the column with ``server_default='RUB'``. After
HRP-439 the currency of HR money fields follows the installation (the
effective billing profile, falling back to ``BILLING_CURRENCY``), so a DDL
literal is wrong on every site that is not Russian: any row inserted
outside the application path — raw SQL, a future migration backfill —
would silently land in RUB.

Removing the default rather than swapping one literal for another: the
column stays NOT NULL, so a writer that supplies no currency now fails
loudly instead of inventing one. Every application path already supplies
a value (the ORM default and the Pydantic schema default both call
``installation_currency()``), so nothing in the product changes.

No backfill: existing rows were all written through the application path
and already carry that installation's currency. Rewriting them from a
migration would be the very thing this ticket removes — a blind literal
applied to data the migration cannot judge.

Revision ID: hrp570salcur
Revises: hrp567slackchan
Create Date: 2026-08-14 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp570salcur"
down_revision: str | None = "hrp567slackchan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "grade_specializations",
        "salary_currency",
        existing_type=sa.String(length=3),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.alter_column(
        "grade_specializations",
        "salary_currency",
        existing_type=sa.String(length=3),
        existing_nullable=False,
        server_default="RUB",
    )
