"""GDPR erasure leaves nothing behind in storage or the analysis cache

Revision ID: rf3e_gdpr_blob_cleanup
Revises: rf3d_pc_dictated
Create Date: 2026-10-05 12:00:00.000000

* ``gdpr_pending_blob_deletes`` - object-storage keys an erasure or the
  retention sweep could not delete; the nightly sweep retries them.
* ``interview_analysis_cache.candidate_vacancy_id`` - the pair a cache row
  was computed for, so an erasure removes stale rows too. Existing rows
  stay NULL: the key is a hash and cannot be traced back.

Additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "rf3e_gdpr_blob_cleanup"
down_revision: str | Sequence[str] | None = "rf3d_pc_dictated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PENDING = "gdpr_pending_blob_deletes"
CACHE = "interview_analysis_cache"


def upgrade() -> None:
    op.create_table(
        PENDING,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=600), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{PENDING}_tenant_id", PENDING, ["tenant_id"])

    op.add_column(
        CACHE,
        sa.Column("candidate_vacancy_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        f"{CACHE}_candidate_vacancy_id_fkey",
        CACHE,
        "candidate_vacancies",
        ["candidate_vacancy_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(f"ix_{CACHE}_candidate_vacancy_id", CACHE, ["candidate_vacancy_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{CACHE}_candidate_vacancy_id", table_name=CACHE)
    op.drop_constraint(f"{CACHE}_candidate_vacancy_id_fkey", CACHE, type_="foreignkey")
    op.drop_column(CACHE, "candidate_vacancy_id")
    op.drop_index(f"ix_{PENDING}_tenant_id", table_name=PENDING)
    op.drop_table(PENDING)
