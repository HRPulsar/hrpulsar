"""Phase CR11: AI competence generation sessions

Revision ID: cr11a1b2c3d4e5f
Revises: cr10b1a2b3c4d5
Create Date: 2026-05-01 14:00:00.000000

Adds `competence_generation_sessions` — backend state for the "Generate
with AI" flow. Each row represents one user-initiated generation: scope,
frozen base snapshot, LLM payload, cascading selection, and lifecycle
status. A partial unique index enforces "one active session per user"
(active = status IN ('pending','running','ready')).

Also seeds two notification templates so the Celery worker can call
`send_notification(...)` once a session reaches `ready` or `error`. The
template body is intentionally short — UI rendering happens in CR13.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cr11a1b2c3d4e5f"
down_revision: str | None = "cr10b1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SESSION_SCOPES = "('whole_base','group','competence_indicators')"
SESSION_STATUSES = "('pending','running','ready','error','applied','cancelled')"
ERROR_CODES = "('service_error','overload','insufficient_data','parse_error')"


def upgrade() -> None:
    op.create_table(
        "competence_generation_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "base_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "selection_state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "prompt_version",
            sa.String(length=40),
            nullable=False,
            server_default="cr11.v1",
        ),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("cost_credits", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("applied_result", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["competence_generation_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"scope IN {SESSION_SCOPES}",
            name="ck_compgen_scope",
        ),
        sa.CheckConstraint(
            f"status IN {SESSION_STATUSES}",
            name="ck_compgen_status",
        ),
        sa.CheckConstraint(
            f"error_code IS NULL OR error_code IN {ERROR_CODES}",
            name="ck_compgen_error_code",
        ),
    )

    op.create_index(
        "ix_compgen_tenant", "competence_generation_sessions", ["tenant_id"]
    )
    op.create_index("ix_compgen_user", "competence_generation_sessions", ["user_id"])
    op.create_index("ix_compgen_status", "competence_generation_sessions", ["status"])
    op.create_index(
        "ix_compgen_parent",
        "competence_generation_sessions",
        ["parent_session_id"],
    )
    op.create_index(
        "ux_compgen_one_active_per_user",
        "competence_generation_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','running','ready')"),
    )

    # Seed notification templates used by tasks.run_generation_session.
    op.execute("""
        INSERT INTO notification_templates
            (id, code, subject_template, body_template, notification_type,
             created_at, updated_at)
        VALUES
            (gen_random_uuid(),
             'competence_generation_ready',
             'AI competence generation is ready',
             '<p>Hi {{ recipient_name }},</p><p>Your competence generation '
             'session has finished. Open the competence library to review '
             'and apply the suggestions.</p>',
             'in_app', now(), now()),
            (gen_random_uuid(),
             'competence_generation_error',
             'AI competence generation failed',
             '<p>Hi {{ recipient_name }},</p><p>Your competence generation '
             'session ended with an error: {{ error_message }}.</p>',
             'in_app', now(), now())
        ON CONFLICT (code) DO NOTHING
        """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_templates WHERE code IN "
        "('competence_generation_ready','competence_generation_error')"
    )
    op.drop_index(
        "ux_compgen_one_active_per_user",
        table_name="competence_generation_sessions",
    )
    op.drop_index("ix_compgen_parent", table_name="competence_generation_sessions")
    op.drop_index("ix_compgen_status", table_name="competence_generation_sessions")
    op.drop_index("ix_compgen_user", table_name="competence_generation_sessions")
    op.drop_index("ix_compgen_tenant", table_name="competence_generation_sessions")
    op.drop_table("competence_generation_sessions")
