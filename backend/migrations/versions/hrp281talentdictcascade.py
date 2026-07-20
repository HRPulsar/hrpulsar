"""HRP-281: cascade Talent Market FKs through tenant deletion.

The talent_market relation tables FK at ``dictionary_items.id``,
``competences.id`` and ``skill_levels.id`` with no ``ON DELETE`` clause.
When a tenant is deleted Postgres cascades those rows via their
``tenant_id`` cascade, but the ``RESTRICT`` default on the talent
relations blocks the cascade and the tenant delete fails with a
foreign-key violation.

Switches the FKs to mirror the deletion semantics that were already
obvious from the cascade graph:

* TalentCardSpecialization.specialization_id (NOT NULL) → CASCADE
* TalentCardSpecialization.grade_id (nullable) → SET NULL
* TalentCardCompetence.competence_id (NOT NULL) → CASCADE
* TalentCardCompetence.skill_level_id (nullable) → SET NULL

Surfaced by the HRP-281 demo seed, which is the first piece of code
that seeds talent_market relations against tenant-scoped reference
rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "hrp281talentdictcascade"
down_revision: str | None = "hrp260drop_waitlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FK_PAIRS = (
    (
        "talent_card_specializations_specialization_id_fkey",
        "talent_card_specializations",
        "dictionary_items",
        "specialization_id",
        "CASCADE",
    ),
    (
        "talent_card_specializations_grade_id_fkey",
        "talent_card_specializations",
        "dictionary_items",
        "grade_id",
        "SET NULL",
    ),
    (
        "talent_card_competences_competence_id_fkey",
        "talent_card_competences",
        "competences",
        "competence_id",
        "CASCADE",
    ),
    (
        "talent_card_competences_skill_level_id_fkey",
        "talent_card_competences",
        "skill_levels",
        "skill_level_id",
        "SET NULL",
    ),
    (
        "assessment_results_competence_id_fkey",
        "assessment_results",
        "competences",
        "competence_id",
        "CASCADE",
    ),
)


def upgrade() -> None:
    for fk_name, src_table, dst_table, col, ondelete in _FK_PAIRS:
        op.drop_constraint(fk_name, src_table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            src_table,
            dst_table,
            [col],
            ["id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    for fk_name, src_table, dst_table, col, _ondelete in _FK_PAIRS:
        op.drop_constraint(fk_name, src_table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            src_table,
            dst_table,
            [col],
            ["id"],
        )
