"""Vacancy -> talent card link (HRP-667)

"Search inside before hiring outside" needs one fact the schema did not
carry: whether this requisition has already been posted to the internal
talent market. Without it the offer cannot tell "not posted yet" from
"posted", and a second press would mint a duplicate card.

The column lives on ``vacancies`` rather than a ``vacancy_id`` on
``talent_cards`` so the talent_market module stays unaware of
recruitment. ``ON DELETE SET NULL``: deleting the card puts the vacancy
back in the "offer to post" state instead of pointing at a missing row.

Revision ID: hrp667tmbridge
Revises: hrp623showgrades
Create Date: 2026-08-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "hrp667tmbridge"
down_revision: str | None = "hrp623showgrades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("talent_card_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_vacancies_talent_card_id", "vacancies", ["talent_card_id"]
    )
    op.create_foreign_key(
        "fk_vacancies_talent_card_id_talent_cards",
        "vacancies",
        "talent_cards",
        ["talent_card_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_vacancies_talent_card_id_talent_cards", "vacancies", type_="foreignkey"
    )
    op.drop_index("ix_vacancies_talent_card_id", table_name="vacancies")
    op.drop_column("vacancies", "talent_card_id")
