"""H phase: file uploads — avatar, PDP attachments, exam images

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # H1: Avatar — add avatar_file_id to users
    op.add_column(
        "users",
        sa.Column(
            "avatar_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # H2: PDP attachments — add file_id to pdp_comments and pdp_item_materials
    op.add_column(
        "pdp_comments",
        sa.Column(
            "file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "pdp_item_materials",
        sa.Column(
            "file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # H3: Exam question images — add image_file_id, drop image_url
    op.add_column(
        "exam_questions",
        sa.Column(
            "image_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.drop_column("exam_questions", "image_url")


def downgrade() -> None:
    op.add_column(
        "exam_questions",
        sa.Column("image_url", sa.String(600), nullable=True),
    )
    op.drop_column("exam_questions", "image_file_id")
    op.drop_column("pdp_item_materials", "file_id")
    op.drop_column("pdp_comments", "file_id")
    op.drop_column("users", "avatar_file_id")
