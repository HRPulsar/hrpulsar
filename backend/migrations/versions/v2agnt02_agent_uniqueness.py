"""Two uniqueness rules the AI-workforce registry checked in Python but
never had behind it in the database.

``uq_ai_agents_tenant_name`` was case-sensitive while ``_ensure_name_free``
compared ``lower(name)``, so "ChatGPT" and "chatgpt" both passed the
pre-check and both committed - and every later update of either one got a
409 it could not resolve. The constraint becomes a functional unique index
on ``lower(name)``, which is the rule the service actually enforces.

The duplicate-pending guard in ``request_assignment`` was a plain
check-then-insert: a double click made two pending rows and an admin could
approve both. A partial unique index makes the second insert fail so the
guard's 409 is the only outcome.

Both indexes are unique, so the rows the old guards let through are dealt
with first: a later case-insensitive duplicate of an agent name gets its
id's first eight characters appended (the name is cut to 189 first, so the
suffix still fits the 200-char column), and of two pending requests for one
(employee, agent) pair the later ones are rejected. Without this the
migration aborts on exactly the databases it was written for.

The duplicates are rejected, never deleted: ``ai_usage_assignments`` is the
EU-AI-Act register the audit log points at, and a downgrade cannot restore
a row this revision dropped. ``rejected`` is a final status outside the
partial index's ``status = 'pending'`` predicate, so the index is satisfied.

Ninth revision of the HRPulsar 2.0 chain (epic HRP-746).
Downgrade order: ``v2agnt02 -> v2merge02 -> v2work05 -> ...``.

Revision ID: v2agnt02
Revises: v2merge02
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2agnt02"
down_revision: str | Sequence[str] | None = "v2merge02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE ai_agents AS a
        SET name = left(a.name, 189) || ' (' || left(a.id::text, 8) || ')'
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY tenant_id, lower(name) ORDER BY created_at, id
            ) AS rn
            FROM ai_agents
        ) AS d
        WHERE d.id = a.id AND d.rn > 1
        """)
    op.execute("""
        UPDATE ai_usage_assignments AS x
        SET status = 'rejected'
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY employee_id, agent_id ORDER BY created_at, id
            ) AS rn
            FROM ai_usage_assignments
            WHERE status = 'pending'
        ) AS d
        WHERE d.id = x.id AND d.rn > 1
        """)
    op.drop_constraint("uq_ai_agents_tenant_name", "ai_agents", type_="unique")
    op.create_index(
        "uq_ai_agents_tenant_name_lower",
        "ai_agents",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "uq_ai_assignments_pending",
        "ai_usage_assignments",
        ["employee_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_assignments_pending", table_name="ai_usage_assignments")
    op.drop_index("uq_ai_agents_tenant_name_lower", table_name="ai_agents")
    # Take the disambiguating suffix back off before the old constraint is
    # back: the upgrade appended " (" || left(id, 8) || ")" to the name, and
    # a downgrade that leaves it turns a one-way rename into the permanent
    # one. A name that was longer than 189 characters stays cut - the
    # original tail is not in the database any more.
    #
    # The pending duplicates are deliberately left ``rejected``: the upgrade
    # cannot tell its own rejects from an admin's, and ai_usage_assignments
    # is the EU-AI-Act register (see the module docstring).
    op.execute("""
        UPDATE ai_agents
        SET name = left(name, length(name) - 11)
        WHERE right(name, 11) = ' (' || left(id::text, 8) || ')'
        """)
    op.create_unique_constraint(
        "uq_ai_agents_tenant_name", "ai_agents", ["tenant_id", "name"]
    )
