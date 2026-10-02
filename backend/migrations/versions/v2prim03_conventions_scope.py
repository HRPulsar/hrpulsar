"""HRP-961: the catalog descriptions of P8 and P11 follow the conventions.

Data only. ``v2prim01`` seeds with ``ON CONFLICT DO NOTHING``, so an
upgraded install keeps the wording it was seeded with unless it is
rewritten here; a fresh install gets the new text from the seed and the
UPDATE changes nothing. Decisions of 2026-09-28: escalation by rule and
notification are no longer coordination (P11), and assigning a person is
P8 only when it takes a judgment about people.

Revision ID: v2prim03
Revises: v2work11
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2prim03"
down_revision: str | Sequence[str] | None = "v2work11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code -> (before, after); the "after" text is catalog_data.PRIMITIVES at
# this revision, pinned here so a later edit of the seed cannot rewrite
# what this revision does.
SCOPES = {
    "P8": (
        "Assign a person, reconcile opinions, push a decision through, "
        "agree on a priority, hand over to the owner",
        "Choose a person by skills, load and relationships, reconcile "
        "opinions, push a decision through, agree on a priority, hand over "
        "to the owner",
    ),
    "P11": (
        "Notify, collect responses, track readiness, put on the schedule, "
        "escalate by rule",
        "Hold the schedule, remind, react to a deadline or a trigger, track "
        "completion and answers against a list",
    ),
}

# IS DISTINCT FROM: a fresh install already carries the new text from the
# seed, and its rows keep their updated_at.
_UPDATE = sa.text(
    "UPDATE primitives SET scope_en = :scope, updated_at = now() "
    "WHERE code = :code AND scope_en IS DISTINCT FROM :scope"
)


def upgrade() -> None:
    for code, (_before, after) in SCOPES.items():
        op.execute(_UPDATE.bindparams(scope=after, code=code))


def downgrade() -> None:
    for code, (before, _after) in SCOPES.items():
        op.execute(_UPDATE.bindparams(scope=before, code=code))
