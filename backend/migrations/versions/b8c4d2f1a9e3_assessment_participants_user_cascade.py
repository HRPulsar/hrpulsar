"""assessment_participants user_id ON DELETE CASCADE + clean orphans

Revision ID: b8c4d2f1a9e3
Revises: a4d8e3f1c2b9
Create Date: 2026-04-28 19:00:00.000000

Background: on 2026-04-22 production logged 3x ForeignKeyViolationError on
add_participant where the resolved Employee.user_id pointed at a user
row that no longer existed. The original FK on
assessment_participants.user_id had no ON DELETE rule, so deleting a
user without first removing their participations would (a) fail with
FK violation if attempted directly, or (b) leave dangling Employee.user_id
pointers if the user was removed via some other path. Either way, the
next add_participant call for the same employee fails.

This migration:
  1. Drops orphaned assessment_participants rows whose user_id is no
     longer in the users table (so the new FK can be added cleanly).
  2. Recreates the FK with ON DELETE CASCADE, so future user deletions
     remove their participations atomically.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8c4d2f1a9e3"
down_revision: str | None = "a4d8e3f1c2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM assessment_participants
        WHERE user_id IS NOT NULL
          AND user_id NOT IN (SELECT id FROM users)
        """)
    op.drop_constraint(
        "assessment_participants_user_id_fkey",
        "assessment_participants",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "assessment_participants_user_id_fkey",
        "assessment_participants",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "assessment_participants_user_id_fkey",
        "assessment_participants",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "assessment_participants_user_id_fkey",
        "assessment_participants",
        "users",
        ["user_id"],
        ["id"],
    )
