"""Merge HRP-274 + HRP-285 heads after pack-rec/pack-dict merges

Revision ID: 501b10d2b6f1
Revises: hrp274ainormalized, hrp285dictoverride
Create Date: 2026-06-30 20:48:11.812869
"""
from collections.abc import Sequence

revision: str = '501b10d2b6f1'
down_revision: tuple[str, str] = ('hrp274ainormalized', 'hrp285dictoverride')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
