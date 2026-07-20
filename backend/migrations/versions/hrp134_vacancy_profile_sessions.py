"""HRP-134: vacancy profile generation sessions.

Tracks in-progress + last completed AI-profile-generation runs per vacancy
so the UI can show ``Generating…`` and re-surface a finished result if the
browser tab dropped the response.

Revision ID: hrp134profsess01
Revises: 9fa581806ea9
Create Date: 2026-05-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp134profsess01"
down_revision: str | None = "9fa581806ea9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vacancy_profile_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "result_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_vacancy_profile_sessions_vacancy_id",
        "vacancy_profile_sessions",
        ["vacancy_id"],
    )
    op.create_index(
        "ix_vacancy_profile_sessions_status",
        "vacancy_profile_sessions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vacancy_profile_sessions_status", table_name="vacancy_profile_sessions"
    )
    op.drop_index(
        "ix_vacancy_profile_sessions_vacancy_id",
        table_name="vacancy_profile_sessions",
    )
    op.drop_table("vacancy_profile_sessions")
