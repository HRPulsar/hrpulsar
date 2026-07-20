"""Cascade talent_candidates.employee_id through employee deletion.

The ``talent_candidates.employee_id`` FK on ``employees.id`` was created
without an ``ON DELETE`` clause, so it defaults to ``NO ACTION``. The
demo purge (HRP-249 / D1) deletes a tenant row and relies on the
``tenants`` ``ON DELETE CASCADE`` chain to wipe every tenant-scoped
table, including ``employees`` and ``talent_candidates``. Postgres
cascades both children from ``tenants`` in an unspecified order, and
when ``employees`` rows are reaped before ``talent_candidates`` the
non-cascading FK blocks the delete with a ``ForeignKeyViolation``.

Surfaced in production by the celery-worker purge_expired_demo_tenants
task — every demo tenant with a seeded TalentCandidate failed to purge.

The mirror semantic — when an employee is deleted, drop any
TalentCandidate rows pointing at them — matches the rest of the
employee FK graph (see ``backend/app/modules/employee/models.py`` and
``assessment/exam`` models which already do CASCADE here).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "talentcandempcascade"
down_revision: str | None = "hrp272resumehash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FK_NAME = "talent_candidates_employee_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK_NAME, "talent_candidates", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "talent_candidates",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "talent_candidates", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "talent_candidates",
        "employees",
        ["employee_id"],
        ["id"],
    )
