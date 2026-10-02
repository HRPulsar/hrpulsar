"""HRP-379 / HRP-714: notification wording after QA

Data only, en/de rows (Russian lives in the ee branch):

* ``recruitment.assessment_evaluator_submitted`` (HRP-379) — the link in
  the vacancy owner's letter opens the candidate's assessments, and now
  says so. Only the link text changes; the rest of the body is untouched.
* ``talent_market.plan_requested`` (HRP-714) — the bell shows the
  subject, so the subject names the card the plan is asked for; the
  letter says the same and its link opens the candidate's matches.

The seeds (``hrp379submittpl01``, ``hrp714tmreactiongap``) stay as they
shipped. Each change is an exact fragment swapped in place per
``(code, locale)``; ``downgrade`` swaps it back.

Revision ID: hrp379714tplcopy
Revises: v2work13
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp379714tplcopy"
down_revision: str | Sequence[str] | None = "v2work13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBMITTED = "recruitment.assessment_evaluator_submitted"
_PLAN = "talent_market.plan_requested"

# (code, locale, column, shipped fragment, new fragment)
SWAPS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        _SUBMITTED,
        "en",
        "body_template",
        ">Open the candidate</a>",
        ">Open candidate's assessments</a>",
    ),
    (
        _SUBMITTED,
        "de",
        "body_template",
        ">Kandidat öffnen</a>",
        ">Bewertungen des Kandidaten öffnen</a>",
    ),
    (
        _PLAN,
        "en",
        "subject_template",
        "{{ employee_name }} asked for a development plan",
        "{{ employee_name }} requests a development plan for {{ card_title }}",
    ),
    (
        _PLAN,
        "en",
        "body_template",
        "</b> asked for a development plan for <b>",
        "</b> requests a development plan for <b>",
    ),
    (
        _PLAN,
        "en",
        "body_template",
        ">Open the candidate</a>",
        ">View candidate matches</a>",
    ),
    (
        _PLAN,
        "de",
        "subject_template",
        "{{ employee_name }} hat um einen Entwicklungsplan gebeten",
        "{{ employee_name }} bittet um einen Entwicklungsplan für {{ card_title }}",
    ),
    (
        _PLAN,
        "de",
        "body_template",
        "</b> hat um einen Entwicklungsplan für <b>{{ card_title }}</b> gebeten.",
        "</b> bittet um einen Entwicklungsplan für <b>{{ card_title }}</b>.",
    ),
    (
        _PLAN,
        "de",
        "body_template",
        ">Kandidatin bzw. Kandidat öffnen</a>",
        ">Übereinstimmungen des Kandidaten ansehen</a>",
    ),
)


def _swap(*, forward: bool) -> None:
    bind = op.get_bind()
    for code, locale, column, shipped, new in SWAPS if forward else SWAPS[::-1]:
        old, repl = (shipped, new) if forward else (new, shipped)
        # Forward skips a row that already carries the new text, so a
        # fragment the new text contains is never doubled on a re-run.
        guard = f" AND strpos({column}, :repl) = 0" if forward else ""
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
