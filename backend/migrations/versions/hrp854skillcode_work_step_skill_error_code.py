"""work_step_skills.error_code: the machine-readable cause of a failure.

The row's ``error_message`` is a fixed English string (HRP-854); the
code lets the reader's locale render the text, and rows written before
this column keep falling back to the stored message. The decomposition
sessions' check constraint grows the billing refusal codes for the same
reason: the 402 path records why the run never started.

Revision ID: hrp854skillcode
Revises: hrp1042dropemb
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp854skillcode"
down_revision: str | Sequence[str] | None = "hrp1042dropemb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CODES = (
    "'service_error', 'overload', 'insufficient_data', 'parse_error', "
    "'reaped_stuck', 'output_truncated', 'no_allowed_processor'"
)
_NEW_CODES = _OLD_CODES + ", 'credits_limit_reached', 'credits_demo_quota_exhausted'"


def _set_codes(codes: str) -> None:
    op.drop_constraint(
        "ck_workdecomp_error_code", "work_decomposition_sessions", type_="check"
    )
    op.create_check_constraint(
        "ck_workdecomp_error_code",
        "work_decomposition_sessions",
        f"error_code IS NULL OR error_code IN ({codes})",
    )


def upgrade() -> None:
    op.add_column(
        "work_step_skills",
        sa.Column("error_code", sa.String(length=40), nullable=True),
    )
    _set_codes(_NEW_CODES)


def downgrade() -> None:
    op.execute(
        "UPDATE work_decomposition_sessions SET error_code = 'service_error' "
        "WHERE error_code IN ('credits_limit_reached', 'credits_demo_quota_exhausted')"
    )
    _set_codes(_OLD_CODES)
    op.drop_column("work_step_skills", "error_code")
