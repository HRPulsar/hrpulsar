"""HRP-749: competence ↔ primitive links and ``competences.applicable_to``.

Second revision of the HRPulsar 2.0 chain (epic HRP-746). Additive:

* ``competences.applicable_to`` — ``human`` (default) | ``agent`` | ``both``.
  Existing rows are correct without a backfill: an HR competence describes
  a person. Read-only for clients in the MVP.
* ``competence_mapping_states`` — one row per mapped competence: who decided
  (``status``), the text fingerprint the mapping was derived from (a
  mismatch means "renamed since — re-map"), and the AI verdict metadata for
  the internal report. A rejected or empty mapping keeps its row with no
  links (decision 2026-09-09).
* ``competence_primitives`` — the pure N:M with a denormalised ``tenant_id``
  that mirrors ``competences.tenant_id`` (kept by the single writer,
  ``primitives.mapping_service``).

``primitive_id`` is ON DELETE RESTRICT on purpose: catalog rows are never
deleted, only retired. This is why ``v2prim01`` must be downgraded after
this revision.

Revision ID: v2prim02
Revises: v2prim01
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2prim02"
down_revision: str | Sequence[str] | None = "v2prim01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competences",
        sa.Column(
            "applicable_to",
            sa.String(length=10),
            server_default="human",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_competences_applicable_to",
        "competences",
        "applicable_to IN ('human', 'agent', 'both')",
    )

    op.create_table(
        "competence_mapping_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("competence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.String(length=1000), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column(
            "mapped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("competence_id", name="uq_compmap_competence"),
        sa.CheckConstraint(
            "status IN ('ai_suggested', 'reviewed', 'manual', 'rejected')",
            name="ck_compmap_status",
        ),
    )
    op.create_index(
        "ix_compmap_tenant_status",
        "competence_mapping_states",
        ["tenant_id", "status"],
    )

    op.create_table(
        "competence_primitives",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("competence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primitive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["primitive_id"], ["primitives.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competence_id", "primitive_id", name="uq_compprim_competence_primitive"
        ),
    )
    # Coverage walks primitive -> competences, so primitive_id leads.
    op.create_index(
        "ix_compprim_primitive_tenant",
        "competence_primitives",
        ["primitive_id", "tenant_id"],
    )
    op.create_index(
        "ix_compprim_tenant_competence",
        "competence_primitives",
        ["tenant_id", "competence_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_compprim_tenant_competence", table_name="competence_primitives")
    op.drop_index("ix_compprim_primitive_tenant", table_name="competence_primitives")
    op.drop_table("competence_primitives")
    op.drop_index("ix_compmap_tenant_status", table_name="competence_mapping_states")
    op.drop_table("competence_mapping_states")
    op.drop_constraint("ck_competences_applicable_to", "competences", type_="check")
    op.drop_column("competences", "applicable_to")
