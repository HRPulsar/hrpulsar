"""HRP-177: vacancy archive + ETag versioning

Adds:
- ``vacancies.archived_at`` (nullable timestamp) — soft-delete marker.
- ``vacancies.archived_by`` (nullable user FK) — actor of the archive op.
- ``vacancies.version`` (int, default 1) — backing column for ``If-Match``
  ETag concurrency in PATCH ``/api/recruitment/vacancies/{id}``.

Revision ID: v1a1b2c3d4e5
Revises: tm4a1b2c3d4e5
Create Date: 2026-05-29 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v1a1b2c3d4e5"
down_revision: str | None = "tm4a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vacancies",
        sa.Column(
            "archived_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "vacancies",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_foreign_key(
        "fk_vacancies_archived_by_users",
        "vacancies",
        "users",
        ["archived_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_vacancies_archived_at",
        "vacancies",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vacancies_archived_at", table_name="vacancies")
    op.drop_constraint("fk_vacancies_archived_by_users", "vacancies", type_="foreignkey")
    op.drop_column("vacancies", "version")
    op.drop_column("vacancies", "archived_by")
    op.drop_column("vacancies", "archived_at")
