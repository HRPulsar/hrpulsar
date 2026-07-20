"""HRP-202: interview upload overhaul

Extends the recruitment interview surface to back the file-upload UX:

- Adds metadata columns to ``interviews``: ``title``, ``timezone``,
  ``type`` (audio/video/text_transcript/undecided), ``duration_minutes``,
  ``created_by``, ``archived_at``, ``archived_by``, ``version`` (ETag
  source) and a snapshot of the attached file (``file_s3_key``,
  ``file_size_bytes``, ``file_mime``, ``transcript_file_id``) plus the
  antivirus state (``av_status``, ``av_scanned_at``).
- Creates ``interview_interviewers`` — many-to-many between interviews
  and interviewer users (the legacy single ``interviewer_id`` column on
  ``interviews`` is kept for back-compat; the M2M is now the source of
  truth).
- Creates ``upload_sessions`` — durable record of an in-flight S3
  multipart upload tied to one interview. Persisted across page
  reloads / browser restarts so a TUS-style ``HEAD`` returns the right
  offset and the orphan-session cleanup task knows when to abort the
  underlying S3 multipart.

Revision ID: hrp202inthr01
Revises: hrp84inappnotif
Create Date: 2026-06-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp202inthr01"
down_revision: str | None = "hrp84inappnotif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("title", sa.String(255), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("timezone", sa.String(50), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "type",
            sa.String(20),
            nullable=False,
            server_default="undecided",
        ),
    )
    op.add_column(
        "interviews",
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "archived_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "transcript_file_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column("file_s3_key", sa.String(500), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("file_mime", sa.String(120), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "av_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "av_scanned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_interviews_created_by_users",
        "interviews",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_interviews_archived_by_users",
        "interviews",
        "users",
        ["archived_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_interviews_transcript_file_id",
        "interviews",
        "files",
        ["transcript_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interviews_archived_at",
        "interviews",
        ["archived_at"],
        unique=False,
    )
    op.create_index(
        "ix_interviews_av_status",
        "interviews",
        ["tenant_id", "av_status"],
    )

    op.create_table(
        "interview_interviewers",
        sa.Column(
            "interview_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_interview_interviewers_user_id",
        "interview_interviewers",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_interviewers_tenant_id",
        "interview_interviewers",
        ["tenant_id"],
    )

    op.create_table(
        "upload_sessions",
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
            "interview_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("total_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "uploaded_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("part_size", sa.Integer(), nullable=False),
        sa.Column("s3_upload_id", sa.String(500), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False),
        sa.Column(
            "s3_parts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        "ix_upload_sessions_tenant_id",
        "upload_sessions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_upload_sessions_interview_id",
        "upload_sessions",
        ["interview_id"],
    )
    op.create_index(
        "ix_upload_sessions_status_expires",
        "upload_sessions",
        ["status", "expires_at"],
    )

    # ``interviews.status`` default flips from "planned" → "scheduled" so
    # newly-created rows match the HRP-202 lifecycle vocabulary. Existing
    # rows keep their value (the alembic command is a server_default
    # change only, no UPDATE).
    op.alter_column(
        "interviews",
        "status",
        server_default="scheduled",
    )


def downgrade() -> None:
    op.alter_column(
        "interviews",
        "status",
        server_default="planned",
    )

    op.drop_index(
        "ix_upload_sessions_status_expires", table_name="upload_sessions"
    )
    op.drop_index(
        "ix_upload_sessions_interview_id", table_name="upload_sessions"
    )
    op.drop_index(
        "ix_upload_sessions_tenant_id", table_name="upload_sessions"
    )
    op.drop_table("upload_sessions")

    op.drop_index(
        "ix_interview_interviewers_tenant_id",
        table_name="interview_interviewers",
    )
    op.drop_index(
        "ix_interview_interviewers_user_id",
        table_name="interview_interviewers",
    )
    op.drop_table("interview_interviewers")

    op.drop_index("ix_interviews_av_status", table_name="interviews")
    op.drop_index("ix_interviews_archived_at", table_name="interviews")
    op.drop_constraint(
        "fk_interviews_transcript_file_id", "interviews", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_interviews_archived_by_users", "interviews", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_interviews_created_by_users", "interviews", type_="foreignkey"
    )

    for col in (
        "av_scanned_at",
        "av_status",
        "file_mime",
        "file_size_bytes",
        "file_s3_key",
        "transcript_file_id",
        "version",
        "archived_by",
        "archived_at",
        "created_by",
        "duration_minutes",
        "type",
        "timezone",
        "title",
    ):
        op.drop_column("interviews", col)
