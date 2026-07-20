"""Cascade assessment_answers.indicator_id and .answer_option_id through deletes.

Both FKs were created without an ``ON DELETE`` clause, defaulting to
``NO ACTION``. The demo purge wipes a tenant via the ``tenants``
``ON DELETE CASCADE`` chain; Postgres reaps ``indicators`` /
``answer_options`` and ``assessment_answers`` from the tenant root in an
unspecified order. When indicators or answer_options are deleted before
the answer rows that reference them, the non-cascading FKs block the
delete with a ``ForeignKeyViolation``.

The mirror semantic (deleting an indicator or answer option drops the
answers that pointed at it) is already used by ``AssessmentCalibratedTotal``
on the same target tables — bring AssessmentAnswer in line.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "assessanswfkcasc"
down_revision: str | None = "talentcandempcascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDICATOR_FK = "assessment_answers_indicator_id_fkey"
_OPTION_FK = "assessment_answers_answer_option_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_INDICATOR_FK, "assessment_answers", type_="foreignkey")
    op.create_foreign_key(
        _INDICATOR_FK,
        "assessment_answers",
        "indicators",
        ["indicator_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(_OPTION_FK, "assessment_answers", type_="foreignkey")
    op.create_foreign_key(
        _OPTION_FK,
        "assessment_answers",
        "answer_options",
        ["answer_option_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_OPTION_FK, "assessment_answers", type_="foreignkey")
    op.create_foreign_key(
        _OPTION_FK,
        "assessment_answers",
        "answer_options",
        ["answer_option_id"],
        ["id"],
    )

    op.drop_constraint(_INDICATOR_FK, "assessment_answers", type_="foreignkey")
    op.create_foreign_key(
        _INDICATOR_FK,
        "assessment_answers",
        "indicators",
        ["indicator_id"],
        ["id"],
    )
