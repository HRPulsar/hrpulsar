"""i18n F5 (HRP-479): stable i18n_key on origin reference rows.

Adds ``i18n_key`` to ``dictionary_items`` and backfills it for origin
rows only (``tenant_id IS NULL``) as a slug of the seeded English title
(``Backend Developer`` -> ``backend_developer``) — the same convention
migration ``cr1a0b1c2d3e4`` used for ``skill_levels``. The frontend
renders ``t(`reference.dictionary.${type}.${i18n_key}`)`` and falls back
to the stored title, so tenant-created items (``i18n_key IS NULL``) keep
rendering verbatim and the English UI is unchanged.

Also adds ``i18n_key`` to ``answer_scales`` and stamps the seeded
default scale (and its historical snapshots) ``standard_5point``.
Snapshots flip ``is_default`` to false and null out ``tenant_id``, so
the flag alone cannot identify the origin scale after an assessment
leaves draft; going forward ``snapshot_scale_for_assessment`` copies the
key. Historical snapshots are matched by the seeded title — a tenant
snapshot that reused the exact seeded title verbatim would pick up the
key too, which only means its (identical) title gets localized.

NOTE for future origin seeds: any migration inserting origin dictionary
rows must set ``i18n_key`` explicitly and add the matching
``reference.dictionary.*`` keys to ``frontend/messages/{en,de}.json``.

Revision ID: hrp479refdata01
Revises: hrp478emaildb01
Create Date: 2026-07-29 20:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp479refdata01"
down_revision: str | None = "hrp478emaildb01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dictionary_items",
        sa.Column("i18n_key", sa.String(length=100), nullable=True),
    )
    # Origin rows only; tenant items stay NULL and render verbatim.
    op.execute(
        "UPDATE dictionary_items "
        "SET i18n_key = trim(both '_' from "
        "lower(regexp_replace(title, '[^a-zA-Z0-9]+', '_', 'g'))) "
        "WHERE tenant_id IS NULL AND i18n_key IS NULL"
    )

    op.add_column(
        "answer_scales",
        sa.Column("i18n_key", sa.String(length=100), nullable=True),
    )
    # Snapshot rows lost their tenant_id at publish, so title alone can't
    # distinguish the stock scale from a tenant scale that reused its name;
    # require the stock description too, or a tenant-authored description
    # would render substituted by the catalog one (answerScaleDescription).
    op.execute(
        "UPDATE answer_scales SET i18n_key = 'standard_5point' "
        "WHERE tenant_id IS NULL AND (is_default = true "
        "OR (is_snapshot = true AND title = 'Standard 5-Point Scale' "
        "AND description IS NOT DISTINCT FROM 'Default assessment scoring scale'))"
    )


def downgrade() -> None:
    op.drop_column("answer_scales", "i18n_key")
    op.drop_column("dictionary_items", "i18n_key")
