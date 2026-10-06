"""HRP-982: the stage-change notification names who moved the candidate

The ``recruitment.candidate.stage_changed`` event carries the mover since
HRP-982 (``actor_id`` / ``actor_name``); the template now says who it was.
en and de rows only - Russian lives in the ee branch
(``ee029stagemoverru``).

A row is rewritten only while its body is still the shipped default, so a
template an installation reworded is left alone; ``downgrade`` puts the
shipped body back under the same guard. Nothing is inserted, so there is
no ``(code, locale)`` conflict to resolve. An event raised before the
change has no ``actor_name`` and renders without the sentence.

Revision ID: hrp982stagetpl01
Revises: hrp790stages01
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp982stagetpl01"
down_revision: str | Sequence[str] | None = "hrp790stages01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "recruitment.candidate_stage_changed"

# locale -> (shipped body, body naming the mover). The shipped bodies are
# pinned against their seeds (r4c1b2c3d4e5, hrp481detemplates01) by
# tests/unit/test_hrp982_stage_template_mover.py.
BODIES: dict[str, tuple[str, str]] = {
    "en": (
        "<p>{{ candidate_name }} on <b>{{ vacancy_title }}</b> is now in stage"
        " <b>{{ stage_name }}</b>.</p>",
        "<p>{{ candidate_name }} on <b>{{ vacancy_title }}</b> is now in stage"
        " <b>{{ stage_name }}</b>.{% if actor_name %} Moved by"
        " {{ actor_name }}.{% endif %}</p>",
    ),
    "de": (
        "<p>{{ candidate_name }} befindet sich bei der Stelle"
        " <b>{{ vacancy_title }}</b> jetzt in der Phase <b>{{ stage_name }}</b>.</p>",
        "<p>{{ candidate_name }} befindet sich bei der Stelle"
        " <b>{{ vacancy_title }}</b> jetzt in der Phase <b>{{ stage_name }}</b>."
        "{% if actor_name %} Verschoben von {{ actor_name }}.{% endif %}</p>",
    ),
}

_SWAP = sa.text(
    "UPDATE notification_templates SET body_template = :new, updated_at = now()"
    " WHERE code = :code AND locale = :locale AND body_template = :old"
)


def _swap(*, forward: bool) -> None:
    bind = op.get_bind()
    for locale, (shipped, new) in BODIES.items():
        old, repl = (shipped, new) if forward else (new, shipped)
        bind.execute(_SWAP, {"code": CODE, "locale": locale, "old": old, "new": repl})


def upgrade() -> None:
    _swap(forward=True)


def downgrade() -> None:
    _swap(forward=False)
