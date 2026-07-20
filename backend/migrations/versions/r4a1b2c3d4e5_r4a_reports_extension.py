"""R4a: report exports + templates extension (XLSX generation, sections)

Extends the existing ``consolidated_reports`` and ``report_templates``
tables (created in r1) with the columns Phase R4a needs:

- ``report_templates.sections`` (JSONB) — list of section codes a template
  exports (``vacancy_summary``, ``competence_profile``, …).
- ``report_templates.is_active`` (bool) — admins can soft-disable a
  template without deleting it; lookups filter by this.
- ``consolidated_reports.template_id`` — which template was used; nullable
  so ad-hoc exports work without a saved template.
- ``consolidated_reports.sections`` — snapshot of the sections requested
  for this export (so editing the template later does not retroactively
  rewrite history).
- ``consolidated_reports.error`` (text), ``completed_at`` (timestamptz)
  — surface task failures and the success boundary in the UI.
- ``ix_consolidated_reports_vacancy_created`` — supports the most common
  query path: list a vacancy's exports newest-first.

Revision ID: r4a1b2c3d4e5
Revises: r3a1b2c3d4e5
Create Date: 2026-05-09 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r4a1b2c3d4e5"
down_revision: str | None = "r3a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── report_templates: sections + is_active ─────────────────────────
    op.add_column(
        "report_templates",
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "report_templates",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── consolidated_reports: template_id, sections, error, completed_at
    op.add_column(
        "consolidated_reports",
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_consolidated_reports_template_id",
        "consolidated_reports",
        "report_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "consolidated_reports",
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "consolidated_reports",
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.add_column(
        "consolidated_reports",
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Composite index for the common "list vacancy exports newest-first".
    op.create_index(
        "ix_consolidated_reports_vacancy_created",
        "consolidated_reports",
        ["tenant_id", "vacancy_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consolidated_reports_vacancy_created",
        table_name="consolidated_reports",
    )
    op.drop_column("consolidated_reports", "completed_at")
    op.drop_column("consolidated_reports", "error")
    op.drop_column("consolidated_reports", "sections")
    op.drop_constraint(
        "fk_consolidated_reports_template_id",
        "consolidated_reports",
        type_="foreignkey",
    )
    op.drop_column("consolidated_reports", "template_id")
    op.drop_column("report_templates", "is_active")
    op.drop_column("report_templates", "sections")
