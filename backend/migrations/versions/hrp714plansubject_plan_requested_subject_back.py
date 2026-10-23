"""HRP-714: the plan-request subject goes back to the seed wording

Data only, en/de rows (Russian lives in the ee branch). QA (21.10) kept
the reworded body of ``talent_market.plan_requested`` ("... requests a
development plan for {card}") but wants the subject - what the bell
shows as its title and the letter as its subject - back as the seed
``hrp714tmreactiongap`` shipped it: "{name} asked for a development
plan". The ``hrp379714tplcopy`` subject swap is undone; its body swaps
stay.

The seeds stay as they shipped. Each change is an exact fragment swapped
in place per ``(code, locale)``; ``downgrade`` swaps it back.

Revision ID: hrp714plansubject
Revises: hrp854skillcode
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp714plansubject"
down_revision: str | Sequence[str] | None = "hrp854skillcode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN = "talent_market.plan_requested"

# (code, locale, column, current fragment, new fragment)
SWAPS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        _PLAN,
        "en",
        "subject_template",
        "{{ employee_name }} requests a development plan for {{ card_title }}",
        "{{ employee_name }} asked for a development plan",
    ),
    (
        _PLAN,
        "de",
        "subject_template",
        "{{ employee_name }} bittet um einen Entwicklungsplan für {{ card_title }}",
        "{{ employee_name }} hat um einen Entwicklungsplan gebeten",
    ),
)


def _swap(*, forward: bool) -> None:
    bind = op.get_bind()
    for code, locale, column, current, new in SWAPS if forward else SWAPS[::-1]:
        old, repl = (current, new) if forward else (new, current)
        # A replacement that contains the fragment it replaces would grow
        # on a re-run; skip a row that already carries it.
        guard = f" AND strpos({column}, :repl) = 0" if old in repl else ""
        # ``column`` comes from the constant table above, never from input.
        bind.execute(
            sa.text(
                "UPDATE notification_templates"
                f" SET {column} = replace({column}, :old, :repl), updated_at = now()"
                f" WHERE code = :code AND locale = :locale{guard}"
            ),
            {"code": code, "locale": locale, "old": old, "repl": repl},
        )


def upgrade() -> None:
    _swap(forward=True)


def downgrade() -> None:
    _swap(forward=False)
