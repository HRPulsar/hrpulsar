"""HRP-954: embeddings belong to a tenant.

``/api/ai/search`` read every tenant's rows and ``/api/ai/embed`` upserted
on ``(entity_type, entity_id)`` across tenants. Add ``tenant_id``, backfill
it from the entity the row describes, drop the rows that cannot be
attributed (derived data - the next embed recreates them), then lock it
down: NOT NULL, FK, index and uniqueness per tenant.

Revision ID: v2work12
Revises: v2work11
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work12"
down_revision: str | Sequence[str] | None = "v2work11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# entity_type -> table whose ``id`` the row's ``entity_id`` points at.
# Nothing in the code writes embeddings; these are the entity kinds an
# admin could have embedded by hand through ``/api/ai/embed``.
BACKFILL_SOURCES = {
    "competence": "competences",
    "indicator": "indicators",
    "position": "positions",
    "employee": "employees",
    "vacancy": "vacancies",
    "candidate": "candidates",
    "talent_card": "talent_cards",
}

# Same shape as v2work13's DEDUPE_SQL. The old select-then-insert writers
# raced exactly like record_answer did, so one key may hold two rows; the
# latest by (updated_at, id) survives and the unique below then holds.
DEDUPE_SQL = """
DELETE FROM embeddings a
USING embeddings b
WHERE a.tenant_id = b.tenant_id
  AND a.entity_type = b.entity_type
  AND a.entity_id = b.entity_id
  AND (a.updated_at, a.id) < (b.updated_at, b.id)
"""


def upgrade() -> None:
    op.add_column("embeddings", sa.Column("tenant_id", sa.UUID(), nullable=True))
    for entity_type, table in BACKFILL_SOURCES.items():
        op.execute(
            f"UPDATE embeddings e SET tenant_id = s.tenant_id FROM {table} s "
            f"WHERE e.entity_type = '{entity_type}' AND e.entity_id = s.id "
            "AND s.tenant_id IS NOT NULL"
        )
    op.execute("DELETE FROM embeddings WHERE tenant_id IS NULL")
    op.execute(DEDUPE_SQL)
    op.alter_column("embeddings", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_embeddings_tenant_id_tenants",
        "embeddings",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_embeddings_tenant_id"), "embeddings", ["tenant_id"])
    op.create_unique_constraint(
        "uq_embeddings_tenant_entity",
        "embeddings",
        ["tenant_id", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_embeddings_tenant_entity", "embeddings", type_="unique")
    op.drop_index(op.f("ix_embeddings_tenant_id"), table_name="embeddings")
    op.drop_constraint(
        "fk_embeddings_tenant_id_tenants", "embeddings", type_="foreignkey"
    )
    op.drop_column("embeddings", "tenant_id")
