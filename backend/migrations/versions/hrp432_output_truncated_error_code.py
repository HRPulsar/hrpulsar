"""HRP-432: extend compgen error_code list with `output_truncated`

Revision ID: hrp432trunc01
Revises: hrp358invconsent
Create Date: 2026-07-23 12:00:00.000000

Tree-scope generations that overflow the per-model output-token ceiling
now fail fast with a dedicated error_code instead of masquerading as a
generic `service_error` ("AI service temporarily unavailable") after five
identical retries.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp432trunc01"
down_revision: str | None = "hrp358invconsent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD = (
    "error_code IS NULL OR error_code IN "
    "('service_error','overload','insufficient_data','parse_error','reaped_stuck')"
)
_NEW = (
    "error_code IS NULL OR error_code IN "
    "('service_error','overload','insufficient_data','parse_error','reaped_stuck',"
    "'output_truncated')"
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
        "SET error_code = 'service_error' WHERE error_code = 'output_truncated'"
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
