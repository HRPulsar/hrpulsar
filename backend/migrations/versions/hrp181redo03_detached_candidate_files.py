"""HRP-181 REDO Stage 3: detached candidate_files (nullable candidate_id)

Stage 3 batch-parses resumes before the user picks "Import". The upload
endpoint writes rows with ``candidate_id IS NULL`` so the parser can run
in the background without a placeholder Candidate row leaking into the
candidate list. ``finalize_candidates_from_parsed`` later flips
``candidate_id`` to the real (created or linked) candidate.

Adds:

- ``candidate_files.candidate_id`` NULLable (was NOT NULL).
- Partial index on ``(tenant_id, created_at)`` filtered by
  ``candidate_id IS NULL`` to keep the 24h parsing-status poll cheap
  even after the table grows.

Revision ID: hrp181redo03
Revises: hrp181redo02
Create Date: 2026-06-08 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp181redo03"
down_revision: str | None = "hrp181redo02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "candidate_files",
        "candidate_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidate_files_detached_recent
        ON candidate_files (tenant_id, created_at)
        WHERE candidate_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_files_detached_recent")
    # Detached rows would violate NOT NULL on downgrade — flush them so
    # the older schema stays valid. They are transient (Stage 3 cleanup
    # task removes them after 7 days anyway).
    op.execute("DELETE FROM candidate_files WHERE candidate_id IS NULL")
    op.alter_column(
        "candidate_files",
        "candidate_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
