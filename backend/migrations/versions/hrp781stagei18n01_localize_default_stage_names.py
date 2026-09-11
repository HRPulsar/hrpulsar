"""HRP-781: localize the default recruitment stage names per tenant

``hrp181redo02`` seeded the canonical 9-stage funnel with hardcoded
English names, and every consumer reads ``vacancy_stages.name`` straight
out of the DB — candidate lists, funnel analytics, XLSX reports, emails.
On a non-English installation the funnel therefore stayed English no
matter what the interface language was set to.

New tenants now take their stage names from the ``recruitment.stage.*``
catalog in their own locale (``seed_default_recruitment_stages``). This
migration does the same for rows that already exist, and only for rows
still carrying the exact English seed name — a stage the tenant renamed
is their wording and is left alone.

Russian is an enterprise-only locale (OPEN_CORE.md), so its names live in
the ee branch (``ee022stagenamesru``); this revision covers the locales
shipped in the community tree.

Revision ID: hrp781stagei18n01
Revises: hrp379submittpl01
Create Date: 2026-09-11

"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp781stagei18n01"
down_revision: str | None = "hrp379submittpl01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, English seed name, {locale: localized name}) — the English names
# mirror ``DEFAULT_RECRUITMENT_STAGES`` and the localized ones mirror
# ``recruitment.stage.*`` in app/i18n/<locale>.json. Kept inline so the
# migration stays self-contained, and pinned against both by
# tests/unit/test_hrp781_stage_name_locale.py.
STAGE_NAMES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("new", "New", {"de": "Neu"}),
    ("screening", "Screening", {"de": "Vorauswahl"}),
    ("tech_interview", "Tech interview", {"de": "Fachgespräch"}),
    (
        "manager_interview",
        "Interview with manager",
        {"de": "Gespräch mit der Führungskraft"},
    ),
    ("final_interview", "Final interview", {"de": "Abschlussgespräch"}),
    ("offer", "Offer", {"de": "Angebot"}),
    ("hired", "Hired", {"de": "Eingestellt"}),
    ("rejected", "Rejected", {"de": "Abgelehnt"}),
    ("withdrew", "Withdrew", {"de": "Zurückgezogen"}),
)

# A tenant with no explicit default_locale follows the deployment, same
# resolution order as app.core.i18n.resolve_locale. Read from the
# environment rather than app.config to keep the migration importable on
# its own.
_DEPLOYMENT_LOCALE = (os.environ.get("DEFAULT_LOCALE") or "en").strip().lower()

# Tenant locales are ISO 639-1, but tolerate a stored "de-DE" shape.
_TENANT_LOCALE = (
    "lower(split_part("
    "coalesce(nullif(trim(t.default_locale), ''), :deployment_locale), '-', 1))"
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


def _rename(old: str, new: str, code: str, locale: str) -> None:
    op.get_bind().execute(
        _RENAME,
        {
            "code": code,
            "locale": locale,
            "old_name": old,
            "new_name": new,
            "deployment_locale": _DEPLOYMENT_LOCALE,
        },
    )


def upgrade() -> None:
    for code, en_name, by_locale in STAGE_NAMES:
        for locale, localized in by_locale.items():
            if localized != en_name:
                _rename(en_name, localized, code, locale)


def downgrade() -> None:
    # Put the English seed name back wherever this migration's own
    # localized value is still in place; anything else was edited since
    # and stays untouched.
    for code, en_name, by_locale in STAGE_NAMES:
        for locale, localized in by_locale.items():
            if localized != en_name:
                _rename(localized, en_name, code, locale)
