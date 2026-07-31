"""Dynamic AI model catalog (HRP-466) — tenant-agnostic, pure core.

The catalog is the DB-backed source for ``GET /admin/ai-settings/models``:
seeded idempotently from the curated ``model_registry`` tier constants, then
extended by the daily discovery sweep (``refresh_model_catalog_task``).

Moderation contract (implemented by platform admin in the enterprise build;
core only classifies and filters):

* a discovered id that is a **re-dated snapshot** of an approved model of
  the same provider (same id with the trailing ``-YYYYMMDD`` stripped) is
  auto-approved and inherits the family's tier/multiplier row values;
* a genuinely **new model** is ``pending`` + disabled while billing is
  active (SaaS) — not pickable, not billable, multiplier NULL — until a
  platform admin approves it with an explicit multiplier (or rejects it;
  snapshots of a rejected family inherit ``rejected``);
* without billing (community/onprem) new models are auto-approved — there
  is nothing to price.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.ai import model_registry
from app.modules.ai.models import ModelCatalogEntry

logger = logging.getLogger(__name__)

# Snapshot-version suffixes are provider-specific: Anthropic dates compactly
# (-20251001), OpenAI with dashes (-2024-08-06), Gemini with a 3-digit
# revision (-001/-002). Gemini ``-preview-*``/``-exp-*`` names deliberately
# do NOT normalize — previews change behavior, so they go through moderation
# as new models.
_VERSION_SUFFIXES: dict[str, re.Pattern[str]] = {
    "anthropic": re.compile(r"-\d{8}$"),
    "openai": re.compile(r"-\d{4}-\d{2}-\d{2}$"),
    "gemini": re.compile(r"-\d{3}$"),
}


def billing_active() -> bool:
    """New discovered models need moderation only where billing exists."""
    return settings.deployment_mode == "saas"


def normalize_model_id(model_id: str, provider: str) -> str:
    """Strip the provider's trailing snapshot-version suffix, if any."""
    pattern = _VERSION_SUFFIXES.get(provider)
    if pattern is None:
        return model_id
    return pattern.sub("", model_id)


def _family_rank(row: ModelCatalogEntry) -> tuple[bool, bool, str]:
    """Deterministic preference among same-family catalog rows.

    Canonical dateless id first (its registry/YAML price is keyed on it),
    then any row that carries a moderated multiplier, then the newest
    snapshot (version suffixes sort lexicographically within a provider).
    """
    return (
        row.model_id == normalize_model_id(row.model_id, row.provider),
        row.credit_multiplier is not None,
        row.model_id,
    )


def _pick_family_rows(
    rows: list[ModelCatalogEntry], status: str
) -> dict[str, ModelCatalogEntry]:
    """Map normalized family id → the preferred row with the given status."""
    best: dict[str, ModelCatalogEntry] = {}
    for row in rows:
        if row.status != status:
            continue
        key = normalize_model_id(row.model_id, row.provider)
        current = best.get(key)
        if current is None or _family_rank(row) > _family_rank(current):
            best[key] = row
    return best


def _seed_rows() -> list[dict[str, Any]]:
    """Curated seed derived from the tier constants (single source of truth).

    Labels default to the model id — the enterprise build overlays human
    labels via the in-memory registry (credits.yaml) at read time.
    """
    tiers: list[tuple[str, dict[str, str]]] = [
        ("fast", model_registry.FAST_MODELS),
        ("balanced", model_registry.BALANCED_MODELS),
        ("thorough", model_registry.THOROUGH_MODELS),
    ]
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for tier, models in tiers:
        for provider, model_id in models.items():
            key = (provider, model_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"provider": provider, "model_id": model_id, "tier": tier})
    # Optional pickable flagship — deliberately tier-less.
    rows.append(
        {
            "provider": "anthropic",
            "model_id": model_registry.ANTHROPIC_FABLE,
            "tier": None,
        }
    )
    return rows


async def seed_from_registry(db: AsyncSession) -> int:
    """Idempotently insert the curated models. Returns rows added."""
    existing = {
        (row.provider, row.model_id)
        for row in (await db.execute(select(ModelCatalogEntry))).scalars()
    }
    added = 0
    for seed in _seed_rows():
        if (seed["provider"], seed["model_id"]) in existing:
            continue
        db.add(
            ModelCatalogEntry(
                provider=seed["provider"],
                model_id=seed["model_id"],
                label=seed["model_id"],
                tier=seed["tier"],
                status="approved",
                enabled=True,
                source="seed",
            )
        )
        added += 1
    if added:
        try:
            await db.commit()
        except IntegrityError:
            # Two workers can race the read-then-insert on a fresh install
            # (the lazy seed runs inside a GET handler) — the loser hits the
            # unique constraint; the winner's rows are already there.
            await db.rollback()
            return 0
    return added


async def list_catalog(
    db: AsyncSession, status: str | None = None
) -> list[ModelCatalogEntry]:
    query = select(ModelCatalogEntry).order_by(
        ModelCatalogEntry.provider, ModelCatalogEntry.model_id
    )
    if status is not None:
        query = query.where(ModelCatalogEntry.status == status)
    return list((await db.execute(query)).scalars().all())


async def approved_models(db: AsyncSession) -> list[ModelCatalogEntry]:
    query = (
        select(ModelCatalogEntry)
        .where(
            ModelCatalogEntry.status == "approved",
            ModelCatalogEntry.enabled.is_(True),
        )
        .order_by(ModelCatalogEntry.provider, ModelCatalogEntry.model_id)
    )
    return list((await db.execute(query)).scalars().all())


async def get_entry(db: AsyncSession, model_id: str) -> ModelCatalogEntry | None:
    """The catalog row for a model id regardless of status, or None.

    When a row exists the catalog is authoritative for pickability — the
    in-memory whitelist is only a fallback for models the catalog has never
    seen (``ai_settings.service.update``)."""
    return (
        (
            await db.execute(
                select(ModelCatalogEntry).where(ModelCatalogEntry.model_id == model_id)
            )
        )
        .scalars()
        .first()
    )


async def is_model_allowed(db: AsyncSession, model_id: str) -> bool:
    """Approved+enabled catalog membership (union partner of the in-memory
    registry check in ``ai_settings.service.update``)."""
    row = (
        (
            await db.execute(
                select(ModelCatalogEntry).where(
                    ModelCatalogEntry.model_id == model_id,
                    ModelCatalogEntry.status == "approved",
                    ModelCatalogEntry.enabled.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )
    return row is not None


async def stored_multiplier(db: AsyncSession, model_id: str) -> float | None:
    """The catalog row's moderated multiplier, or None.

    Billing fallback for multi-worker deployments: an approval upserts the
    in-memory registry only in the worker that served it — the other
    workers read the moderated value from the DB row until their registries
    are replayed on restart. Deliberately ignores ``enabled``/``status`` —
    a tenant pinned to a later-disabled model keeps billing at the
    moderated price, never at a silent 1.0."""
    row = await get_entry(db, model_id)
    if row is None:
        return None
    return row.credit_multiplier


async def upsert_discovered(
    db: AsyncSession, provider: str, models: list[dict[str, str]]
) -> dict[str, int]:
    """Fold one provider's discovery result into the catalog.

    Never deletes: known ids only get a ``last_seen`` bump. New ids are
    classified as re-dated snapshots (auto-approved with the family's
    effective multiplier, or ``rejected`` when the family was rejected) or
    genuinely new models (pending under active billing). A snapshot whose
    approved family has no resolvable price is treated as a new model —
    auto-approving it would bill at a silent 1.0.
    """
    from app.modules.ai_settings import service as ai_settings_service

    result = await db.execute(
        select(ModelCatalogEntry).where(ModelCatalogEntry.provider == provider)
    )
    by_id = {row.model_id: row for row in result.scalars()}
    approved_by_normalized = _pick_family_rows(list(by_id.values()), "approved")
    rejected_by_normalized = _pick_family_rows(list(by_id.values()), "rejected")

    def _effective_family_multiplier(family: ModelCatalogEntry) -> float | None:
        """Moderated row value, else the registry price keyed on the family
        id (curated seed rows carry NULL — their price lives in
        credits.yaml under the dateless id)."""
        if family.credit_multiplier is not None:
            return family.credit_multiplier
        registry_entry = ai_settings_service._model_lookup(family.model_id)
        if registry_entry is not None:
            return float(registry_entry["credit_multiplier"])
        return None

    now = datetime.now(timezone.utc)
    stats = {"seen": 0, "new_versions": 0, "new_models": 0, "rejected": 0}
    for item in models:
        model_id = item.get("model_id")
        if not model_id:
            continue
        known = by_id.get(model_id)
        if known is not None:
            known.last_seen = now
            stats["seen"] += 1
            continue

        normalized = normalize_model_id(model_id, provider)
        family = approved_by_normalized.get(normalized)
        multiplier = (
            _effective_family_multiplier(family) if family is not None else None
        )
        if family is not None and (multiplier is not None or not billing_active()):
            # Re-dated snapshot of an approved model: inherit the family,
            # multiplier included, so the snapshot bills at the family price.
            entry = ModelCatalogEntry(
                provider=provider,
                model_id=model_id,
                label=item.get("label") or model_id,
                tier=family.tier,
                status="approved",
                enabled=family.enabled,
                credit_multiplier=multiplier,
                source="discovered",
                first_seen=now,
                last_seen=now,
            )
            stats["new_versions"] += 1
        elif family is None and rejected_by_normalized.get(normalized) is not None:
            # Snapshot of a rejected family: stays rejected — re-dating a
            # model the platform admin turned down is not a new decision.
            entry = ModelCatalogEntry(
                provider=provider,
                model_id=model_id,
                label=item.get("label") or model_id,
                tier=None,
                status="rejected",
                enabled=False,
                credit_multiplier=None,
                source="discovered",
                first_seen=now,
                last_seen=now,
            )
            stats["rejected"] += 1
        else:
            # Genuinely new model — or a snapshot whose family has no price
            # anywhere while billing is active (approving it would bill at a
            # silent 1.0); both go through moderation.
            pending = billing_active()
            entry = ModelCatalogEntry(
                provider=provider,
                model_id=model_id,
                label=item.get("label") or model_id,
                tier=None,
                status="pending" if pending else "approved",
                enabled=not pending,
                credit_multiplier=None,
                source="discovered",
                first_seen=now,
                last_seen=now,
            )
            stats["new_models"] += 1
            if pending:
                logger.info(
                    "model catalog: new %s model %s discovered — pending "
                    "platform-admin moderation",
                    provider,
                    model_id,
                )
        db.add(entry)
        by_id[model_id] = entry
        if entry.status == "approved":
            current = approved_by_normalized.get(normalized)
            if current is None or _family_rank(entry) > _family_rank(current):
                approved_by_normalized[normalized] = entry

    await db.commit()
    return stats


def to_read_dicts(rows: list[ModelCatalogEntry]) -> list[dict[str, Any]]:
    """Project approved rows for the /models endpoint.

    One entry per model family: re-dated snapshots collapse onto the
    ``_family_rank``-preferred row (canonical dateless id first), so a
    year of snapshots never fills the picker with duplicates — the DB
    keeps every row, only the projection dedups.

    Multiplier precedence: in-memory registry (curated credits.yaml or a
    moderation upsert) → the row's own moderated value → 1.0 (community,
    where multipliers are cosmetic). Under active billing an approved row
    with no multiplier anywhere is a config error — logged and withheld
    from the pickable list rather than billed at a silent default.
    """
    from app.modules.ai_settings import service as ai_settings_service

    best: dict[tuple[str, str], ModelCatalogEntry] = {}
    for row in rows:
        key = (row.provider, normalize_model_id(row.model_id, row.provider))
        current = best.get(key)
        if current is None or _family_rank(row) > _family_rank(current):
            best[key] = row
    deduped = sorted(best.values(), key=lambda r: (r.provider, r.model_id))

    out: list[dict[str, Any]] = []
    for row in deduped:
        registry_entry = ai_settings_service._model_lookup(row.model_id)
        multiplier: float | None
        label = row.label
        if registry_entry is not None:
            multiplier = float(registry_entry["credit_multiplier"])
            label = registry_entry.get("label") or label
        else:
            multiplier = row.credit_multiplier
        if multiplier is None:
            if billing_active():
                logger.warning(
                    "model catalog: approved model %s/%s has no credit "
                    "multiplier — withholding from the pickable list",
                    row.provider,
                    row.model_id,
                )
                continue
            multiplier = 1.0
        out.append(
            {
                "provider": row.provider,
                "model": row.model_id,
                "label": label,
                "credit_multiplier": multiplier,
            }
        )
    return out


async def run_discovery_sweep(db: AsyncSession) -> dict[str, Any]:
    """One full discovery pass over every provider with a configured key.

    Per-provider isolation: a provider API outage is logged and skipped —
    existing catalog rows are never touched, the other providers still
    refresh. Returns a per-provider summary for the task log.
    """
    from app.modules.ai import provider_discovery

    summary: dict[str, Any] = {}
    # The curated seed must exist before classification — re-dated snapshot
    # inheritance needs the approved family rows. A seed failure must not
    # kill the sweep: existing installs already carry the seed rows.
    try:
        await seed_from_registry(db)
        # On a no-op seed (every non-first run) the read above leaves an
        # autobegun transaction open, and the next thing this task does
        # is provider HTTP calls — idle-in-transaction there gets killed
        # by the server-side timeout on a slow provider (cf. HRP-432).
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — sweep must survive a DB hiccup
        logger.warning(
            "model catalog: seed failed (%s: %s); continuing with discovery",
            type(exc).__name__,
            exc,
        )
        await db.rollback()
    for provider, api_key in provider_discovery.discoverable_providers():
        try:
            models = await provider_discovery.discover(provider, api_key)
            summary[provider] = await upsert_discovered(db, provider, models)
        except Exception as exc:  # noqa: BLE001 — per-provider isolation
            logger.warning(
                "model catalog: %s discovery failed (%s: %s); keeping existing rows",
                provider,
                type(exc).__name__,
                exc,
            )
            summary[provider] = {"error": type(exc).__name__}
            # A failed upsert leaves the session dirty — reset before the
            # next provider so one bad batch can't poison the whole sweep.
            await db.rollback()
            continue
    return summary


async def sync_registry_from_catalog(db: AsyncSession) -> int:
    """Replay moderation-approved multipliers into the in-memory whitelist.

    Called from the app lifespan on boot: approvals upsert the registry
    immediately, but the in-memory copy dies with the process — this
    restores the fast billing path from the DB rows. Returns entries synced.
    """
    from app.modules.ai_settings import service as ai_settings_service

    synced = 0
    for row in await approved_models(db):
        if row.credit_multiplier is None:
            continue
        if ai_settings_service._model_lookup(row.model_id) is not None:
            # Curated entries (credits.yaml / community presets) win.
            continue
        ai_settings_service.upsert_allowed_model(
            {
                "provider": row.provider,
                "model": row.model_id,
                "label": row.label,
                "credit_multiplier": row.credit_multiplier,
            }
        )
        synced += 1
    return synced
