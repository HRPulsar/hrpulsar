"""HRP-801 (QA 12.11): a hire need opened "look inside first" is a talent
card of its own, with no vacancy behind it - ``work_hire_needs.talent_card_id``.

Nullable, ``ON DELETE SET NULL``: a card deleted in the talent market drops
the need off the screen, the way a deleted vacancy does. A need carries the
card or the vacancy; ``vacancy_id`` stays as it is. Additive only.

Revision ID: hrp801needcard
Revises: hrp1066region
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "hrp801needcard"
down_revision: str | Sequence[str] | None = "hrp1066region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_hire_needs",
        sa.Column(
            "talent_card_id",
            UUID(as_uuid=True),
            sa.ForeignKey("talent_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_work_hire_needs_talent_card", "work_hire_needs", ["talent_card_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_work_hire_needs_talent_card", table_name="work_hire_needs")
    op.drop_column("work_hire_needs", "talent_card_id")
