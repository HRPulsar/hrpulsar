"""HRP-163: extend compgen error_code list with `reaped_stuck`

Revision ID: hrp163reap001
Revises: 6162d7ab9e32
Create Date: 2026-05-23 12:00:00.000000

The reap-stuck-sessions beat job needs a distinct error_code so the UI
and ops dashboards can separate "the LLM call legitimately failed" from
"the worker died and we marked the row as error to unblock the user".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp163reap001"
down_revision: str | None = "6162d7ab9e32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD = (
    "error_code IS NULL OR error_code IN "
    "('service_error','overload','insufficient_data','parse_error')"
)
_NEW = (
    "error_code IS NULL OR error_code IN "
    "('service_error','overload','insufficient_data','parse_error','reaped_stuck')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_compgen_error_code",
        "competence_generation_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_compgen_error_code",
        "competence_generation_sessions",
        _NEW,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE competence_generation_sessions "
        "SET error_code = 'service_error' WHERE error_code = 'reaped_stuck'"
    )
    op.drop_constraint(
        "ck_compgen_error_code",
        "competence_generation_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_compgen_error_code",
        "competence_generation_sessions",
        _OLD,
    )
