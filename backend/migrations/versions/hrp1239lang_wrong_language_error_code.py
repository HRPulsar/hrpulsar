"""work_decomposition_sessions: the wrong_language error code.

HRP-1239: a breakdown whose steps came back in a language other than the
content language - and again on the one retry - ends as a failed
generation. It gets its own session error code, so the reader's locale
says what happened instead of a generic failure.

Revision ID: hrp1239lang
Revises: hrp1197executors
Create Date: 2026-11-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp1239lang"
down_revision: str | Sequence[str] | None = "hrp1197executors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CODES = (
    "'service_error', 'overload', 'insufficient_data', 'parse_error', "
    "'reaped_stuck', 'output_truncated', 'no_allowed_processor', "
    "'credits_limit_reached', 'credits_demo_quota_exhausted'"
)
_NEW_CODES = _OLD_CODES + ", 'wrong_language'"


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
    _set_codes(_NEW_CODES)


def downgrade() -> None:
    op.execute(
        "UPDATE work_decomposition_sessions SET error_code = 'service_error' "
        "WHERE error_code = 'wrong_language'"
    )
    _set_codes(_OLD_CODES)
