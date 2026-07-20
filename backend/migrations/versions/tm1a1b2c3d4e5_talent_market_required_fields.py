"""HRP-87: Talent Market structured Requirements.

Adds the two fields the new Required Specialization / Required Competencies
blocks need so they can replace the free-text Requirements card:

* ``talent_card_specializations.min_experience_years`` — optional integer.
  Per the spec, a specialization row carries a minimum years-of-experience
  expectation alongside the (specialization, grade) pair.
* ``talent_card_competences.match_percent`` — optional 0–100 integer. The
  third step of the Required Competencies modal asks for the desired match
  threshold across the picked competences.

Both columns are nullable to make rolling deployments safe; the new UI
validates required values at submit time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm1a1b2c3d4e5"
down_revision: str | None = "pdp2a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "talent_card_specializations",
        sa.Column("min_experience_years", sa.Integer(), nullable=True),
    )
    op.add_column(
        "talent_card_competences",
        sa.Column("match_percent", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("talent_card_competences", "match_percent")
    op.drop_column("talent_card_specializations", "min_experience_years")
