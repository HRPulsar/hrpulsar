"""HRP-748: primitive catalog — reference table and the v1.1 seed.

First revision of the HRPulsar 2.0 chain (epic HRP-746). Creates the
platform-wide ``primitives`` reference (no tenant scope) and seeds the 17
codes of catalog v1.1 from ``app.modules.primitives.catalog_data`` with
``INSERT ... ON CONFLICT (code) DO NOTHING`` — a re-run never rewrites a row
a later revision may have retired or revised.

Downgrade order across the chain is strict: ``competence_primitives``
(``v2prim02``, ON DELETE RESTRICT) and ``work_step_primitives`` reference
this table, so this revision must be downgraded last —
``v2work02 -> v2work01 -> v2agnt01 -> v2prim02 -> v2prim01``.

Revision ID: v2prim01
Revises: hrp714tmreactiongap
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2prim01"
down_revision: str | Sequence[str] | None = "hrp714tmreactiongap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "primitives",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ai_verdict", sa.String(length=20), nullable=False),
        sa.Column("ai_as_of", sa.Date(), nullable=False),
        sa.Column("ai_basis", sa.String(length=50), nullable=False),
        sa.Column("title_en", sa.String(length=300), nullable=False),
        sa.Column("scope_en", sa.String(length=600), nullable=True),
        sa.Column("i18n_key", sa.String(length=100), nullable=False),
        sa.Column("sort_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("introduced_in", sa.String(length=20), nullable=False),
        sa.Column("retired_in", sa.String(length=20), nullable=True),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.UniqueConstraint("code", name="uq_primitives_code"),
        sa.UniqueConstraint("i18n_key", name="uq_primitives_i18n_key"),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["primitives.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "kind IN ('cognitive', 'boundary')", name="ck_primitives_kind"
        ),
        sa.CheckConstraint(
            "ai_verdict IN ('strong', 'better_than_human', 'draft', 'no')",
            name="ck_primitives_ai_verdict",
        ),
    )
    op.create_index("ix_primitives_kind", "primitives", ["kind"])

    # The seed list is the committed English rendering of the catalog YAML
    # (docs/ is not in the public tree). The import stays local because
    # graph-only commands (``alembic history`` / ``heads``) load revision
    # modules without running ``env.py``, which is what puts the app package
    # on the path. A later catalog edit is caught by the golden hash in
    # test_primitive_catalog_seed.py, which demands a follow-up data
    # migration rather than a silent change of what a fresh install seeds.
    from app.modules.primitives.catalog_data import seed_insert

    op.get_bind().execute(seed_insert())


def downgrade() -> None:
    op.drop_index("ix_primitives_kind", table_name="primitives")
    op.drop_table("primitives")
