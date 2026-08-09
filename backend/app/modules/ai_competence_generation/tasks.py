"""Celery worker for `CompetenceGenerationSession`.

Loads a `pending` session, builds the prompt for its scope, calls the LLM
with a strict JSON-Schema constraint, normalises the payload (assigns a
`temp_id` to every node so the frontend can address selection state),
and stores it back on the row. Notification is sent on every terminal
state — `ready` for success, `error` for failure.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core import billing_hooks
from app.core.celery_app import celery
from app.core.llm_sanitize import sanitize_user_refinement
from app.database import make_async_engine
from app.modules.ai import model_registry

if TYPE_CHECKING:
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )

logger = logging.getLogger(__name__)


async def _broadcast_session_update(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Best-effort fan-out of an AI-session status change via Redis pub/sub.

    Imported lazily to keep this module testable without FastAPI import side-effects.
    """
    try:
        from app.core.websocket import manager

        payload: dict[str, Any] = {
            "type": "compgen.session.updated",
            "payload": {
                "session_id": str(session_id),
                "status": status,
            },
        }
        if error_code:
            payload["payload"]["error_code"] = error_code
        if error_message:
            payload["payload"]["error_message"] = error_message
        await manager.publish_to_user(str(tenant_id), str(user_id), payload)
    except Exception:
        logger.exception("compgen ws broadcast failed")


# HRP-71 phase 4: chunked progress events. Architecturally synthetic — one
# LLM round-trip remains, but after parse we know totals and broadcast them
# in the order the UI checklist expects (grades → competences → indicators
# → matrix). The indicator phase fans out one event per item with a tiny
# sleep so the counter animates 1/N → N/N instead of jumping. Configurable
# via `settings.ai_progress_step_delay_s` (env: AI_PROGRESS_STEP_DELAY_S);
# set to 0 to disable for big matrices where the animation becomes a drag.
PROGRESS_INDICATOR_STEP_DELAY_S = settings.ai_progress_step_delay_s


async def _broadcast_progress(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    phase: str,
    *,
    total: int | None = None,
    current: int | None = None,
) -> None:
    """Emit a `compgen.progress` event for the streaming checklist UI."""
    try:
        from app.core.websocket import manager

        payload: dict[str, Any] = {
            "type": "compgen.progress",
            "payload": {
                "session_id": str(session_id),
                "phase": phase,
            },
        }
        if total is not None:
            payload["payload"]["total"] = total
        if current is not None:
            payload["payload"]["current"] = current
        await manager.publish_to_user(str(tenant_id), str(user_id), payload)
    except Exception:
        logger.exception("compgen progress broadcast failed")


def _count_payload_totals(
    payload: dict[str, Any], scope: str, base_snapshot: dict[str, Any] | None
) -> tuple[int, int, int]:
    """Return (grades, competences, indicators) totals for a parsed payload.

    `grades` is meaningful only for `specialization_matrix` (read from the
    base snapshot the session captured at create time — the LLM doesn't
    repeat the grade list, it's an input). `competences`/`indicators` come
    from the freshly parsed tree.
    """
    grades_total = 0
    if scope == "specialization_matrix" and base_snapshot:
        spec = (base_snapshot or {}).get("specialization") or {}
        grades_total = len(spec.get("grades") or [])

    competences_total = 0
    indicators_total = 0

    def visit_group(g: dict[str, Any]) -> None:
        nonlocal competences_total, indicators_total
        for ch in g.get("children", []) or []:
            visit_group(ch)
        for c in g.get("competences", []) or []:
            competences_total += 1
            indicators_total += len(c.get("indicators") or [])

    for g in payload.get("groups", []) or []:
        visit_group(g)
    indicators_total += len(payload.get("indicators", []) or [])
    return grades_total, competences_total, indicators_total


async def _stream_progress_after_parse(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: dict[str, Any],
    scope: str,
    base_snapshot: dict[str, Any] | None,
) -> None:
    """Replay the parsed payload as a sequence of progress events.

    Order matches the UI checklist: grades (matrix only) → competences →
    indicators (one tick per item) → matrix (matrix only). Each event is
    fire-and-forget; failures are logged but don't sink the apply path.
    """
    grades, comps, inds = _count_payload_totals(payload, scope, base_snapshot)

    if scope == "specialization_matrix":
        await _broadcast_progress(
            tenant_id, user_id, session_id, "grades", total=grades, current=grades
        )
    await _broadcast_progress(
        tenant_id, user_id, session_id, "competences", total=comps, current=comps
    )
    if inds > 0:
        for current in range(1, inds + 1):
            await _broadcast_progress(
                tenant_id,
                user_id,
                session_id,
                "indicators",
                total=inds,
                current=current,
            )
            if current < inds:
                await asyncio.sleep(PROGRESS_INDICATOR_STEP_DELAY_S)
    else:
        await _broadcast_progress(
            tenant_id, user_id, session_id, "indicators", total=0, current=0
        )
    if scope == "specialization_matrix":
        await _broadcast_progress(
            tenant_id, user_id, session_id, "matrix", total=comps, current=comps
        )


def _run_with_async_session(
    coro_factory: Callable[[async_sessionmaker[AsyncSession]], Awaitable[Any]],
) -> Any:
    """Same short-lived-engine pattern used by app.modules.ai.tasks."""

    async def _inner() -> Any:
        engine = make_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            return await coro_factory(session_factory)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Normalisation: assign temp_id to every node so the UI can target selection
# ---------------------------------------------------------------------------


def _normalise_tree(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    """Walk the tree, attach `temp_id` everywhere, build default selection."""
    selection: dict[str, bool] = {}

    def visit_group(group: dict[str, Any]) -> None:
        gid = uuid.uuid4().hex
        group["temp_id"] = gid
        selection[gid] = True
        for child in group.get("children", []) or []:
            visit_group(child)
        for comp in group.get("competences", []) or []:
            cid = uuid.uuid4().hex
            comp["temp_id"] = cid
            selection[cid] = True
            for ind in comp.get("indicators", []) or []:
                iid = uuid.uuid4().hex
                ind["temp_id"] = iid
                selection[iid] = True

    for group in payload.get("groups", []) or []:
        visit_group(group)
    return payload, selection


def _normalise_indicators(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    selection: dict[str, bool] = {}
    for ind in payload.get("indicators", []) or []:
        iid = uuid.uuid4().hex
        ind["temp_id"] = iid
        selection[iid] = True
    return payload, selection


def _annotate_group_augment_snapshot(
    payload: dict[str, Any],
    base_snapshot: dict[str, Any],
    selection: dict[str, bool],
) -> None:
    """HRP-155: tag nodes that match existing items in ``base_snapshot``.

    When the operator turned on augment mode for a ``group`` session the
    LLM is allowed to echo existing subgroups / competences alongside the
    new ones. Matching is title-based (case-insensitive, trimmed) — the
    schema forbids the LLM from inventing ``snapshot_id`` itself, and
    UUIDs round-trip poorly through LLM output anyway.

    Matched nodes receive a ``snapshot_id`` pointing at the real DB row.
    The frontend (HRP-123/124) reads ``snapshot_id`` to render the locked
    "existing" badge; the apply step (`_apply_competence`) reuses the
    underlying competence row instead of creating a duplicate and skips
    indicators whose ``snapshot_id`` is already set.

    Indicator-level matching also flips ``selection[temp_id]`` to ``False``
    for any indicator that was already in the DB so the selection counter
    reflects "only new indicators by default".
    """

    def index_by_title(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Map title → snapshot item, dropping ambiguous titles entirely.

        When two siblings share the exact same title (rare but possible
        when groups got duplicated by hand), title-only matching would
        silently bind the LLM's echo to the wrong DB row. Skipping both
        sides degrades the augment to a fresh-suggestion under that
        title — a duplicate at worst, never a mis-attribution.
        """
        seen: dict[str, dict[str, Any]] = {}
        ambiguous: set[str] = set()
        for item in items or []:
            title = (item.get("title") or "").strip().lower()
            if not title or "id" not in item:
                continue
            if title in seen:
                ambiguous.add(title)
                continue
            seen[title] = item
        for title in ambiguous:
            seen.pop(title, None)
        return seen

    def annotate_indicators(
        gen_comp: dict[str, Any], snap_comp: dict[str, Any]
    ) -> None:
        snap_ind_by_key = {
            (
                (i.get("title") or "").strip().lower(),
                (i.get("skill_level") or "").strip().lower(),
            ): i
            for i in (snap_comp.get("indicators") or [])
        }
        for ind in gen_comp.get("indicators", []) or []:
            key = (
                (ind.get("title") or "").strip().lower(),
                (ind.get("skill_level") or "").strip().lower(),
            )
            match = snap_ind_by_key.get(key)
            if match is None:
                continue
            snap_id = match.get("id")
            if snap_id:
                ind["snapshot_id"] = str(snap_id)
                tid = ind.get("temp_id")
                if tid in selection:
                    selection[tid] = False

    def walk_group(
        gen_group: dict[str, Any], snap_group: dict[str, Any] | None
    ) -> None:
        if snap_group is None:
            return
        snap_id = snap_group.get("id")
        if snap_id:
            gen_group["snapshot_id"] = str(snap_id)
        snap_comps_by_title = index_by_title(snap_group.get("competences", []))
        for comp in gen_group.get("competences", []) or []:
            title = (comp.get("title") or "").strip().lower()
            snap_comp = snap_comps_by_title.get(title)
            if snap_comp is None:
                continue
            comp_snap_id = snap_comp.get("id")
            if comp_snap_id:
                comp["snapshot_id"] = str(comp_snap_id)
            annotate_indicators(comp, snap_comp)
        snap_children_by_title = index_by_title(snap_group.get("children", []))
        for child in gen_group.get("children", []) or []:
            ctitle = (child.get("title") or "").strip().lower()
            walk_group(child, snap_children_by_title.get(ctitle))

    # ``base_snapshot`` for the group scope is shaped as
    # ``{"group": {"id", "title", "competences", "descendants"}}``. The
    # ``descendants`` list mirrors the nested children of the group, which
    # is what the LLM sees as sub-tree context. Build a combined map so the
    # walker has one source of truth.
    snap_group = base_snapshot.get("group") if base_snapshot else None
    if not isinstance(snap_group, dict):
        return
    snap_root: dict[str, Any] = {
        "id": snap_group.get("id"),
        "title": snap_group.get("title"),
        "competences": snap_group.get("competences") or [],
        "children": snap_group.get("descendants") or [],
    }
    snap_root_title = (snap_root.get("title") or "").strip().lower()
    snap_top_by_title = {snap_root_title: snap_root} if snap_root_title else {}
    for top_group in payload.get("groups", []) or []:
        title = (top_group.get("title") or "").strip().lower()
        walk_group(top_group, snap_top_by_title.get(title))


# ---------------------------------------------------------------------------
# Retry helper — local to CR11 because we want explicit error_code mapping
# ---------------------------------------------------------------------------


async def _generate_with_retries(
    *,
    user_prompt: str,
    system: str,
    schema: type[BaseModel],
    tenant_settings: Any,
    max_attempts: int,
    max_tokens: int | None = None,
    credentials: Any = None,
    model: str | None = None,
) -> tuple[BaseModel, str | None]:
    """Returns (model_instance, error_code_or_None). Bounded exponential backoff.

    Distinguishes parse/validation errors (deterministic — no point hammering
    the same prompt) from transient provider errors (worth a delay).

    ``max_tokens`` overrides the LLM output budget. HRP-122: tree-shaped
    payloads (whole_base, group, matrix) truncate at the SDK default 8192
    and surface as ``parse_error`` because the partial JSON fails schema
    validation. Callers derive a scope-aware budget via
    ``_max_tokens_for_scope`` and forward it here.
    """
    from app.modules.ai import llm_client

    last_exc: Exception | None = None
    last_code: str | None = None
    generate_kwargs: dict[str, Any] = {
        "system": system,
        "tenant_settings": tenant_settings,
        "schema": schema,
        "credentials": credentials,
        # HRP-500 (review #5): resolved through the catalog by the caller,
        # which holds the session — passing ``credentials`` alone left the
        # kill-switch unapplied on this Celery path while billing already
        # priced the substitute.
        "model": model,
    }
    if max_tokens is not None:
        generate_kwargs["max_tokens"] = max_tokens
    for attempt in range(max_attempts):
        try:
            result = await llm_client.generate_json(user_prompt, **generate_kwargs)
            assert isinstance(result, BaseModel)
            return result, None
        except llm_client.LLMOutputTruncatedError as exc:
            # Truncation is deterministic for a given prompt+budget, and the
            # budget is already at the per-model ceiling — retrying can only
            # burn the same tokens again. Fail fast with a dedicated code so
            # the UI can suggest narrowing the scope instead of "try later".
            raise RuntimeError("output_truncated") from exc
        except (ValidationError, ValueError) as exc:
            last_exc = exc
            last_code = "parse_error"
            logger.warning(
                "compgen LLM parse failed (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                exc,
            )
        except Exception as exc:  # provider/network/etc  # noqa: BLE001
            last_exc = exc
            last_code = "service_error"
            logger.warning(
                "compgen LLM call failed (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                exc,
            )
            await asyncio.sleep(min(2**attempt, 30))

    raise RuntimeError(last_code or "service_error") from last_exc


# HRP-122: output-token budget per scope. The SDK default 8192 truncates
# whole_base / group / matrix tree responses mid-JSON, surfacing as
# ``parse_error`` even when the model is producing valid content. Tree
# scopes ask for the sonnet-class ceiling (a live Cyrillic whole-base tree
# overflowed the previous 16384 budget) and rely on llm_client's per-model
# clamps (Haiku 8192, Opus 32000, gpt-4o 16384, non-2.5 Gemini 8192) to
# keep the request valid for cheaper presets. competence_indicators stays
# at the default — its output is bounded by the number of skill levels ×
# 3-5 indicators each, well under 8192.
_TREE_SCOPE_MAX_TOKENS = model_registry.ANTHROPIC_OUTPUT_CAPS[
    model_registry.ANTHROPIC_BALANCED
]
_MAX_TOKENS_BY_SCOPE: dict[str, int] = {
    "whole_base": _TREE_SCOPE_MAX_TOKENS,
    "group": _TREE_SCOPE_MAX_TOKENS,
    "specialization_matrix": _TREE_SCOPE_MAX_TOKENS,
    "competence_indicators": 8192,
}


def _max_tokens_for_scope(scope: str) -> int:
    return _MAX_TOKENS_BY_SCOPE.get(scope, 8192)


# HRP-122: with ``worker_prefetch_multiplier=1`` the scheduled
# ``write_celery_heartbeat`` task sits queued behind a long compgen run —
# the heartbeat key TTLs out after 90s, ``/health/celery`` flips to 503,
# and ``useCeleryHealth`` shows "Background worker offline" while the
# worker is actually busy producing the very payload the user is waiting
# for. The fallback control-channel ping (HRP-46) helps but isn't always
# fast enough under load. Refreshing the heartbeat key from inside this
# task closes the gap: every 20s, regardless of beat queue depth.
HEARTBEAT_KEY = "status:celery:heartbeat"
HEARTBEAT_TTL_S = 90
HEARTBEAT_REFRESH_INTERVAL_S = 20


# ---------------------------------------------------------------------------
# HRP-143: per-item context_excludes helpers
# ---------------------------------------------------------------------------


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    """Parse a string/UUID into a UUID, returning None on garbage.
    Used by the pruning helpers where snapshot ids may be either str or UUID."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _fetch_related_specs_for_group(
    db: AsyncSession, tenant_id: uuid.UUID, group_snapshot: dict[str, Any]
) -> list[dict[str, str]]:
    """HRP-114: pull every competence id under a group snapshot and ask
    ``_fetch_related_specializations`` for the subset of tenant specs that
    reference any of them through a matrix link."""
    from app.modules.ai_competence_generation.service import (
        _collect_competence_ids_in_group,
        _fetch_related_specializations,
    )

    ids = _collect_competence_ids_in_group(group_snapshot)
    return await _fetch_related_specializations(db, tenant_id, competence_ids=ids)


async def _fetch_related_specs_for_competence(
    db: AsyncSession, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> list[dict[str, str]]:
    """HRP-114: related specializations for a single competence (indicators
    scope). Thin wrapper over the shared service-layer query so the worker
    doesn't grow its own SQL surface."""
    from app.modules.ai_competence_generation.service import (
        _fetch_related_specializations,
    )

    return await _fetch_related_specializations(
        db, tenant_id, competence_ids=[competence_id]
    )


def _prune_descendants(
    nodes: list[dict[str, Any]],
    excluded_group_ids: set[uuid.UUID],
    excluded_competence_ids: set[uuid.UUID],
) -> list[dict[str, Any]]:
    """HRP-114: drop descendant groups / competences whose ids appear in
    the per-item excludes. Shape mirrors ``_fetch_group_descendants``: a
    list of ``{id, title, children, competences}`` dicts."""
    out: list[dict[str, Any]] = []
    for node in nodes:
        if _coerce_uuid(node.get("id")) in excluded_group_ids:
            continue
        out.append(
            {
                **node,
                "children": _prune_descendants(
                    node.get("children", []) or [],
                    excluded_group_ids,
                    excluded_competence_ids,
                ),
                "competences": [
                    c
                    for c in (node.get("competences", []) or [])
                    if _coerce_uuid(c.get("id")) not in excluded_competence_ids
                ],
            }
        )
    return out


def _parse_per_item_excludes(excludes: set[str], *, prefix: str) -> set[uuid.UUID]:
    """Pluck ``"<prefix><uuid>"`` keys out of ``excludes`` into a UUID set.

    HRP-143: the preflight modal sends granular keys like
    ``"specialization:<uuid>"`` alongside the category-wide
    ``"specializations"`` toggle. We parse those here so the LLM-context
    fetchers can do ``id not in excluded_xxx_ids`` cleanly.
    """
    out: set[uuid.UUID] = set()
    for key in excludes:
        if not key.startswith(prefix):
            continue
        parsed = _coerce_uuid(key[len(prefix) :])
        if parsed is not None:
            out.add(parsed)
    return out


def _open_heartbeat_redis() -> Any:
    """Lazy redis client factory — separate function so tests can patch it
    without monkey-patching ``sys.modules`` (which is fragile when
    ``redis.asyncio`` is already cached by other imports).
    """
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url)


# HRP-163 review: how often the heartbeat pulser touches the session row.
# Picked at ~1/15th of the reaper cutoff so even one missed refresh leaves
# 14 minutes of safety margin before a healthy worker can be reaped.
SESSION_TOUCH_INTERVAL_S = 60


async def _heartbeat_pulse(
    stop_event: asyncio.Event,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    """Keep ``status:celery:heartbeat`` fresh while ``execute_session`` runs.

    HRP-163 review: also touches the owning session row so the reap-stuck
    beat job (``reap_stuck_sessions``) only fires on workers that have
    actually died. Without this, a long LLM round-trip never updates
    ``updated_at`` between the ``status='running'`` flip and the final
    commit — the reaper would happily kill it after 15 minutes.

    The session touch runs at a slower cadence than the Redis ping
    (`SESSION_TOUCH_INTERVAL_S` vs `HEARTBEAT_REFRESH_INTERVAL_S`) to
    avoid contention on the row while the main worker session is also
    holding it.
    """
    try:
        r = _open_heartbeat_redis()
    except Exception:
        logger.exception("compgen heartbeat: redis driver unavailable")
        return

    last_touch = datetime.now(timezone.utc)

    async def _touch_session_row() -> None:
        from sqlalchemy import update

        from app.modules.ai_competence_generation.models import (
            CompetenceGenerationSession,
        )

        if session_factory is None or session_id is None:
            return
        try:
            async with session_factory() as touch_db:
                await touch_db.execute(
                    update(CompetenceGenerationSession)
                    .where(CompetenceGenerationSession.id == session_id)
                    .values(updated_at=datetime.now(timezone.utc))
                )
                await touch_db.commit()
        except Exception:
            logger.exception(
                "compgen heartbeat: session row touch failed for %s", session_id
            )

    try:
        while not stop_event.is_set():
            try:
                await r.set(
                    HEARTBEAT_KEY,
                    datetime.now(timezone.utc).isoformat(),
                    ex=HEARTBEAT_TTL_S,
                )
            except Exception:
                logger.exception("compgen heartbeat refresh failed")
            now = datetime.now(timezone.utc)
            if (now - last_touch).total_seconds() >= SESSION_TOUCH_INTERVAL_S:
                await _touch_session_row()
                last_touch = now
            with contextlib.suppress(TimeoutError):
                # Normal: interval elapsed, loop again.
                await asyncio.wait_for(
                    stop_event.wait(), timeout=HEARTBEAT_REFRESH_INTERVAL_S
                )
    finally:
        try:
            await r.aclose()
        except Exception:
            logger.exception("compgen heartbeat: redis close failed")


# ---------------------------------------------------------------------------
# Per-scope prompt building — extracted verbatim from _execute_session_body
# (project review 2026-07-01, item 23) so each scope reads as one unit
# ---------------------------------------------------------------------------


@dataclass
class _SessionContext:
    """Per-run state shared by the scope prompt builders.

    Bundles the worker DB session, the session row and the parsed
    ``params``-derived values (refinement, context excludes) so the
    per-scope builders take one argument instead of a dozen locals.
    """

    db: AsyncSession
    sess: CompetenceGenerationSession
    tenant_id: uuid.UUID
    with_indicators: bool
    refinement: str | None
    context_excludes: set[str]
    excluded_specialization_ids: set[uuid.UUID]
    excluded_division_ids: set[uuid.UUID]
    excluded_group_ids: set[uuid.UUID]
    excluded_competence_ids: set[uuid.UUID]
    excluded_position_ids: set[uuid.UUID]
    excluded_related_specialization_ids: set[uuid.UUID]
    excluded_ancestor_ids: set[uuid.UUID]
    excluded_descendant_ids: set[uuid.UUID]
    base_snapshot: dict[str, Any]

    # HRP-114: tenant-wide context fetch shared by whole_base / group /
    # competence_indicators. Each category respects context_excludes —
    # excluded keys return an empty value so the prompt skips them.
    # HRP-143: per-item exclusions trim items out of the category list
    # without disabling the category entirely.
    async def fetch_tenant_specializations(self) -> list[str]:
        if "specializations" in self.context_excludes:
            return []
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.dictionary.service import effective_is_active_expr

        spec_q = await self.db.execute(
            select(DictionaryItem.id, DictionaryItem.title).where(
                DictionaryItem.type == "specialization",
                effective_is_active_expr(self.tenant_id).is_(True),
                (DictionaryItem.tenant_id == self.tenant_id)
                | DictionaryItem.tenant_id.is_(None),
            )
        )
        return [
            title
            for (sid, title) in spec_q.all()
            if sid not in self.excluded_specialization_ids
        ]

    async def fetch_tenant_divisions(self) -> list[str]:
        if "divisions" in self.context_excludes:
            return []
        from app.modules.company.models import Division

        div_q = await self.db.execute(
            select(Division.id, Division.name).where(
                Division.tenant_id == self.tenant_id
            )
        )
        return [
            name for (did, name) in div_q.all() if did not in self.excluded_division_ids
        ]

    async def fetch_tenant_company(self) -> str | None:
        if "company" in self.context_excludes:
            return None
        from app.modules.company.models import Tenant

        tenant = await self.db.get(Tenant, self.tenant_id)
        return (tenant.description or tenant.name) if tenant else None

    def prune_source_tree(self, tree: dict[str, Any]) -> dict[str, Any]:
        """HRP-143: drop groups/competences whose ids appear in the
        per-item excludes. Tree shape preserved; only matching nodes
        (and their descendants for groups) are removed. Handles both
        whole_base snapshots (``{"groups": [...]}``) and group-scope
        snapshots (``{"group": {...}}``).
        """
        if not self.excluded_group_ids and not self.excluded_competence_ids:
            return tree

        def filter_group(g: dict[str, Any]) -> dict[str, Any] | None:
            if _coerce_uuid(g.get("id")) in self.excluded_group_ids:
                return None
            return {
                **g,
                "children": [
                    child
                    for child in (filter_group(c) for c in g.get("children", []) or [])
                    if child is not None
                ],
                "competences": [
                    c
                    for c in (g.get("competences", []) or [])
                    if _coerce_uuid(c.get("id")) not in self.excluded_competence_ids
                ],
            }

        if "group" in tree and isinstance(tree["group"], dict):
            pruned = filter_group(tree["group"])
            return {"group": pruned} if pruned is not None else {}
        if "groups" in tree:
            return {
                "groups": [
                    fg
                    for fg in (filter_group(g) for g in (tree.get("groups") or []))
                    if fg is not None
                ],
            }
        return tree


def _build_session_context(
    db: AsyncSession, sess: CompetenceGenerationSession
) -> _SessionContext:
    """Parse ``sess.params`` into the shared prompt-building context.

    HRP-163: ``refinement`` is stripped of injection markers + truncated
    before the prompt builders ever see the value. Defence-in-depth — the
    schemas already trim whitespace, but they don't (and shouldn't) touch
    content.

    HRP-123 / HRP-143: the preflight modal lets the user drop context
    before the LLM call. The list mixes two kinds of keys:
    - Category-wide: ``specializations`` / ``divisions`` / ``company``
      / ``source_tree`` / ``existing_indicators`` / ``sibling_competences``
      — drop the whole category.
    - Per-item (HRP-143): ``specialization:<uuid>`` / ``division:<uuid>``
      / ``group:<uuid>`` / ``competence:<uuid>`` — drop a single entry
      inside a category that's otherwise included.
    Lowercased on parse so the filter is case-insensitive; per-item ids
    stay UUID-shaped because UUIDs round-trip through ``lower()``.
    """
    params = sess.params or {}
    context_excludes = {str(k).lower() for k in (params.get("context_excludes") or [])}
    return _SessionContext(
        db=db,
        sess=sess,
        tenant_id=sess.tenant_id,
        with_indicators=bool(params.get("with_indicators", True)),
        refinement=sanitize_user_refinement(params.get("refinement_prompt")),
        context_excludes=context_excludes,
        excluded_specialization_ids=_parse_per_item_excludes(
            context_excludes, prefix="specialization:"
        ),
        excluded_division_ids=_parse_per_item_excludes(
            context_excludes, prefix="division:"
        ),
        excluded_group_ids=_parse_per_item_excludes(context_excludes, prefix="group:"),
        excluded_competence_ids=_parse_per_item_excludes(
            context_excludes, prefix="competence:"
        ),
        # HRP-159: per-item exclusions for the specialization_matrix scope.
        excluded_position_ids=_parse_per_item_excludes(
            context_excludes, prefix="position:"
        ),
        # HRP-114: per-item exclusions for the group / indicators scopes.
        excluded_related_specialization_ids=_parse_per_item_excludes(
            context_excludes, prefix="related_specialization:"
        ),
        excluded_ancestor_ids=_parse_per_item_excludes(
            context_excludes, prefix="ancestor:"
        ),
        excluded_descendant_ids=_parse_per_item_excludes(
            context_excludes, prefix="descendant:"
        ),
        base_snapshot=sess.base_snapshot or {},
    )


@dataclass
class _BuiltPrompt:
    """A scope builder's success result — everything the LLM call needs."""

    system: str
    user_prompt: str
    schema_cls: type[BaseModel]


@dataclass
class _PromptFailure:
    """A scope builder bailed out; the caller must ``_terminate`` with these."""

    error_code: str
    message: str


async def _build_prompt_whole_base(ctx: _SessionContext) -> _BuiltPrompt:
    from app.modules.ai_competence_generation import prompts
    from app.modules.ai_competence_generation.schemas import GeneratedTreeSchema

    specializations = await ctx.fetch_tenant_specializations()
    divisions = await ctx.fetch_tenant_divisions()
    company = await ctx.fetch_tenant_company()

    # HRP-124: in augment mode the user can drop the existing tree
    # from the prompt — useful when they want fresh suggestions that
    # aren't filtered through "Never duplicate the source tree".
    # HRP-143: per-item ``group:<id>`` / ``competence:<id>`` keys
    # trim individual subtrees / competences without dropping the
    # whole library.
    source_tree: dict[str, Any] = (
        {}
        if "source_tree" in ctx.context_excludes
        else ctx.prune_source_tree(ctx.base_snapshot)
    )

    system, user_prompt = prompts.build_tree_prompt(
        specializations=specializations,
        divisions=divisions,
        projects=[],
        company=company,
        source_tree=source_tree,
        with_indicators=ctx.with_indicators,
        refinement=ctx.refinement,
    )
    return _BuiltPrompt(system, user_prompt, GeneratedTreeSchema)


async def _build_prompt_specialization_matrix(
    ctx: _SessionContext,
) -> _BuiltPrompt | _PromptFailure:
    from app.modules.ai_competence_generation import prompts
    from app.modules.ai_competence_generation.schemas import GeneratedMatrixSchema
    from app.modules.company.models import Division, Tenant
    from app.modules.competence.models import Competence, SkillLevel
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )
    from app.modules.position.models import Position

    db = ctx.db
    sess = ctx.sess
    tenant_id = ctx.tenant_id
    context_excludes = ctx.context_excludes
    base_snapshot = ctx.base_snapshot

    if sess.target_id is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="matrix session has no target_id",
        )
    spec = await db.get(DictionaryItem, sess.target_id)
    if spec is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="target specialization missing",
        )

    level_q = await db.execute(
        select(SkillLevel.title)
        .where(
            SkillLevel.is_active.is_(True),
            (SkillLevel.tenant_id == tenant_id) | (SkillLevel.tenant_id.is_(None)),
        )
        .order_by(SkillLevel.sort_index)
    )
    levels = [t for (t,) in level_q.all()]

    spec_block = base_snapshot.get("specialization", {}) if base_snapshot else {}
    grade_titles = [
        g.get("grade_title", "")
        for g in spec_block.get("grades", [])
        if g.get("grade_title")
    ]
    # HRP-33: without grades the LLM gets a degenerate prompt
    # (`grades: []`, no `grade_levels` keys to fill) and either
    # truncates, returns prose, or invents fields — burning all 5
    # retries for nothing. Bail out early with a clear code so the
    # UI can prompt the user to set up grades instead of showing
    # the generic "failed after 5 attempts" message.
    if not grade_titles:
        return _PromptFailure(
            error_code="insufficient_data",
            message=(
                "No grades configured for this specialization. "
                "Add at least one grade before AI generation."
            ),
        )

    tenant = await db.get(Tenant, tenant_id)
    company = (
        None
        if "company" in context_excludes
        else ((tenant.description or tenant.name) if tenant else None)
    )

    params_full = sess.params or {}

    # HRP-159: structured context blocks the preflight modal can
    # trim. Each block is fetched in full and then per-item /
    # category excludes are applied — empty blocks drop out of the
    # prompt entirely.
    positions_payload: list[dict[str, Any]] = []
    if "positions" not in context_excludes:
        pos_q = await db.execute(
            select(Position.id, Position.title, Position.description)
            .where(
                Position.tenant_id == tenant_id,
                Position.specialization_id == sess.target_id,
                Position.is_active.is_(True),
            )
            .order_by(Position.title)
        )
        for pid, ptitle, pdesc in pos_q.all():
            if pid in ctx.excluded_position_ids:
                continue
            positions_payload.append(
                {
                    "title": ptitle,
                    "description": pdesc,
                }
            )

    matrix_divisions_payload: list[str] = []
    if "divisions" not in context_excludes:
        div_q = await db.execute(
            select(Division.id, Division.name).where(Division.tenant_id == tenant_id)
        )
        matrix_divisions_payload = [
            name for (did, name) in div_q.all() if did not in ctx.excluded_division_ids
        ]

    existing_competences_payload: list[dict[str, str]] = []
    if "existing_competences" not in context_excludes:
        comp_q = await db.execute(
            select(Competence.id, Competence.title, Competence.description)
            .join(
                GradeCompetenceLink,
                GradeCompetenceLink.competence_id == Competence.id,
            )
            .join(
                GradeSpecialization,
                GradeSpecialization.id == GradeCompetenceLink.grade_specialization_id,
            )
            .where(
                GradeSpecialization.specialization_id == sess.target_id,
                GradeSpecialization.tenant_id == tenant_id,
                Competence.is_active.is_(True),
            )
            .distinct()
        )
        for cid, ctitle, cdesc in comp_q.all():
            if cid in ctx.excluded_competence_ids:
                continue
            existing_competences_payload.append(
                {"title": ctitle, "description": cdesc or ""}
            )

    spec_description = (
        None if "specialization_description" in context_excludes else spec.description
    )

    # HRP-163 review: the matrix wizard ships six free-form fields
    # straight into the prompt builder. Each one is a 4 KB user
    # input — same prompt-injection surface as `refinement`, just
    # bigger. Scrub them the same way.
    system, user_prompt = prompts.build_specialization_matrix_prompt(
        specialization=spec.title,
        specialization_description=spec_description,
        grades=grade_titles,
        skill_levels=levels,
        company=company,
        existing_matrix=spec_block,
        responsibilities=sanitize_user_refinement(params_full.get("responsibilities")),
        daily_tasks=sanitize_user_refinement(params_full.get("daily_tasks")),
        weekly_tasks=sanitize_user_refinement(params_full.get("weekly_tasks")),
        kpi=sanitize_user_refinement(params_full.get("kpi")),
        requirements_text=sanitize_user_refinement(
            params_full.get("requirements_text")
        ),
        parsed_files=sanitize_user_refinement(params_full.get("parsed_files")),
        refinement=ctx.refinement,
        # HRP-119 AC2: caller flips this on when the existing matrix
        # is non-empty and the operator wants additional indicators
        # for every competence already in it.
        indicators_for_existing=bool(params_full.get("indicators_for_existing", False)),
        positions=positions_payload or None,
        divisions=matrix_divisions_payload or None,
        existing_competences=existing_competences_payload or None,
    )
    return _BuiltPrompt(system, user_prompt, GeneratedMatrixSchema)


async def _build_prompt_group(
    ctx: _SessionContext,
) -> _BuiltPrompt | _PromptFailure:
    from app.modules.ai_competence_generation import prompts
    from app.modules.ai_competence_generation.schemas import GeneratedTreeSchema
    from app.modules.competence.models import CompetenceGroup

    db = ctx.db
    sess = ctx.sess
    context_excludes = ctx.context_excludes
    base_snapshot = ctx.base_snapshot

    if sess.target_id is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="group session has no target_id",
        )
    grp = await db.get(CompetenceGroup, sess.target_id)
    if grp is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="target group missing",
        )
    # HRP-114: tenant context + source_tree are toggleable from the
    # preflight modal. `source_tree` empty drops the snapshot of
    # the group's existing competences from the prompt.
    specializations = await ctx.fetch_tenant_specializations()
    divisions = await ctx.fetch_tenant_divisions()
    company = await ctx.fetch_tenant_company()
    group_source_tree: dict[str, Any] = (
        {}
        if "source_tree" in context_excludes
        else ctx.prune_source_tree(base_snapshot)
    )
    # HRP-114: related specializations + surrounding tree context
    # (ancestors / descendants). Each is filtered through
    # context_excludes (category + per-item).
    grp_snapshot = base_snapshot.get("group") or {}
    related_specs_raw = await _fetch_related_specs_for_group(
        db, ctx.tenant_id, grp_snapshot
    )
    related_specializations = (
        []
        if "related_specializations" in context_excludes
        else [
            s["title"]
            for s in related_specs_raw
            if _coerce_uuid(s["id"]) not in ctx.excluded_related_specialization_ids
        ]
    )
    ancestors_raw = grp_snapshot.get("ancestors") or []
    ancestors_titles = (
        []
        if "ancestors" in context_excludes
        else [
            a["title"]
            for a in ancestors_raw
            if _coerce_uuid(a.get("id")) not in ctx.excluded_ancestor_ids
        ]
    )
    descendants_raw = grp_snapshot.get("descendants") or []
    descendants_payload: list[dict[str, Any]] = (
        []
        if "descendants" in context_excludes
        else _prune_descendants(
            descendants_raw,
            ctx.excluded_descendant_ids,
            ctx.excluded_competence_ids,
        )
    )

    system, user_prompt = prompts.build_group_prompt(
        group_title=grp.title,
        group_description=grp.description,
        source_tree=group_source_tree,
        with_indicators=ctx.with_indicators,
        refinement=ctx.refinement,
        specializations=specializations or None,
        related_specializations=related_specializations or None,
        divisions=divisions or None,
        company=company,
        ancestors=ancestors_titles or None,
        descendants=descendants_payload or None,
    )
    return _BuiltPrompt(system, user_prompt, GeneratedTreeSchema)


async def _build_prompt_competence_indicators(
    ctx: _SessionContext,
) -> _BuiltPrompt | _PromptFailure:
    from app.modules.ai_competence_generation import prompts
    from app.modules.ai_competence_generation.schemas import (
        GeneratedIndicatorsSchema,
    )
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        SkillLevel,
    )

    db = ctx.db
    sess = ctx.sess
    tenant_id = ctx.tenant_id
    context_excludes = ctx.context_excludes
    base_snapshot = ctx.base_snapshot

    if sess.target_id is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="indicators session has no target_id",
        )
    comp = await db.get(Competence, sess.target_id)
    if comp is None:
        return _PromptFailure(
            error_code="insufficient_data",
            message="target competence missing",
        )
    level_q = await db.execute(
        select(SkillLevel.title).where(
            SkillLevel.is_active.is_(True),
            (SkillLevel.tenant_id == tenant_id) | SkillLevel.tenant_id.is_(None),
        )
    )
    levels = [t for (t,) in level_q.all()]
    # HRP-114: existing indicators can be dropped via the modal
    # so the LLM doesn't anchor on what's already there.
    existing_raw = (
        base_snapshot.get("competence", {}).get("indicators", [])
        if base_snapshot
        else []
    )
    existing = [] if "existing_indicators" in context_excludes else existing_raw
    parents: list[str] = []
    cur_group = await db.get(CompetenceGroup, comp.group_id)
    while cur_group is not None:
        parents.insert(0, cur_group.title)
        if cur_group.parent_id is None:
            break
        cur_group = await db.get(CompetenceGroup, cur_group.parent_id)

    # HRP-102: when the session was launched from a matrix cell,
    # the create-step persisted a `specialization_context` block on
    # the snapshot. The prompt builder uses it to bias indicators
    # against sibling competences and the spec's grade ladder.
    # HRP-114: same `sibling_competences` toggle drops them from
    # the matrix snapshot too — the user gets one chip controlling
    # both group siblings and matrix siblings.
    spec_context = (
        base_snapshot.get("specialization_context") if base_snapshot else None
    )
    if spec_context and "sibling_competences" in context_excludes:
        spec_context = {
            k: v for k, v in spec_context.items() if k != "sibling_competences"
        }

    # HRP-114: same-group siblings (other competences sharing
    # ``comp.group_id``) are useful context for the LLM even when
    # the session wasn't launched from a matrix.
    sibling_titles: list[str] = []
    if comp.group_id is not None and ("sibling_competences" not in context_excludes):
        sib_q = await db.execute(
            select(Competence.title).where(
                Competence.group_id == comp.group_id,
                Competence.id != comp.id,
                Competence.is_active.is_(True),
            )
        )
        sibling_titles = sorted({t for (t,) in sib_q.all() if t})

    # HRP-114: tenant context + related specializations for
    # indicators scope. Related = specs whose matrices reference
    # this specific competence — separate signal from the broader
    # tenant catalogue.
    specializations = await ctx.fetch_tenant_specializations()
    divisions = await ctx.fetch_tenant_divisions()
    company = await ctx.fetch_tenant_company()
    related_specs_raw = await _fetch_related_specs_for_competence(
        db, tenant_id, comp.id
    )
    related_specializations = (
        []
        if "related_specializations" in context_excludes
        else [
            s["title"]
            for s in related_specs_raw
            if _coerce_uuid(s["id"]) not in ctx.excluded_related_specialization_ids
        ]
    )

    system, user_prompt = prompts.build_indicators_prompt(
        competence_title=comp.title,
        competence_type="hard_skill",
        skill_levels=levels,
        parents=parents,
        existing_indicators=[
            {"title": i["title"], "skill_level": ""} for i in existing
        ],
        refinement=ctx.refinement,
        specialization_context=spec_context,
        specializations=specializations or None,
        related_specializations=related_specializations or None,
        divisions=divisions or None,
        company=company,
        sibling_competences=sibling_titles or None,
    )
    return _BuiltPrompt(system, user_prompt, GeneratedIndicatorsSchema)


async def _build_scope_prompt(
    ctx: _SessionContext,
) -> _BuiltPrompt | _PromptFailure:
    """Dispatch to the per-scope prompt builder.

    Unknown scopes fall through to ``competence_indicators`` — the
    pre-split if/elif chain had the same ``else`` semantics.
    """
    if ctx.sess.scope == "whole_base":
        return await _build_prompt_whole_base(ctx)
    if ctx.sess.scope == "specialization_matrix":
        return await _build_prompt_specialization_matrix(ctx)
    if ctx.sess.scope == "group":
        return await _build_prompt_group(ctx)
    return await _build_prompt_competence_indicators(ctx)


def _normalise_payload(
    ctx: _SessionContext, model_instance: BaseModel
) -> tuple[dict[str, Any], dict[str, bool]]:
    """Attach temp_ids + default selection to the parsed LLM payload."""
    payload_dict = model_instance.model_dump()
    if ctx.sess.scope == "competence_indicators":
        return _normalise_indicators(payload_dict)
    payload_dict, selection = _normalise_tree(payload_dict)
    # HRP-155: in group-scope augment mode (source_tree included)
    # annotate matched existing nodes with ``snapshot_id`` so the
    # tree renders them as locked and the apply step reuses the
    # existing DB rows instead of creating duplicates.
    if (
        ctx.sess.scope == "group"
        and "source_tree" not in ctx.context_excludes
        and ctx.base_snapshot
    ):
        _annotate_group_augment_snapshot(payload_dict, ctx.base_snapshot, selection)
    return payload_dict, selection


async def _flip_ready_and_bill(
    db: AsyncSession,
    sess: CompetenceGenerationSession,
    payload_dict: dict[str, Any],
    selection: dict[str, bool],
) -> None:
    """Persist the payload, flip to `ready` and consume credits in ONE commit.

    CR14: if consume_action raises (e.g. tenant_credits row vanished —
    should be impossible after precheck, but guard anyway), the rollback
    drops both payload and status so the user is never charged for missing
    data nor handed `ready` data without billing.
    """
    from app.modules.ai_competence_generation.billing_actions import (
        start_action_for_scope,
    )

    sess.payload = payload_dict
    sess.selection_state = selection
    sess.status = "ready"
    sess.finished_at = datetime.now(timezone.utc)
    billing_action = (sess.params or {}).get(
        "billing_action"
    ) or start_action_for_scope(sess.scope)
    billing_cost = (sess.params or {}).get("cost")
    await billing_hooks.consume_action(
        db,
        sess.tenant_id,
        sess.user_id,
        billing_action,
        amount_override=billing_cost,
    )
    await db.commit()


async def _send_ready_notification(
    db: AsyncSession,
    sess: CompetenceGenerationSession,
    notification_service: Any,
) -> None:
    from app.modules.auth.models import User

    user = await db.get(User, sess.user_id)
    if user is None:
        return
    try:
        await notification_service.send_notification(
            db,
            sess.tenant_id,
            "competence_generation_ready",
            sess.user_id,
            user.email,
            {
                "recipient_name": user.first_name or user.email,
                "session_id": str(sess.id),
            },
            event_type="competence_generation",
        )
    except Exception:
        logger.exception("failed to send compgen ready notification")


# ---------------------------------------------------------------------------
# Execution body — module-level so tests can drive it without Celery
# ---------------------------------------------------------------------------


async def execute_session(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
) -> dict[str, Any]:
    """Drive one session through pending → ready/error.

    Pulled out of `run_generation_session` so unit tests can call it with a
    test session_factory and skip Celery / `make_async_engine` entirely.

    HRP-122: wraps the body with a heartbeat pulser that refreshes the
    celery liveness key from inside this task — the scheduled beat
    heartbeat sits queued behind us under ``worker_prefetch_multiplier=1``
    and would let ``/health/celery`` flip to 503 mid-run.
    """
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_pulse(
            heartbeat_stop,
            session_factory=session_factory,
            session_id=session_id,
        ),
        name="compgen-heartbeat",
    )
    cancelled = False
    try:
        return await _execute_session_body(session_factory, session_id)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        # HRP-33: if the body raises anything we don't already convert into
        # `_terminate(error)` (e.g. consume_credits failure, DB blip during
        # commit, unexpected provider exception that escapes the retry
        # wrapper), the session row would otherwise stay in `running` and
        # block the user's next AI Generate forever — the partial unique
        # index treats running as active. Catch-all here flips it to
        # `error` so the next attempt can proceed.
        logger.exception(
            "compgen session %s crashed unexpectedly; marking as error",
            session_id,
        )
        try:
            await _force_terminate_running(session_factory, session_id, exc)
        except Exception:
            logger.exception(
                "compgen session %s: failed to mark as error after crash",
                session_id,
            )
        return {
            "status": "error",
            "session_id": str(session_id),
            "error_code": "service_error",
        }
    finally:
        heartbeat_stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(heartbeat_task), timeout=5.0)
        except TimeoutError:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
        except asyncio.CancelledError:
            # Outer cancel: stop the pulser cleanly, then let the original
            # CancelledError keep propagating from the except block above.
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
            if not cancelled:
                raise
        except Exception:
            logger.exception("compgen heartbeat task error on shutdown")


async def _execute_session_body(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
) -> dict[str, Any]:
    """Body of ``execute_session`` — pure DB/LLM work, no heartbeat wiring.

    Orchestration only: load + guard the row, build the scope prompt
    (``_build_scope_prompt``), call the LLM, normalise, stream progress,
    bill + flip to ready, notify. The per-scope prompt assembly lives in
    the ``_build_prompt_*`` builders above.
    """
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )
    from app.modules.ai_settings import service as ai_settings_service
    from app.modules.notification import service as notification_service

    async with session_factory() as db:
        sess = await db.get(CompetenceGenerationSession, session_id)
        if sess is None:
            logger.warning("compgen session %s not found", session_id)
            return {"status": "missing"}
        if sess.status != "pending":
            logger.info(
                "compgen session %s already in status %s; skipping",
                session_id,
                sess.status,
            )
            return {"status": sess.status}

        sess.status = "running"
        await db.commit()
        await db.refresh(sess)

        tenant_id = sess.tenant_id
        user_id = sess.user_id
        await _broadcast_session_update(tenant_id, user_id, sess.id, "running")
        # HRP-71 phase 4: kick off the progress checklist as soon as we flip
        # to running so the UI shows «model is thinking…» immediately, not
        # after the LLM round-trip completes.
        await _broadcast_progress(tenant_id, user_id, sess.id, "thinking")
        tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
        # HRP-500 (review #5): the catalog kill-switch has to be applied
        # here, where the session still exists — the LLM phase below runs
        # on ``credentials`` alone. The recorded ``llm_model`` is the id we
        # actually dispatch and the one billing prices.
        effective_model = await ai_settings_service.get_effective_model_async(
            db, tenant_settings
        )
        sess.llm_model = effective_model
        await db.commit()

        # --- Build prompt per scope ---------------------------------
        ctx = _build_session_context(db, sess)
        built = await _build_scope_prompt(ctx)
        if isinstance(built, _PromptFailure):
            return await _terminate(
                db,
                sess,
                error_code=built.error_code,
                message=built.message,
                notification_service=notification_service,
            )

        # --- Cooperative cancel check #1: before LLM call ----------
        # Cancel may have landed between `status='running'` flip and now.
        # Cheap DB hit; saves the LLM round-trip + tokens entirely.
        await db.refresh(sess, attribute_names=["status"])
        if sess.status == "cancelled":
            logger.info(
                "compgen session %s cancelled before LLM call; skipping",
                sess.id,
            )
            return {"status": "cancelled", "session_id": str(sess.id)}

        # HRP-432: end the read transaction before the LLM phase. The
        # engine-wide idle_in_transaction_session_timeout (5min,
        # app/database.py) kills connections that sit in an open
        # transaction across a many-minute generation — the post-LLM
        # refresh/_terminate would then crash with "connection is closed"
        # and mask the real error. Committing releases the connection;
        # the next statement checks out a fresh one (pool_pre_ping).
        # HRP-465: resolve the tenant's BYOK/local credentials while the
        # session connection is still ours — the LLM phase below runs
        # without an open transaction.
        from app.modules.ai import providers as ai_providers

        credentials = await ai_providers.resolve_generation_target(
            db, sess.tenant_id, effective_model
        )

        await db.commit()

        # --- Call LLM with retries ----------------------------------
        max_attempts = max(
            5, ai_settings_service.get_effective_max_retries(tenant_settings)
        )
        # HRP-480: generated content follows the tenant's content_language;
        # the prompt templates themselves stay English.
        system = "\n\n".join(
            [
                built.system,
                ai_settings_service.build_language_directive(tenant_settings),
            ]
        )
        try:
            model_instance, _ = await _generate_with_retries(
                user_prompt=built.user_prompt,
                system=system,
                schema=built.schema_cls,
                tenant_settings=tenant_settings,
                max_attempts=max_attempts,
                # HRP-122: scope-aware output budget — see _max_tokens_for_scope.
                max_tokens=_max_tokens_for_scope(sess.scope),
                credentials=credentials,
                model=effective_model,
            )
        except RuntimeError as exc:
            code = str(exc) or "service_error"
            # HRP-33: surface the underlying cause in the user-visible
            # message — without it, every flavour (JSON truncated, schema
            # mismatch, provider 5xx) collapses into the same generic
            # "failed after N attempts" line.
            underlying = exc.__cause__
            detail = ""
            if underlying is not None:
                detail_text = str(underlying)[:200]
                detail = f" ({type(underlying).__name__}: {detail_text})"
            if code == "output_truncated":
                # Fail-fast path — "after N attempts" would be a lie, and
                # the remedy is narrowing the scope, not retrying.
                message = f"Model output exceeded the output-token budget{detail}"
            else:
                message = f"LLM generation failed after {max_attempts} attempts{detail}"
            return await _terminate(
                db,
                sess,
                error_code=code,
                message=message,
                notification_service=notification_service,
            )

        # --- Cooperative cancel check #2: after LLM, before billing -
        # Cancel mid-LLM-call doesn't refund the provider tokens, but it
        # does prevent us charging the tenant for an output they discarded
        # and stops the payload from materialising.
        await db.refresh(sess, attribute_names=["status"])
        if sess.status == "cancelled":
            logger.info(
                "compgen session %s cancelled during LLM call; not billing",
                sess.id,
            )
            return {"status": "cancelled", "session_id": str(sess.id)}

        # --- Normalise & persist ------------------------------------
        payload_dict, selection = _normalise_payload(ctx, model_instance)
        # HRP-71 phase 4: synthetic streaming. Totals are known after parse;
        # we replay them as a sequence of progress events so the UI can
        # animate the checklist while we finish the DB commit.
        await _stream_progress_after_parse(
            tenant_id,
            user_id,
            sess.id,
            payload_dict,
            sess.scope,
            ctx.base_snapshot,
        )

        # --- Cooperative cancel check #3: post-streaming, pre-billing -
        # The streaming loop can take ~50 ms × N indicators; a cancel mid-stream
        # must skip both the `ready` flip and `consume_credits`, otherwise the
        # tenant gets billed for output the user already discarded.
        # HRP-163 review: also bail on `error` — the reaper task may have
        # flipped the row to `error/reaped_stuck` while we were producing
        # the payload. Continuing here would overwrite the reap result
        # with `ready` while leaving `error_code='reaped_stuck'` on the
        # row, confusing both the UI and audit log.
        await db.refresh(sess, attribute_names=["status"])
        if sess.status in ("cancelled", "error"):
            logger.info(
                "compgen session %s in terminal state %s during streaming; not billing",
                sess.id,
                sess.status,
            )
            return {"status": sess.status, "session_id": str(sess.id)}

        # CR14: consume credits in the same commit as the payload+ready flip
        # — see _flip_ready_and_bill.
        await _flip_ready_and_bill(db, sess, payload_dict, selection)
        await _broadcast_session_update(tenant_id, user_id, sess.id, "ready")

        # --- Notify -------------------------------------------------
        await _send_ready_notification(db, sess, notification_service)

        return {"status": "ready", "session_id": str(sess.id)}


@celery.task(bind=True, max_retries=0)
def run_generation_session(self, session_id_str: str) -> dict[str, Any]:
    """Drive one session pending → ready/error and notify the initiator."""
    session_id = uuid.UUID(session_id_str)
    return _run_with_async_session(lambda sf: execute_session(sf, session_id))


# ---------------------------------------------------------------------------
# HRP-163: reap stuck-running sessions
# ---------------------------------------------------------------------------

# Sessions running longer than this without an `updated_at` heartbeat are
# considered crashed. The heartbeat refresh inside ``execute_session`` runs
# every 20 s while the body is alive, and the body itself touches the row
# at most every couple of minutes — 15 m is generous enough that legitimate
# long generations are never reaped, and short enough that an OOM victim
# doesn't block the partial unique index for an entire shift.
REAPER_STUCK_AGE_MINUTES = 15


async def _reap_stuck_sessions_body(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Flip stuck-`running` rows to `error` so the per-user active-session
    partial unique index releases. ``_force_terminate_running`` covers the
    in-process crash path; this body covers OOM / SIGKILL / host reboot
    where Python never gets a chance to run the except branch."""
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=REAPER_STUCK_AGE_MINUTES)
    reaped: list[CompetenceGenerationSession] = []
    async with session_factory() as db:
        rows = await db.execute(
            select(CompetenceGenerationSession).where(
                CompetenceGenerationSession.status == "running",
                CompetenceGenerationSession.updated_at < cutoff,
            )
        )
        for sess in rows.scalars().all():
            sess.status = "error"
            sess.error_code = "reaped_stuck"
            sess.error_message = (
                f"Generation worker exited without finishing within "
                f"{REAPER_STUCK_AGE_MINUTES} minutes; resetting to error so "
                f"the next attempt can proceed."
            )
            sess.finished_at = datetime.now(timezone.utc)
            reaped.append(sess)
        await db.commit()
        for sess in reaped:
            try:
                await _broadcast_session_update(
                    sess.tenant_id,
                    sess.user_id,
                    sess.id,
                    "error",
                    error_code=sess.error_code,
                    error_message=sess.error_message,
                )
            except Exception:  # noqa: BLE001
                logger.exception("compgen reaper broadcast failed for %s", sess.id)
    return {"reaped": len(reaped)}


@celery.task(
    bind=True, max_retries=0, name="ai_competence_generation.reap_stuck_sessions"
)
def reap_stuck_sessions(self) -> dict[str, Any]:
    """Beat-driven safety net (every 5 minutes). Runs the async body in
    the standard short-lived-engine envelope so worker resources are not
    held between firings."""
    return _run_with_async_session(_reap_stuck_sessions_body)


async def _force_terminate_running(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    exc: BaseException,
) -> None:
    """HRP-33: rescue stuck-as-running rows after an unexpected crash.

    Opens a fresh DB session because the one that owned the body call may
    have rolled back into an unusable state. We only flip rows still in
    `running`/`pending` — anything terminal stays put. Notification is
    skipped: the LLM didn't produce output worth describing, and we don't
    want a 500 in the mailer to hide the original error in logs.
    """
    from app.modules.ai_competence_generation.models import (
        CompetenceGenerationSession,
    )

    async with session_factory() as db:
        sess = await db.get(CompetenceGenerationSession, session_id)
        if sess is None or sess.status not in ("pending", "running"):
            return
        sess.status = "error"
        sess.error_code = "service_error"
        sess.error_message = (
            f"Generation crashed unexpectedly: "
            f"{type(exc).__name__}: {str(exc)[:200]}"
        )
        sess.finished_at = datetime.now(timezone.utc)
        await db.commit()
        await _broadcast_session_update(
            sess.tenant_id,
            sess.user_id,
            sess.id,
            "error",
            error_code=sess.error_code,
            error_message=sess.error_message,
        )


async def _terminate(
    db: AsyncSession,
    sess: Any,
    *,
    error_code: str,
    message: str,
    notification_service: Any,
) -> dict[str, Any]:
    sess.status = "error"
    sess.error_code = error_code
    sess.error_message = message
    sess.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await _broadcast_session_update(
        sess.tenant_id,
        sess.user_id,
        sess.id,
        "error",
        error_code=error_code,
        error_message=message,
    )

    from app.modules.auth.models import User

    user = await db.get(User, sess.user_id)
    if user is not None:
        try:
            await notification_service.send_notification(
                db,
                sess.tenant_id,
                "competence_generation_error",
                sess.user_id,
                user.email,
                {
                    "recipient_name": user.first_name or user.email,
                    "session_id": str(sess.id),
                    "error_message": message,
                },
                event_type="competence_generation",
            )
        except Exception:
            logger.exception("failed to send compgen error notification")

    return {"status": "error", "session_id": str(sess.id), "error_code": error_code}
