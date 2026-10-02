"""question_sets.generated_at; the no_allowed_processor session error code

Revision ID: hrp740genat01
Revises: v2merge07ar
Create Date: 2026-10-01 20:00:00.000000

HRP-740: the "Generated <date>" line read ``updated_at``, which HRP-471's
status-only writes (regenerating, settle, cancel) move too, so a cancelled
or failed regeneration re-dated questions that had not changed. The date
of the last generation gets its own column, stamped only when questions
land; existing rows take ``updated_at``, the best record they have.

HRP-1005: a competence generation or a process breakdown refused because
the workspace's processor list allows no AI provider ended as a generic
``service_error`` ("try later"). It gets its own session error code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp740genat01"
down_revision: str | Sequence[str] | None = "v2merge07ar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_CODES = (
    "'service_error', 'overload', 'insufficient_data', 'parse_error', "
    "'reaped_stuck', 'output_truncated'"
)
_NEW_CODES = _OLD_CODES + ", 'no_allowed_processor'"
_CHECKS = (
    ("ck_compgen_error_code", "competence_generation_sessions"),
    ("ck_workdecomp_error_code", "work_decomposition_sessions"),
)


def _set_codes(codes: str) -> None:
    for name, table in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name, table, f"error_code IS NULL OR error_code IN ({codes})"
        )


def upgrade() -> None:
    op.add_column(
        "question_sets",
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE question_sets SET generated_at = updated_at "
        "WHERE status IN ('ready', 'regenerating')"
    )
    _set_codes(_NEW_CODES)


def downgrade() -> None:
    for _, table in _CHECKS:
        op.execute(
            f"UPDATE {table} SET error_code = 'service_error' "
            "WHERE error_code = 'no_allowed_processor'"
        )
    _set_codes(_OLD_CODES)
    op.drop_column("question_sets", "generated_at")
