"""Competence → primitive mapping (HRP-749 / HRP-750).

Only this module writes ``competence_primitives`` and
``competence_mapping_states``. That is what keeps the denormalised
``tenant_id`` on both tables equal to ``competences.tenant_id``
(REFACTOR_PLAN §1.2): coverage filters on the link row alone and never joins
``competences`` for the tenant.

The state row answers "the competence was renamed — is the mapping stale?"
without a scheduler (``source_fingerprint``), and it survives an empty or
rejected mapping, so those are distinguishable from a competence that was
never mapped (decision 2026-09-09).

The AI side (§3) works over any competence tree; in the MVP the input is the
tenant's own competences (decision O1-a — there is no origin catalog).
Acceptance is internal: every status counts the same for coverage; the
status only decides whether the next AI run may overwrite the codes and what
the internal report shows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai import llm_client
from app.modules.ai import providers as ai_providers
from app.modules.ai_settings import service as ai_settings_service
from app.modules.competence.models import Competence, Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.primitives.models import (
    MAPPING_STATUSES,
    CompetenceMappingState,
    CompetencePrimitive,
    Primitive,
)
from app.modules.primitives.schemas import ReviewItem

logger = logging.getLogger(__name__)

# v2 (2026-09-09, HRP-751 round 1): full set of exercised capabilities with
# indicator evidence; spoken communication is dialogue (P7/P12), not text.
# v3 (2026-09-09, round 2): top-level-only evidence does not add a code; P7
# narrowed to an outside party with an open outcome.
# v4 (2026-09-09, round 3): posting and filing by known rules is P3, not
# P1 or P9 - the same boundary the decomposition prompt draws.
# v5 (2026-09-09, review): P5 covers written explaining and reporting, a
# spoken presentation adds no code; P12 needs an outside party; escalation
# by rule is P11; registering from documents stays P1.
PROMPT_VERSION = "v2map.v5"
TOP_LEVEL_TAG = "top level"
BATCH_SIZE = 20
MAX_INDICATORS = 10
# 20 items × (uuid + rationale) sits well under this; llm_client clamps it
# to the per-model ceiling. The SDK default (8192) can truncate mid-JSON.
MAX_OUTPUT_TOKENS = 16000
RATIONALE_MAX = 1000
# Human verdicts: never overwritten by an AI run unless the text went stale.
PROTECTED_STATUSES = ("reviewed", "manual", "rejected")


def lock_key(tenant_id: uuid.UUID | str) -> str:
    """One mapping run per tenant at a time: coverage sets the key when it
    schedules a run, the task deletes it when the run is over, so the
    screen's "pending" ends with the run rather than with the window."""
    return f"work:coverage:mapping:{tenant_id}"


# Ceiling on a run that never reports back; ``work.coverage`` keeps its own
# copy (MAPPING_LOCK_SECONDS) because it claims the same key on its schedule.
LOCK_TTL_SECONDS = 600
# ``force`` re-sends competences the model has already answered for, so it is
# the one way to pay for the same rows twice - and on a non-BYOK tenant that
# is the platform's money. One forced run per tenant per hour.
FORCE_COOLDOWN_SECONDS = 3600


def force_cooldown_key(tenant_id: uuid.UUID | str) -> str:
    return f"work:coverage:mapping:force:{tenant_id}"


async def claim_mapping_slot(tenant_id: uuid.UUID | str, *, force: bool) -> None:
    """Take the tenant's single mapping slot for a run started by hand.

    The same key coverage claims, so a manual run can neither overlap a
    scheduled one nor start a second of its own; the task frees it when the
    run ends. Fails closed - a Redis outage leaves this endpoint unthrottled
    over paid LLM calls, which is the thing the slot exists to prevent.
    """
    from app.core.redis import redis_client

    async with redis_client() as client:
        if not await client.set(lock_key(tenant_id), "1", nx=True, ex=LOCK_TTL_SECONDS):
            raise AppError("primitives_mapping_in_progress", 409)
        if force and not await client.set(
            force_cooldown_key(tenant_id), "1", nx=True, ex=FORCE_COOLDOWN_SECONDS
        ):
            await client.delete(lock_key(tenant_id))
            raise AppError("primitives_mapping_force_cooldown", 429)


async def release_mapping_slot(tenant_id: uuid.UUID | str) -> None:
    from app.core.redis import redis_client

    async with redis_client() as client:
        await client.delete(lock_key(tenant_id))


# --- LLM contract ---------------------------------------------------------


class MappedCompetence(BaseModel):
    """Lenient on purpose: one malformed item must not discard a whole
    batch that was already paid for. Ids, codes, confidence and rationale
    are normalised in ``map_competences``."""

    competence_id: str
    primitives: list[str] = Field(default_factory=list)
    confidence: float | None = None
    rationale: str | None = None


class MappedCompetencesSchema(BaseModel):
    items: list[MappedCompetence]


@dataclass
class MappingRunResult:
    mapped: int = 0  # competences that received links
    empty: int = 0  # model returned no code — state row, no links
    kept: int = 0  # protected or already at this prompt version — untouched
    skipped: int = 0  # ids the model invented, duplicated or omitted
    batches: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


# --- Fingerprint ------------------------------------------------------------


def source_fingerprint(title: str, description: str | None) -> str:
    """sha256 over the competence text the mapping was derived from."""
    return hashlib.sha256(f"{title}\n{description or ''}".encode()).hexdigest()


def is_stale(state: CompetenceMappingState, competence: Competence) -> bool:
    return state.source_fingerprint != source_fingerprint(
        competence.title, competence.description
    )


# --- Write side -------------------------------------------------------------


async def _active_by_code(
    db: AsyncSession, codes: Iterable[str]
) -> dict[str, Primitive]:
    wanted = list(dict.fromkeys(codes))
    if not wanted:
        return {}
    found = await db.execute(
        select(Primitive).where(
            Primitive.code.in_(wanted), Primitive.retired_in.is_(None)
        )
    )
    by_code = {p.code: p for p in found.scalars().all()}
    unknown = [code for code in wanted if code not in by_code]
    if unknown:
        raise AppError("primitive_not_found", 404, codes=", ".join(unknown))
    return by_code


async def _states_by_competence(
    db: AsyncSession, competence_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, CompetenceMappingState]:
    if not competence_ids:
        return {}
    rows = await db.execute(
        select(CompetenceMappingState).where(
            CompetenceMappingState.competence_id.in_(list(competence_ids))
        )
    )
    return {state.competence_id: state for state in rows.scalars().all()}


async def _codes_by_competence(
    db: AsyncSession, competence_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    if not competence_ids:
        return {}
    rows = await db.execute(
        select(CompetencePrimitive.competence_id, Primitive.code)
        .join(Primitive, Primitive.id == CompetencePrimitive.primitive_id)
        .where(CompetencePrimitive.competence_id.in_(list(competence_ids)))
        .order_by(Primitive.sort_index)
    )
    out: dict[uuid.UUID, list[str]] = {}
    for competence_id, code in rows.all():
        out.setdefault(competence_id, []).append(code)
    return out


async def apply_mapping(
    db: AsyncSession,
    competence: Competence,
    codes: Iterable[str],
    *,
    status: str = "ai_suggested",
    reviewed_by_id: uuid.UUID | None = None,
    confidence: float | None = None,
    rationale: str | None = None,
    prompt_version: str | None = None,
    commit: bool = True,
) -> CompetenceMappingState:
    """Replace the competence's links with ``codes`` (deduplicated, in order)
    and upsert its state row.

    Retired codes are rejected like unknown ones: nothing new may point at a
    code the catalog has withdrawn. An empty ``codes`` clears the links but
    keeps the state row, so the competence stays "mapped to nothing".

    Both writes are upserts on the tables' unique constraints, not
    check-then-insert: an origin competence is shared, so two tenants' runs
    (or one admin's double click) may reach it at once, and the loser must
    not take its whole batch down. ``commit=False`` leaves the transaction
    to the caller - a review batch lands whole or not at all.
    """
    if status not in MAPPING_STATUSES:
        raise ValueError(f"unknown mapping status {status!r}")
    wanted = list(dict.fromkeys(codes))
    by_code = await _active_by_code(db, wanted)

    now = datetime.now(UTC)
    human = status != "ai_suggested"
    values = {
        "tenant_id": competence.tenant_id,
        "status": status,
        "source_fingerprint": source_fingerprint(
            competence.title, competence.description
        ),
        "confidence": confidence,
        "rationale": rationale,
        "prompt_version": prompt_version,
        "mapped_at": now,
        "reviewed_at": now if human else None,
        "reviewed_by_id": reviewed_by_id if human else None,
    }
    await db.execute(
        pg_insert(CompetenceMappingState)
        .values(competence_id=competence.id, **values)
        .on_conflict_do_update(constraint="uq_compmap_competence", set_=values)
    )
    await db.execute(
        delete(CompetencePrimitive).where(
            CompetencePrimitive.competence_id == competence.id
        )
    )
    if wanted:
        await db.execute(
            pg_insert(CompetencePrimitive)
            .values(
                [
                    {
                        "competence_id": competence.id,
                        "primitive_id": by_code[code].id,
                        "tenant_id": competence.tenant_id,
                    }
                    for code in wanted
                ]
            )
            .on_conflict_do_nothing(constraint="uq_compprim_competence_primitive")
        )
    if commit:
        await db.commit()
    # Read past the identity map: the caller may hold the row from before.
    return (
        await db.execute(
            select(CompetenceMappingState)
            .where(CompetenceMappingState.competence_id == competence.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


# --- AI mapping -------------------------------------------------------------


def build_system_prompt(primitives: Sequence[Primitive]) -> str:
    lines = [
        "You map HR competences to a fixed catalog of capability primitives.",
        "A primitive is a capability a step of work requires. Map each",
        "competence to every capability a person exercising it actually",
        "performs - usually one to four codes.",
        "Rules:",
        "- Use only codes from the catalog below.",
        "- Include a code only when the competence's title, description or at",
        "  least one of its indicators evidences that capability, and name the",
        "  evidence in the rationale. Do not add a code for a capability the",
        "  competence merely touches.",
        f"- An indicator marked ({TOP_LEVEL_TAG}) alone is not enough evidence:",
        "  a code needs the title, the description or an indicator below the",
        "  top level. Everyone who passes the competence is credited with all",
        "  its codes, and a capability only the top level exercises must not",
        "  be credited to all of them.",
        "- Engineering and analytical competences usually span several codes:",
        "  producing the artifact (P9), checking it against a reference such as",
        "  a review or a test (P2), finding the cause of a failure (P4). Include",
        "  each one only when evidenced.",
        "- Spoken or interactive communication is dialogue, not text. P7 only",
        "  for dialogue with a party outside the company (a customer, a",
        "  supplier, a candidate, a regulator) whose outcome is open:",
        "  negotiation, bargaining, interviews, disputes. Explaining or",
        "  reporting is P5 - the report, the memo or the deck is written text;",
        "  a spoken presentation adds no code. Gathering facts from people is",
        "  P1 or P4; internal alignment and conflict is P8; escalation by rule",
        "  is P11. Use P12 when the competence is explicitly about following a",
        "  script, a questionnaire or a procedure with a party outside the",
        "  company.",
        "- Posting transactions to accounts, booking entries or filing tickets",
        "  by known rules is P3, a choice from a finite set - not P9 (an",
        "  artifact accepted by whether it works). Registering an object in a",
        "  system from its documents is P1: the fields are extracted.",
        "- Boundary codes (kind: boundary) only when the competence is about",
        "  physical, sensory or hands-on transfer work; a competence may consist",
        "  of a boundary code alone.",
        "- Return an empty list only when no capability applies.",
        "- confidence is a number in [0, 1] for the whole set; rationale is one",
        "  or two English sentences naming the evidence for each code.",
        "- Return one item per input competence, with the same competence_id.",
        "Catalog:",
    ]
    for p in primitives:
        scope = f" Scope: {p.scope_en}." if p.scope_en else ""
        lines.append(
            f"- {p.code} - {p.title_en}.{scope} (kind: {p.kind}, "
            f"AI verdict: {p.ai_verdict})"
        )
    return "\n".join(lines)


async def _active_primitives(db: AsyncSession) -> list[Primitive]:
    rows = await db.execute(
        select(Primitive)
        .where(Primitive.retired_in.is_(None))
        .order_by(Primitive.sort_index)
    )
    return list(rows.scalars().all())


async def _load_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_ids: Sequence[uuid.UUID] | None,
    *,
    include_origin: bool = False,
) -> list[Competence]:
    stmt = select(Competence).where(Competence.is_active.is_(True))
    if competence_ids:
        # Origin competences (tenant_id IS NULL) are shared by every tenant
        # and only coverage decides a tenant references one; ids that came
        # out of a request body buy no access to them - what is written on a
        # shared row is read by everyone, so a request must not be able to
        # aim a model run at it.
        scope = (
            or_(Competence.tenant_id == tenant_id, Competence.tenant_id.is_(None))
            if include_origin
            else Competence.tenant_id == tenant_id
        )
        stmt = stmt.where(Competence.id.in_(list(competence_ids)), scope)
    else:
        # A blanket run maps this tenant's own tree. The shared library is
        # not one tenant's to pay a model run for wholesale.
        stmt = stmt.where(Competence.tenant_id == tenant_id)
    rows = await db.execute(stmt.order_by(Competence.title))
    return list(rows.scalars().all())


def _needs_mapping(
    competence: Competence, state: CompetenceMappingState | None, force: bool
) -> bool:
    # A stale row goes back to the model whatever its status: a human verdict
    # (reviewed, manual, rejected) was about text that has since changed.
    if state is None:
        return True
    if is_stale(state, competence):
        return True
    if state.status in PROTECTED_STATUSES:
        return False
    return force or state.prompt_version != PROMPT_VERSION


async def _payloads(
    db: AsyncSession, tenant_id: uuid.UUID, competences: Sequence[Competence]
) -> list[dict]:
    """Compact JSON the model sees: title, description, type, indicators."""
    ids = [c.id for c in competences]
    type_ids = {c.competence_type_id for c in competences if c.competence_type_id}
    type_titles: dict[uuid.UUID, str] = {}
    if type_ids:
        rows = await db.execute(
            select(DictionaryItem.id, DictionaryItem.title).where(
                DictionaryItem.id.in_(type_ids)
            )
        )
        type_titles = dict(rows.tuples().all())

    # The top skill level of each competence is marked, because evidence
    # found only there does not add a code (decision 2026-09-09, T4 round
    # 2): whoever passes the competence is credited with all its codes, so a
    # capability only the top level exercises would be credited to everyone.
    # "Top" is the competence's own highest active level, and only when it
    # has more than one - a one-level competence would otherwise lose all
    # its evidence.
    rows = await db.execute(
        select(
            Indicator.competence_id,
            Indicator.title,
            SkillLevel.title,
            SkillLevel.sort_index,
        )
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id.in_(ids),
            # Origin competences are shared and every tenant hangs its own
            # indicators on them - without this the prompt (and the shared
            # mapping it produces) carries another tenant's text.
            Indicator.visible_to(tenant_id),
            Indicator.is_active.is_(True),
            SkillLevel.is_active.is_(True),
        )
        .order_by(SkillLevel.sort_index, Indicator.sort_index)
    )
    per_competence = rows.all()
    levels: dict[uuid.UUID, set[int]] = {cid: set() for cid in ids}
    for competence_id, _title, _level, sort_index in per_competence:
        levels[competence_id].add(sort_index)
    indicators: dict[uuid.UUID, list[str]] = {cid: [] for cid in ids}
    for competence_id, title, level, sort_index in per_competence:
        bucket = indicators[competence_id]
        if len(bucket) < MAX_INDICATORS:
            own = levels[competence_id]
            is_top = len(own) > 1 and sort_index == max(own)
            tag = f"{level} ({TOP_LEVEL_TAG})" if is_top else level
            bucket.append(f"[{tag}] {title}")

    return [
        {
            "competence_id": str(c.id),
            "title": c.title,
            "description": c.description,
            "type": type_titles.get(c.competence_type_id)
            if c.competence_type_id
            else None,
            "indicators": indicators[c.id],
        }
        for c in competences
    ]


async def map_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_ids: Sequence[uuid.UUID] | None = None,
    *,
    force: bool = False,
    include_origin: bool = False,
    batch_size: int = BATCH_SIZE,
) -> MappingRunResult:
    """Map the tenant's (active) competences to primitives, ~20 per LLM call.

    Which competences go to the model: unmapped ones, ones whose text went
    stale, and ``ai_suggested`` ones made by an older prompt version.
    ``force`` also re-maps fresh ``ai_suggested`` rows (prompt iteration);
    ``reviewed`` / ``manual`` / ``rejected`` states are never overwritten
    unless stale. Codes the model invents are dropped, ids it invents are
    skipped. The tenant's model settings apply (BYOK pays with its own key).

    ``include_origin`` admits shared competences named in ``competence_ids``.
    Only coverage sets it: it maps the origin rows the tenant's own grade
    matrices reference, which is the one case a tenant may write on a row
    every other tenant reads.
    """
    result = MappingRunResult()
    primitives = await _active_primitives(db)
    valid_codes = {p.code for p in primitives}
    system = build_system_prompt(primitives)
    competences = await _load_competences(
        db, tenant_id, competence_ids, include_origin=include_origin
    )
    states = await _states_by_competence(db, [c.id for c in competences])
    todo = []
    for candidate in competences:
        # An origin competence is shared: one tenant's ``force`` must not run
        # the model over rows every tenant reads. It is mapped when unmapped
        # or stale, exactly as coverage would have it.
        if _needs_mapping(
            candidate,
            states.get(candidate.id),
            force and candidate.tenant_id is not None,
        ):
            todo.append(candidate)
        else:
            result.kept += 1
    if not todo:
        return result
    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    model = await ai_settings_service.get_effective_model_async(db, tenant_settings)
    credentials = await ai_providers.resolve_generation_target(db, tenant_id, model)

    # A shared row never shares a prompt with the tenant's own text: a
    # competence title and description are text the tenant writes, and one
    # prompt holding both lets it steer the codes stored on an origin row
    # that every other tenant reads.
    own = [c for c in todo if c.tenant_id is not None]
    origin = [c for c in todo if c.tenant_id is None]
    batches = [
        group[start : start + batch_size]
        for group in (own, origin)
        for start in range(0, len(group), batch_size)
    ]

    for batch in batches:
        by_id = {c.id: c for c in batch}
        prompt = json.dumps(
            {"competences": await _payloads(db, tenant_id, batch)}, ensure_ascii=False
        )
        # Last statement before the call: the commit releases the connection,
        # so the idle-in-transaction timeout cannot kill it under a long
        # generation. Nothing may touch ``db`` until the call ends.
        await db.commit()
        parsed = await llm_client.generate_json(
            prompt,
            system=system,
            model=model,
            tenant_settings=tenant_settings,
            schema=MappedCompetencesSchema,
            max_tokens=MAX_OUTPUT_TOKENS,
            db=db,
            tenant_id=tenant_id,
            credentials=credentials,
        )
        if not isinstance(parsed, MappedCompetencesSchema):
            raise TypeError(f"generate_json returned {type(parsed).__name__}")
        result.batches += 1
        seen: set[uuid.UUID] = set()
        for item in parsed.items:
            try:
                competence_id: uuid.UUID | None = uuid.UUID(item.competence_id)
            except ValueError:
                competence_id = None
            competence = by_id.get(competence_id) if competence_id else None
            if competence is None or competence_id in seen:
                result.skipped += 1
                logger.warning(
                    "primitive mapping: unknown or duplicate competence %r",
                    item.competence_id,
                )
                continue
            seen.add(competence.id)
            codes = [code for code in item.primitives if code in valid_codes]
            if len(codes) != len(item.primitives):
                logger.warning(
                    "primitive mapping: dropped unknown codes %s for %s",
                    sorted(set(item.primitives) - valid_codes),
                    competence.id,
                )
            confidence = (
                None if item.confidence is None else min(1.0, max(0.0, item.confidence))
            )
            rationale = (item.rationale or "").strip()[:RATIONALE_MAX] or None
            await apply_mapping(
                db,
                competence,
                codes,
                status="ai_suggested",
                confidence=confidence,
                rationale=rationale,
                prompt_version=PROMPT_VERSION,
            )
            if codes:
                result.mapped += 1
            else:
                result.empty += 1
        result.skipped += len(set(by_id) - seen)
    return result


# --- Internal review --------------------------------------------------------


async def list_mappings(
    db: AsyncSession, tenant_id: uuid.UUID, *, status: str | None = None
) -> list[dict]:
    """One entry per mapped competence (rejected and empty ones included):
    codes, verdict metadata, staleness."""
    stmt = (
        select(CompetenceMappingState, Competence)
        .join(Competence, Competence.id == CompetenceMappingState.competence_id)
        .where(CompetenceMappingState.tenant_id == tenant_id)
        .order_by(Competence.title)
    )
    if status:
        stmt = stmt.where(CompetenceMappingState.status == status)
    rows = (await db.execute(stmt)).all()
    codes = await _codes_by_competence(db, [state.competence_id for state, _ in rows])
    return [
        {
            "competence_id": competence.id,
            "title": competence.title,
            "description": competence.description,
            "codes": codes.get(competence.id, []),
            "status": state.status,
            "confidence": state.confidence,
            "rationale": state.rationale,
            "prompt_version": state.prompt_version,
            "mapped_at": state.mapped_at,
            "reviewed_at": state.reviewed_at,
            "stale": is_stale(state, competence),
        }
        for state, competence in rows
    ]


async def review_mapping(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    items: Sequence[ReviewItem],
    *,
    reviewed_by_id: uuid.UUID,
) -> dict[str, int]:
    """Batch verdicts: ``accepted`` keeps the codes, ``corrected`` replaces
    them, ``rejected`` clears them and marks the state ``rejected``.
    Accepted/corrected rows flip to ``reviewed``; the AI confidence and
    rationale are carried over. When a competence appears twice in one
    batch the last verdict wins.

    Everything is resolved before the first write, so a foreign id, an
    unknown or retired code, an ``accepted`` without a mapping or on a stale
    mapping fails the whole batch instead of half of it. A stale row cannot
    be accepted as-is: its codes came from text that has since changed.
    """
    items = list({item.competence_id: item for item in items}.values())
    ids = {item.competence_id for item in items}
    rows = await db.execute(
        select(Competence).where(
            Competence.id.in_(ids),
            or_(Competence.tenant_id == tenant_id, Competence.tenant_id.is_(None)),
        )
    )
    competences = {c.id: c for c in rows.scalars().all()}
    if len(competences) != len(ids):
        raise AppError("competence_not_found", 404)
    if any(c.tenant_id is None for c in competences.values()):
        # The origin library is read-only to a tenant, its mapping included:
        # a verdict here would rewrite what every other tenant reads.
        raise AppError("origin_competence_read_only", 403)
    states = await _states_by_competence(db, list(ids))
    codes_of = await _codes_by_competence(db, list(ids))
    for item in items:
        if item.verdict != "accepted":
            continue
        state = states.get(item.competence_id)
        if state is None:
            raise AppError("mapping_not_found", 404)
        if is_stale(state, competences[item.competence_id]):
            raise AppError("mapping_stale", 409)
    by_code = await _active_by_code(
        db,
        (
            code
            for item in items
            for code in (
                item.primitives
                if item.verdict == "corrected"
                else codes_of.get(item.competence_id, [])
                if item.verdict == "accepted"
                else []
            )
        ),
    )

    # Written in three statements rather than through ``apply_mapping`` per
    # item: a 200-item batch is the documented ceiling, and five round trips
    # each is a thousand of them for one screen's Save.
    counts = {"accepted": 0, "corrected": 0, "rejected": 0}
    now = datetime.now(UTC)
    state_rows: list[dict] = []
    link_rows: list[dict] = []
    for item in items:
        competence = competences[item.competence_id]
        state = states.get(item.competence_id)
        if item.verdict == "rejected":
            status, codes = "rejected", []
        elif item.verdict == "corrected":
            status, codes = "reviewed", list(dict.fromkeys(item.primitives))
        else:
            status, codes = "reviewed", codes_of.get(item.competence_id, [])
        state_rows.append(
            {
                "competence_id": competence.id,
                "tenant_id": competence.tenant_id,
                "status": status,
                "source_fingerprint": source_fingerprint(
                    competence.title, competence.description
                ),
                "confidence": state.confidence if state else None,
                "rationale": state.rationale if state else None,
                "prompt_version": state.prompt_version if state else None,
                "mapped_at": now,
                "reviewed_at": now,
                "reviewed_by_id": reviewed_by_id,
            }
        )
        link_rows += [
            {
                "competence_id": competence.id,
                "primitive_id": by_code[code].id,
                "tenant_id": competence.tenant_id,
            }
            for code in codes
        ]
        counts[item.verdict] += 1

    # Items are deduplicated above, so no competence is addressed twice -
    # ON CONFLICT DO UPDATE would abort if one were.
    upsert = pg_insert(CompetenceMappingState).values(state_rows)
    await db.execute(
        upsert.on_conflict_do_update(
            constraint="uq_compmap_competence",
            set_={
                column: upsert.excluded[column]
                for column in state_rows[0]
                if column != "competence_id"
            },
        )
    )
    await db.execute(
        delete(CompetencePrimitive).where(
            CompetencePrimitive.competence_id.in_(list(ids))
        )
    )
    if link_rows:
        await db.execute(
            pg_insert(CompetencePrimitive)
            .values(link_rows)
            .on_conflict_do_nothing(constraint="uq_compprim_competence_primitive")
        )
    # One transaction for the batch: a failure mid-way lands none of it.
    await db.commit()
    return counts
