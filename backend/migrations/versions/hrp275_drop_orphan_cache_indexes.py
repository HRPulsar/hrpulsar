"""HRP-275: drop orphan indexes left by the in-place edit of HRP-252.

The original ``hrp252cache`` migration (commit 0646286) created two
btree indexes on ``interview_analysis_cache``:

* ``ix_interview_analysis_cache_tenant_id``
* ``ix_interview_analysis_cache_cache_key``

A subsequent chore commit (0beec75) removed those ``op.create_index``
calls from the migration in place, but environments that had already
applied the original revision still carry the indexes, and the
downgrade path no longer drops them either. Use ``IF EXISTS`` so the
follow-up is a no-op on databases that never saw the original.

Revision ID: hrp275dropcacheidx
Revises: hrp281talentdictcascade
Create Date: 2026-06-18 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "hrp275dropcacheidx"
down_revision: str | None = "hrp281talentdictcascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_interview_analysis_cache_tenant_id"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_interview_analysis_cache_cache_key"
    )


def downgrade() -> None:
    # Recreating the orphan indexes is not useful — the
    # (tenant_id, cache_key) UNIQUE btree already covers every lookup.
    pass
