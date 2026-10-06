"""HRP-790: Offer accepted and Probation completed in the default funnel

New tenants get both stages from ``DEFAULT_RECRUITMENT_STAGES``; this
revision adds them to every funnel that already exists:

* ``offer_accepted`` (active) right after ``offer``;
* ``probation_completed`` (terminal-positive) right after ``hired``.

"Every funnel" is the tenant default set and each per-vacancy override
(``_get_applicable_stages`` reads the override instead of the defaults, so
a vacancy with one would never see the new stages otherwise). A funnel
gets a stage only when it still has the anchor stage and not the new code
yet, so a re-run is a no-op. Overrides number their stages 0, 1, 2…, so
the stages after the anchor move down by one to make room.

Names come from the ``recruitment.stage.*`` catalog in the tenant's locale,
like ``seed_default_recruitment_stages`` writes them - the core tree
carries no Cyrillic, and an enterprise install resolves ru through
``ee/i18n`` (open-core mechanism 3).

The same rule renames ``hired`` where its catalog name grew past the old
seed: ru went from one word to three. The untouched old default is
recognised as the first word of the new name, so a stage the tenant
renamed is left alone and no locale with a one-word name is touched.

It also normalises the vacancy statuses for the HRP-836 status model, one
way (``downgrade`` keeps them - the old code read both the same):

* ``published`` - what the demo seed, the onboarding sample and old edit
  payloads wrote for a live vacancy - becomes ``open``, the only name the
  status commands know;
* a vacancy closed with the old ``cancelled`` resolution becomes the
  Cancelled status, without a resolution (``closed_at`` stays).

Revision ID: hrp790stages01
Revises: hrp973droperms
Create Date: 2026-10-02

"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp790stages01"
down_revision: str | None = "hrp973droperms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, anchor code, stage_type, color) - mirrors DEFAULT_RECRUITMENT_STAGES,
# pinned by tests/unit/test_hrp790_post_offer_stages.py.
NEW_STAGES: tuple[tuple[str, str, str, str], ...] = (
    ("offer_accepted", "offer", "active", "teal"),
    ("probation_completed", "hired", "terminal_positive", "green"),
)

# Same resolution as hrp781stagei18n01: a tenant with no locale follows the
# deployment.
_DEPLOYMENT_LOCALE = (os.environ.get("DEFAULT_LOCALE") or "en").strip().lower()
_TENANT_LOCALE = (
    "lower(split_part("
    "coalesce(nullif(trim(t.default_locale), ''), :deployment_locale), '-', 1))"
)

# A funnel (tenant defaults: vacancy_id NULL, or one vacancy's override)
# that holds the anchor ``a`` but not the new code yet.
_MISSING = """
    a.code = :anchor
    AND NOT EXISTS (
        SELECT 1 FROM vacancy_stages b
         WHERE b.tenant_id = a.tenant_id
           AND b.vacancy_id IS NOT DISTINCT FROM a.vacancy_id
           AND b.code = :code
    )
"""

_MAKE_ROOM = sa.text(
    f"""
    UPDATE vacancy_stages s
       SET sort_order = s.sort_order + 1
      FROM vacancy_stages a
     WHERE s.tenant_id = a.tenant_id
       AND s.vacancy_id IS NOT DISTINCT FROM a.vacancy_id
       AND s.sort_order > a.sort_order
       AND {_MISSING}
    """
)

_INSERT = sa.text(
    f"""
    INSERT INTO vacancy_stages (
        id, tenant_id, vacancy_id, name, code, sort_order,
        is_terminal, stage_type, color, created_at, updated_at
    )
    SELECT gen_random_uuid(), a.tenant_id, a.vacancy_id,
           CAST(:name AS VARCHAR), CAST(:code AS VARCHAR), a.sort_order + 1,
           :is_terminal, CAST(:stage_type AS VARCHAR), CAST(:color AS VARCHAR),
           now(), now()
      FROM vacancy_stages a
      JOIN tenants t ON t.id = a.tenant_id
     WHERE {_MISSING}
       AND {_TENANT_LOCALE} = :locale
    """
)

_RENAME = sa.text(
    f"""
    UPDATE vacancy_stages vs
       SET name = :new_name, updated_at = now()
      FROM tenants t
     WHERE vs.tenant_id = t.id
       AND vs.code = :code
       AND vs.name = :old_name
       AND {_TENANT_LOCALE} = :locale
    """
)


def _locales() -> list[tuple[str, str]]:
    """``(tenant locale as resolved in SQL, catalog locale)`` for every tenant.

    Every value is returned, so the insert reaches each funnel that
    ``_MAKE_ROOM`` made room in; a malformed one (``ru_RU``, ``english``)
    takes the English names. Only a plain language code names a catalog
    file.
    """
    rows = op.get_bind().execute(
        sa.text(f"SELECT DISTINCT {_TENANT_LOCALE} FROM tenants t"),
        {"deployment_locale": _DEPLOYMENT_LOCALE},
    )
    return [
        (value, value if re.fullmatch(r"[a-z]{2,3}", value) else "en")
        for (value,) in rows
    ]


def _hired_rename(locale: str) -> tuple[str, str] | None:
    """(old seed name, catalog name) when the catalog name grew past it."""
    from app.core.i18n import translate

    name = translate("recruitment.stage.hired", locale)
    first_word = name.split(" ", 1)[0]
    return (first_word, name) if first_word != name else None


def upgrade() -> None:
    from app.core.i18n import translate

    op.execute("UPDATE vacancies SET status = 'open' WHERE status = 'published'")
    op.execute(
        "UPDATE vacancies SET status = 'cancelled', close_resolution = NULL"
        " WHERE status = 'closed' AND close_resolution = 'cancelled'"
    )

    bind = op.get_bind()
    locales = _locales()
    for code, anchor, stage_type, color in NEW_STAGES:
        bind.execute(_MAKE_ROOM, {"anchor": anchor, "code": code})
        for locale, catalog in locales:
            bind.execute(
                _INSERT,
                {
                    "anchor": anchor,
                    "code": code,
                    "name": translate(f"recruitment.stage.{code}", catalog),
                    "is_terminal": stage_type != "active",
                    "stage_type": stage_type,
                    "color": color,
                    "locale": locale,
                    "deployment_locale": _DEPLOYMENT_LOCALE,
                },
            )
    for locale, catalog in locales:
        names = _hired_rename(catalog)
        if names:
            bind.execute(
                _RENAME,
                {
                    "code": "hired",
                    "old_name": names[0],
                    "new_name": names[1],
                    "locale": locale,
                    "deployment_locale": _DEPLOYMENT_LOCALE,
                },
            )


def downgrade() -> None:
    # Only the rows nobody stands on go; the room made for them stays
    # (sort_order is relative, a gap changes nothing).
    op.execute(
        """
        DELETE FROM vacancy_stages vs
         WHERE vs.code IN ('offer_accepted', 'probation_completed')
           AND NOT EXISTS (
               SELECT 1 FROM candidate_vacancies cv WHERE cv.stage_id = vs.id
           )
        """
    )
    bind = op.get_bind()
    for locale, catalog in _locales():
        names = _hired_rename(catalog)
        if names:
            bind.execute(
                _RENAME,
                {
                    "code": "hired",
                    "old_name": names[1],
                    "new_name": names[0],
                    "locale": locale,
                    "deployment_locale": _DEPLOYMENT_LOCALE,
                },
            )
