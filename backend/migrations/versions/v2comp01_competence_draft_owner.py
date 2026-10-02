"""HRP-632: a division head's personal competence draft.

``competences.draft_owner_id`` names the manager whose draft a competence
is - set only on a draft a division head adds, cleared when HR or an admin
publishes it. Such a draft is seen by its author and by ``manage`` alone,
and offered by no picker until it is published. Everything the catalogue
held before stays ownerless and behaves as it did.

Revision ID: v2comp01
Revises: v2merge06ar
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2comp01"
down_revision: str | Sequence[str] | None = "v2merge06ar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competences",
        sa.Column(
            "draft_owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_competences_draft_owner_id", "competences", ["draft_owner_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_competences_draft_owner_id", table_name="competences")
    op.drop_column("competences", "draft_owner_id")
