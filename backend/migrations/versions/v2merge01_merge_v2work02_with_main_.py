"""Merge of the HRPulsar 2.0 chain (``v2work02``) with main
(``hrp379submittpl01``, v1.23.1). No schema change: the two lines were
developed in parallel and this revision joins them so the tree has one
head again (risk R8 of the execution plan).

Revision ID: v2merge01
Revises: v2work02, hrp379submittpl01
Create Date: 2026-09-09

"""

from collections.abc import Sequence

revision: str = "v2merge01"
down_revision: str | Sequence[str] | None = ("v2work02", "hrp379submittpl01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
