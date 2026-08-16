"""HRP-581: create the recruitment indexes the models ask for

The drift guard (HRP-540) surfaced 42 columns carrying ``index=True`` in
``app/modules/recruitment/models.py`` for which no migration ever emitted
the DDL. Each was reviewed against the queries that actually run; this
migration creates the 14 that earn their keep and the models dropped
``index=True`` from the rest (a model-only index costs nothing in a
deployed database — it never existed there — so those need no DDL).

Two groups are created here:

* Child-by-parent lookups — the FK columns every listing page filters on
  (segments of an interview, candidates of a vacancy, assessments of a
  candidate_vacancy). These run on the hot read paths.
* ``tenant_id`` on three tables that never got the index ``TenantMixin``
  declares. Besides the tenant-scoped reads, the column carries
  ``ON DELETE CASCADE`` from ``tenants``: without an index, deleting a
  tenant (demo purge) sequentially scans each child table.

Deliberately NOT created: columns whose filters only ever appear as a
secondary predicate next to an already-indexed leading column
(``competence_id`` beside ``candidate_vacancy_id``, ``vacancy_id``
beside ``tenant_id`` in a composite), and the four ``tenant_id`` columns
already covered by a composite index that leads with ``tenant_id``.

Plain ``CREATE INDEX`` (not CONCURRENTLY): alembic runs a migration in a
transaction, and at current table sizes the build is short. Revisit if
these tables grow into the millions.

Revision ID: hrp581recidx
Revises: hrp575signuploc
Create Date: 2026-08-14 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp581recidx"
down_revision: str | None = "hrp575signuploc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column) — index name follows SQLAlchemy's ``index=True``
# convention, ``ix_<table>_<column>``, so the models and the database
# agree on the name as well as the shape.
INDEXES: tuple[tuple[str, str], ...] = (
    # --- child-by-parent lookups ---
    ("ai_assessments", "interview_id"),
    ("assessment_invites", "candidate_vacancy_id"),
    ("candidate_files", "candidate_id"),
    ("candidate_questions", "candidate_id"),
    ("candidate_vacancies", "candidate_id"),
    ("candidate_vacancies", "stage_id"),
    ("candidate_vacancies", "vacancy_id"),
    ("human_assessments", "candidate_vacancy_id"),
    ("interview_segments", "interview_id"),
    ("interviews", "candidate_vacancy_id"),
    ("vacancy_stages", "vacancy_id"),
    # --- TenantMixin's index, missing on these three tables ---
    ("vacancy_attachments", "tenant_id"),
    ("vacancy_competences", "tenant_id"),
    ("vacancy_profile_sessions", "tenant_id"),
)


def upgrade() -> None:
    for table, column in INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, column in reversed(INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
