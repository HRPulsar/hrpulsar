"""Coverage matching (HRP-758, REFACTOR_PLAN §5): who covers each step of a
breakdown - an agent type, a person, or nobody - and how far the step can
move to an agent at all.

Pure arithmetic over the annotation, no LLM. Three queries and sets:

* the agent layer - a step is covered by a pack when its whole primitive
  set fits inside the pack's (``step ⊆ pack``); a registered agent of the
  tenant matches on its effective set ``pack ∪ add − remove`` and is named;
* the human layer - a cascade of two sources per person: ``assessed`` (the
  latest completed assessment reached the passing score of the person's
  grade specialization, or 75 without one) over ``expected`` (the grade
  matrix of the position requires the competence). One person must hold
  the whole set;
* the automation mode - a function of the step's own annotation, in which
  accountability overrides capability: a boundary code blocks physically,
  a judgement code (``ai_verdict='no'``) blocks by judgement, a formal or
  regulatory signature or an external change needs review, and only a
  step made of strong codes alone is automatable.

Boundary codes leave the arithmetic through one function,
``count_toward_coverage``: a step with no cognitive code is out of scope -
it gets no executor verdict and no share of the percentages. The shares
are yearly hours (W6, decision 2026-09-11): a step without an estimate is
in no bucket and is counted as ``unestimated``; the percentages stay
``None`` on a breakdown shorter than four steps in scope (the 2026-08-31
reservation kept) and while no candidate step carries an estimate.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_workforce import service as agents_service
from app.modules.assessment.models import (
    Assessment,
    AssessmentResult,
    AssessmentStatus,
)
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.competence.models import Competence
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.position.models import Position
from app.modules.primitives.mapping_service import is_stale, lock_key
from app.modules.primitives.models import (
    CompetenceMappingState,
    CompetencePrimitive,
    Primitive,
)
from app.modules.work import service
from app.modules.work.models import (
    WorkContainer,
    WorkHireNeed,
    WorkStep,
    WorkStepPrimitive,
    WorkStepSkill,
)
from app.modules.work.service import get_container

logger = logging.getLogger(__name__)

# Delta 4 (2026-08-31): the threshold is the passing score of the person's
# grade specialization; this is the fallback for a person without one.
DEFAULT_PASSING_SCORE = 75
# Decision 2026-08-31, kept by W6: no percentage on two or three steps.
MIN_STEPS_FOR_SHARES = 4
# §5.1: rare work nobody answers for is an outsourcing candidate.
AGENCY_RUNS_PER_YEAR = 12
# W6 (§5.10): the To do tab is everything unclosed, not only "nobody does
# this". A step an agent type covers but the tenant has not actually
# automated - no agent of its own registered, or no skill file written -
# is work not started, and it belongs on the same list.
GAP_KINDS = ("no_owner", "not_automated_yet")
STRONG_VERDICTS = ("strong", "better_than_human")
# W6 (§5.3): the quality traffic light of a step - how well an agent does
# this work, next to the mode, which says what to do about it. Weakest
# first: a step is only as good as its weakest cognitive capability.
QUALITY_ORDER = ("no", "draft", "strong", "better_than_human")
# Modes in which an agent produces the work: the steps the weights wizard
# asks about, and the ones the shares are about.
CANDIDATE_MODES = ("automatable", "draft_then_review", "review_required")
BUCKET_OF_MODE = {
    "automatable": "moves",
    "draft_then_review": "to_review",
    "review_required": "to_review",
    "blocked_judgment": "stays",
    "blocked_physical": "stays",
}
# HRP-861: percent of a reviewed step's hours that stays with the person who
# checks the agent's work, when the step names no share of its own. Declared
# once, here: the SPA reads the effective value off the payload.
DEFAULT_REVIEW_HUMAN_SHARE = 50
# One mapping run per tenant per window: the first coverage call schedules
# it, the polls that follow see the lock and report "pending".
MAPPING_LOCK_SECONDS = 600
# HRP-776: a code the model reported below this confidence, and nobody
# confirmed, makes the step's verdict preliminary. Measured on five
# processes: above it 74 of 81 codes were right, below it 72 of 105; to be
# revisited on the ten-process sample (decision 2026-09-10).
TENTATIVE_BELOW = 0.8
# How much of the agent registry one coverage read matches against.
AGENT_PAGE = 1000


def count_toward_coverage(primitive: Primitive) -> bool:
    """The one place boundary codes leave the arithmetic (§5.2)."""
    return primitive.kind == "cognitive"


def automation_mode(
    primitives: Sequence[Primitive], *, responsibility: str, output_type: str
) -> str | None:
    """§5.2, checks in order: accountability overrides capability."""
    if not primitives:
        return None
    if any(p.kind == "boundary" for p in primitives):
        return "blocked_physical"
    if any(p.ai_verdict == "no" for p in primitives):
        return "blocked_judgment"
    if responsibility in ("formal", "regulatory") or output_type == "external_change":
        return "review_required"
    if all(p.ai_verdict in STRONG_VERDICTS for p in primitives):
        return "automatable"
    return "draft_then_review"


def effective_mode(step: WorkStep, primitives: Sequence[Primitive]) -> str | None:
    """HRP-863: the company's word outranks the computed mode, the way a
    named executor outranks the match (HRP-809). Every reader of a step's
    mode goes through here - the coverage row, the skill gate and the skill
    task - so the buckets, the To do list and the skill button cannot
    disagree. Only on a step in scope: one with no cognitive capability is
    in no bucket, and there is nothing for the override to move."""
    if step.manual_mode and any(count_toward_coverage(p) for p in primitives):
        return step.manual_mode
    return automation_mode(
        primitives, responsibility=step.responsibility, output_type=step.output_type
    )


def manual_pack(code: str | None, packs: Sequence[dict[str, Any]]) -> dict | None:
    """HRP-863: the pack the company named on the step, out of the packs
    visible to the tenant; None when it named none, or the one it named is
    gone (deleted or deactivated) - the step then reads as without it."""
    return next((p for p in packs if p["code"] == code), None) if code else None


def step_quality(primitives: Sequence[Primitive]) -> str | None:
    """The weakest ``ai_verdict`` among the step's cognitive capabilities
    (§5.3); None for a step out of scope, which has none. Boundary codes
    are left out on purpose - they are why the step is out of scope, and
    their structural "no" would flatten every mixed step to red."""
    cognitive = [p for p in primitives if count_toward_coverage(p)]
    if not cognitive:
        return None
    return min(cognitive, key=lambda p: QUALITY_ORDER.index(p.ai_verdict)).ai_verdict


def step_hours(step: WorkStep) -> float | None:
    """Yearly hours, ``hours_per_run x runs_per_year``; None when either
    is unset - the step is then in no bucket."""
    if step.hours_per_run is None or step.runs_per_year is None:
        return None
    return float(step.hours_per_run) * step.runs_per_year


def review_share(step: WorkStep, mode: str | None) -> int | None:
    """HRP-861: the percent of the step's hours its checker keeps - the
    step's own, else the default. None outside the review bucket, where a
    stored share means nothing."""
    if mode is None or BUCKET_OF_MODE[mode] != "to_review":
        return None
    if step.review_human_share is None:
        return DEFAULT_REVIEW_HUMAN_SHARE
    return step.review_human_share


def freed_hours(row: Mapping[str, Any]) -> float:
    """HRP-861/866: the yearly hours a step takes off people - all of them
    for a step an agent does alone, less what its checker keeps for a step
    that goes to review. A step nobody estimated frees nothing."""
    hours = row["hours_per_year"] or 0.0
    share = row["review_human_share"]
    return hours if share is None else hours * (1 - share / 100)


def step_rate(step: WorkStep, tenant_rate: Decimal | None) -> float | None:
    """HRP-868: the hourly rate a step is priced at - its own, else the
    tenant's; None when neither is set, and the step is then in no money.
    Always in the tenant's currency. Kept apart and small on purpose: the
    next level of the cascade (HRP-869, the executor's salary) goes between
    the two."""
    rate = step.hourly_rate if step.hourly_rate is not None else tenant_rate
    return None if rate is None else float(rate)


def money_of(
    rows: Sequence[dict[str, Any]], rates: dict[uuid.UUID, float | None]
) -> dict[str, Any] | None:
    """HRP-868: the money of the estimated rows, the same set as the hours.
    A sum over the steps, each at its own rate - total hours times one rate
    stopped being right the moment a step could name its own. A row without
    a rate is in no figure and is counted in ``unpriced``, so a partial total
    can say it is partial; None when no row is priced at all."""
    priced = [(r, rates[r["step_id"]]) for r in rows]
    priced = [(r, rate) for r, rate in priced if rate is not None]
    if not priced:
        return None
    money = dict.fromkeys(("moves", "to_review", "to_review_after", "stays"), 0.0)
    for r, rate in priced:
        amount = r["hours_per_year"] * rate
        money[BUCKET_OF_MODE[r["mode"]]] += amount
        if r["review_human_share"] is not None:
            money["to_review_after"] += amount * r["review_human_share"] / 100
    # Clamped: at a share of 100 on fractional hours the subtraction lands
    # on -1e-16, and "frees up -0" is not a figure anybody should read.
    freed = max(0.0, money["moves"] + money["to_review"] - money["to_review_after"])
    total = money["moves"] + money["to_review"] + money["stays"]
    return {
        **{key: round(value, 2) for key, value in money.items()},
        "total": round(total, 2),
        "freed": round(freed, 2),
        "unpriced": len(rows) - len(priced),
    }


def gap_label_for(step: WorkStep, container: WorkContainer) -> str:
    """The step's own label; else the §5.1 first suggestion - rare work
    nobody answers for is an outsourcing candidate; else the container's.
    The suggestion runs before the container default on purpose: the
    default is NOT NULL, so the other order would never let it fire."""
    if step.gap_label:
        return step.gap_label
    if (
        step.responsibility == "none"
        and step.runs_per_year is not None
        and step.runs_per_year <= AGENCY_RUNS_PER_YEAR
    ):
        return "agency"
    return container.gap_default_label


# --- Loading ----------------------------------------------------------------


async def _steps(
    db: AsyncSession, container_id: uuid.UUID
) -> list[tuple[WorkStep, list[Primitive]]]:
    steps = (
        (
            await db.execute(
                select(WorkStep)
                .where(WorkStep.container_id == container_id)
                .order_by(WorkStep.position, WorkStep.created_at)
            )
        )
        .scalars()
        .all()
    )
    links: dict[uuid.UUID, list[Primitive]] = {s.id: [] for s in steps}
    if steps:
        rows = await db.execute(
            select(WorkStepPrimitive.step_id, Primitive)
            .join(Primitive, Primitive.id == WorkStepPrimitive.primitive_id)
            .where(WorkStepPrimitive.step_id.in_(list(links)))
            .order_by(Primitive.sort_index, Primitive.code)
        )
        for step_id, primitive in rows.all():
            links[step_id].append(primitive)
    return [(s, links[s.id]) for s in steps]


async def _agent_layer(
    db: AsyncSession, tenant_id: uuid.UUID
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    packs = [
        {
            "id": p["id"],
            "code": p["code"],
            "title": p["title_en"],
            "codes": set(p["primitive_codes"]),
        }
        for p in await agents_service.list_packs(db, tenant_id)
    ]
    # ponytail: one page at 1000; a registry that large is not an MVP tenant.
    agents, total = await agents_service.list_agents(
        db, tenant_id, is_active=True, limit=AGENT_PAGE
    )
    if total > AGENT_PAGE:
        # Silently matching against a truncated registry would show a step
        # as a gap while the agent that covers it sits on page two.
        logger.warning(
            "coverage: tenant %s has %s active agents, matching against the first %s",
            tenant_id,
            total,
            AGENT_PAGE,
        )
    return packs, [
        {
            "id": a["id"],
            "name": a["name"],
            "pack_id": a["pack_id"],
            "pack_code": a["pack_code"],
            "codes": set(a["effective_primitive_codes"]),
        }
        for a in agents
    ]


async def _human_layer(
    db: AsyncSession, tenant_id: uuid.UUID, wanted_codes: set[str]
) -> tuple[list[dict[str, Any]], set[uuid.UUID]]:
    """Every active employee with ``{code: 'assessed' | 'expected'}``;
    people with nothing to their name are dropped. The second element is the
    competences the tenant actually references - what it was assessed on and
    what its grade matrices expect - which is also the only part of the
    origin library worth mapping for it.

    Only the codes this container's steps ask for are resolved: a match
    needs every required code, so a person holding none of them can never
    be one, and an assignee's ``missing_codes`` is read off the same list.
    That keeps the mapping-link scan and the matching loop proportional to
    the container rather than to the tenant's whole registry."""
    # The position title travels with the match (T14, decision 2026-09-10):
    # the layer matches by capability, not by role, and the screen says so.
    people = (
        await db.execute(
            select(
                Employee.id,
                Employee.position_id,
                User.first_name,
                User.last_name,
                Position.title,
            )
            .join(User, User.id == Employee.user_id)
            .outerjoin(Position, Position.id == Employee.position_id)
            .where(Employee.tenant_id == tenant_id, Employee.status == "active")
            .order_by(User.last_name, User.first_name, Employee.id)
        )
    ).all()
    if not people:
        return [], set()

    # Layer B: position → grade specialization → required competences; the
    # same row carries the passing score layer A compares against.
    spec_of_position: dict[uuid.UUID, tuple[uuid.UUID, int | None]] = {}
    position_ids = {p.position_id for p in people if p.position_id}
    if position_ids:
        rows = await db.execute(
            select(
                Position.id, GradeSpecialization.id, GradeSpecialization.passing_score
            )
            .join(
                GradeSpecialization,
                and_(
                    GradeSpecialization.tenant_id == tenant_id,
                    GradeSpecialization.grade_id == Position.grade_id,
                    GradeSpecialization.specialization_id == Position.specialization_id,
                ),
            )
            .where(Position.id.in_(list(position_ids)))
        )
        spec_of_position = {pid: (gs_id, score) for pid, gs_id, score in rows.all()}
    expected_of_spec: dict[uuid.UUID, set[uuid.UUID]] = {}
    if spec_of_position:
        rows = await db.execute(
            select(
                GradeCompetenceLink.grade_specialization_id,
                GradeCompetenceLink.competence_id,
            ).where(
                GradeCompetenceLink.grade_specialization_id.in_(
                    [gs_id for gs_id, _ in spec_of_position.values()]
                )
            )
        )
        for gs_id, competence_id in rows.all():
            expected_of_spec.setdefault(gs_id, set()).add(competence_id)

    # Layer A: the latest completed assessment per (person, competence).
    rows = await db.execute(
        select(
            Assessment.employee_id,
            AssessmentResult.competence_id,
            AssessmentResult.percent,
        )
        .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.id)
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(
            Assessment.tenant_id == tenant_id,
            AssessmentStatus.code == "done",
            Assessment.employee_id.in_([p.id for p in people]),
        )
        .order_by(
            Assessment.finished_at.desc().nulls_last(),
            Assessment.created_at.desc(),
            Assessment.id,
        )
    )
    # employee → {competence → percent of the latest completed assessment}
    latest: dict[uuid.UUID, dict[uuid.UUID, int | None]] = {}
    for employee_id, competence_id, percent in rows.all():
        latest.setdefault(employee_id, {}).setdefault(competence_id, percent)

    competence_ids = {cid for scores in latest.values() for cid in scores} | {
        cid for ids in expected_of_spec.values() for cid in ids
    }
    codes_of_competence: dict[uuid.UUID, list[str]] = {}
    title_of_competence: dict[uuid.UUID, str] = {}
    if competence_ids and wanted_codes:
        rows = await db.execute(
            select(CompetencePrimitive.competence_id, Primitive.code, Competence.title)
            .join(Primitive, Primitive.id == CompetencePrimitive.primitive_id)
            .join(Competence, Competence.id == CompetencePrimitive.competence_id)
            .where(
                CompetencePrimitive.visible_to(tenant_id),
                CompetencePrimitive.competence_id.in_(list(competence_ids)),
                Primitive.code.in_(list(wanted_codes)),
                Competence.is_active.is_(True),
                Competence.applicable_to != "agent",
            )
        )
        for competence_id, code, title in rows.all():
            codes_of_competence.setdefault(competence_id, []).append(code)
            title_of_competence[competence_id] = title

    out = []
    for person in people:
        gs_id, score = (
            spec_of_position.get(person.position_id, (None, None))
            if person.position_id
            else (None, None)
        )
        threshold = score if score is not None else DEFAULT_PASSING_SCORE
        # Per competence first, codes after: one code can come from several
        # competences, so a failure withdraws only what its own competence
        # granted. A completed assessment outranks the grade both ways -
        # passing proves the competence, failing withdraws the expectation.
        # An unscored one (percent NULL) is no evidence and changes nothing.
        by_competence: dict[uuid.UUID, str] = dict.fromkeys(
            expected_of_spec.get(gs_id, ()) if gs_id else (), "expected"
        )
        for competence_id, percent in latest.get(person.id, {}).items():
            if percent is None:
                continue
            by_competence[competence_id] = (
                "assessed" if percent >= threshold else "failed"
            )
        codes: dict[str, str] = {}
        # HRP-871: what the cascade stood on, kept instead of collapsed - the
        # competences that granted a code, each with the score it was read
        # off. A failed one granted nothing and explains no match.
        grounds: list[dict[str, Any]] = []
        for competence_id, state in by_competence.items():
            if state == "failed":
                continue
            granted = codes_of_competence.get(competence_id, ())
            for code in granted:
                if state == "assessed" or code not in codes:
                    codes[code] = state
            if granted:
                grounds.append(
                    {
                        "competence_id": competence_id,
                        "title": title_of_competence[competence_id],
                        "state": state,
                        "percent": (
                            latest.get(person.id, {}).get(competence_id)
                            if state == "assessed"
                            else None
                        ),
                        "codes": list(granted),
                    }
                )
        if codes:
            out.append(
                {
                    "id": person.id,
                    "name": f"{person.first_name} {person.last_name}".strip(),
                    "position": person.title,
                    "codes": codes,
                    "passing_score": threshold,
                    "grounds": grounds,
                }
            )
    return out, competence_ids


async def _assignees(
    db: AsyncSession, tenant_id: uuid.UUID, steps: Sequence[WorkStep]
) -> dict[uuid.UUID | None, dict[str, Any]]:
    """The active employees the steps name as executor or accountable
    (HRP-809). Read on their own rather than out of ``_human_layer``, which
    drops a person with no capability - and an assignee without the skills
    is exactly the case the assignment exists for. A terminated one is left
    out, so the step reads as unassigned."""
    ids = {s.executor_employee_id for s in steps} | {
        s.accountable_employee_id for s in steps
    }
    ids.discard(None)
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Employee.id,
            User.first_name,
            User.last_name,
            # A free-text title has no Position row; the picker shows it too.
            func.coalesce(Position.title, Employee.position_title),
        )
        .join(User, User.id == Employee.user_id)
        .outerjoin(Position, Position.id == Employee.position_id)
        .where(
            Employee.id.in_(list(ids)),
            Employee.tenant_id == tenant_id,
            Employee.status == "active",
        )
    )
    return {
        employee_id: {
            "employee_id": employee_id,
            "name": f"{first_name} {last_name}".strip(),
            "position": title,
        }
        for employee_id, first_name, last_name, title in rows.tuples().all()
    }


# --- Mapping trigger (§3.3) -------------------------------------------------


async def _unmapped_competences(
    db: AsyncSession, tenant_id: uuid.UUID, referenced: set[uuid.UUID]
) -> list[uuid.UUID]:
    """Active competences with no mapping row, or one made of a text that
    has since changed. ``ai_suggested`` from an older prompt is not enough:
    coverage must not re-run the model on every prompt bump.

    The tenant's own tree, plus the origin competences (``tenant_id IS NULL``)
    it actually references - grade matrices may name those and nothing clones
    them, so without them a tenant on the shared library reads ``gap``
    everywhere. Only the referenced ones: the rest of the origin library is
    not this tenant's to pay a model run for."""
    own = Competence.tenant_id == tenant_id
    scope = (
        or_(own, and_(Competence.tenant_id.is_(None), Competence.id.in_(referenced)))
        if referenced
        else own
    )
    rows = await db.execute(
        select(Competence, CompetenceMappingState)
        .outerjoin(
            CompetenceMappingState,
            CompetenceMappingState.competence_id == Competence.id,
        )
        .where(scope, Competence.is_active.is_(True))
        .order_by(Competence.title, Competence.id)
    )
    return [
        competence.id
        for competence, state in rows.all()
        if state is None or is_stale(state, competence)
    ]


async def _schedule_mapping(
    tenant_id: uuid.UUID,
    competence_ids: list[uuid.UUID],
    user_id: uuid.UUID | None,
) -> bool:
    """Enqueue one mapping run per tenant per window. True when a run is
    now in flight (this call's or an earlier one's); False when it could
    not be arranged - coverage is still answered from what is mapped.
    ``user_id`` routes the task's WS events to the person who asked."""
    key = lock_key(tenant_id)
    try:
        from app.core.redis import redis_client

        async with redis_client() as client:
            claimed = await client.set(key, "1", nx=True, ex=MAPPING_LOCK_SECONDS)
            if not claimed:
                # A run is in flight; the task deletes the key when it ends.
                return True
            try:
                from app.core.task_enqueue import enqueue_task
                from app.modules.primitives.tasks import map_competences_task

                enqueue_task(
                    map_competences_task,
                    str(tenant_id),
                    [str(c) for c in competence_ids],
                    # Coverage names the shared competences its grade
                    # matrices reference; nothing else may map origin rows.
                    include_origin=True,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    module="primitives",
                    action="map_competences",
                )
            except Exception:
                # Free the slot: the next call should retry, not wait it out.
                await client.delete(key)
                raise
        return True
    except Exception:  # noqa: BLE001 - never fail coverage over the trigger
        logger.exception("coverage: could not schedule mapping for %s", tenant_id)
        return False


# --- Matching ---------------------------------------------------------------


def _match_agent(
    codes: set[str], packs, agents, manual_pack_code: str | None = None
) -> dict[str, Any] | None:
    # Several agents of the registry may cover the step: the same one has
    # to win every read, or the coverage tab renames the owner of a step
    # between two refreshes. By name, as the registry is listed; the id
    # settles a collation tie.
    def first(found):
        return min(found, key=lambda a: (a["name"], str(a["id"])), default=None)

    named = manual_pack(manual_pack_code, packs)
    if named is not None:
        # HRP-863: the company named the agent type, so the codes are not
        # asked - the row reads as matched by this pack, with the tenant's
        # own agent of it when one is registered.
        agent = first([a for a in agents if a["pack_id"] == named["id"]])
        return {
            "pack_id": named["id"],
            "pack_code": named["code"],
            "pack_manual": True,
            "agent_id": agent["id"] if agent else None,
            "agent_name": agent["name"] if agent else None,
        }
    agent = first([a for a in agents if codes <= a["codes"]])
    if agent:
        return {
            "pack_id": agent["pack_id"],
            "pack_code": agent["pack_code"],
            "pack_manual": False,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
        }
    for pack in packs:
        if codes <= pack["codes"]:
            return {
                "pack_id": pack["id"],
                "pack_code": pack["code"],
                "pack_manual": False,
                "agent_id": None,
                "agent_name": None,
            }
    return None


def _match_human(codes: set[str], people) -> dict[str, Any] | None:
    best = None
    for person in people:
        if not codes <= person["codes"].keys():
            continue
        assessed = sum(person["codes"][c] == "assessed" for c in codes)
        # Most confirmed codes first; the list is already in name order.
        if best is None or assessed > best[0]:
            best = (assessed, person)
    if best is None:
        return None
    assessed, person = best
    # HRP-871: the competences behind this step's codes, confirmed ones
    # first; a set is unordered, so the order is made here.
    grounds = sorted(
        (
            {**g, "codes": [c for c in g["codes"] if c in codes]}
            for g in person["grounds"]
            if codes.intersection(g["codes"])
        ),
        key=lambda g: (g["state"] != "assessed", g["title"], str(g["competence_id"])),
    )
    return {
        "employee_id": person["id"],
        "name": person["name"],
        "position": person["position"],
        "label": "assessed" if assessed == len(codes) else "expected",
        "missing_codes": [],
        "passing_score": person["passing_score"],
        "grounds": grounds,
    }


async def compute(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    schedule_mapping: bool = True,
    people: bool = True,
) -> dict[str, Any]:
    """Coverage of every step of the container, on any step state.
    ``schedule_mapping`` is the caller's right to start a model run over the
    tenant's unmapped competences: a manager's read does, a plain reader's
    (HRP-810) does not - it is answered from what is mapped.

    ``people=False`` skips the tenant-wide human layer, for a caller that
    reads only ``summary_of``: the hours and the shares follow the modes and
    the agents, and without people an unmatched step reads as a gap."""
    started = time.perf_counter()
    container = await get_container(db, tenant_id, container_id)
    steps = await _steps(db, container.id)
    packs, agents = await _agent_layer(db, tenant_id)
    people_layer, referenced = (
        await _human_layer(db, tenant_id, {p.code for _step, ps in steps for p in ps})
        if people
        else ([], set())
    )
    skill_status: dict[uuid.UUID, str] = {}
    skill_pack: dict[uuid.UUID, uuid.UUID | None] = {}
    unsure: set[uuid.UUID] = set()
    if steps:
        rows = await db.execute(
            select(
                WorkStepSkill.step_id,
                WorkStepSkill.status,
                WorkStepSkill.updated_at,
                WorkStepSkill.pack_id,
            ).where(WorkStepSkill.step_id.in_([s.id for s, _ in steps]))
        )
        # A row abandoned in ``generating`` (cancelled request, worker
        # restart) stops blocking here the way it does in the service:
        # past the timeout it reads as failed, so the button retries.
        now = datetime.now(UTC)
        for step_id, status, updated_at, pack_id in rows.tuples().all():
            skill_status[step_id] = service.effective_skill_status(
                status, updated_at, now
            )
            skill_pack[step_id] = pack_id
        unsure = set(
            (
                await db.execute(
                    select(WorkStepPrimitive.step_id).where(
                        WorkStepPrimitive.step_id.in_([s.id for s, _ in steps]),
                        WorkStepPrimitive.confidence < TENTATIVE_BELOW,
                        WorkStepPrimitive.confirmed_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    assignees = await _assignees(db, tenant_id, [s for s, _ in steps])
    codes_of_person = {p["id"]: p["codes"] for p in people_layer}

    result_rows: list[dict[str, Any]] = []
    for step, primitives in steps:
        codes = {p.code for p in primitives}
        cognitive = [p.code for p in primitives if count_toward_coverage(p)]
        mode = effective_mode(step, primitives)
        executor = assignees.get(step.executor_employee_id)
        accountable = assignees.get(step.accountable_employee_id)
        agent = human = None
        if executor:
            # HRP-809: the company's word outranks the match, an agent's
            # included; the agent stays on the row as what could take it.
            held = codes_of_person.get(executor["employee_id"], {})
            human = {
                **executor,
                "label": "assigned",
                "missing_codes": [c for c in cognitive if c not in held],
            }
        if cognitive:
            # The named pack only counts in a mode where an agent produces
            # the work: on a blocked step it would take the row out of To do
            # while its hours stay with people - covered by nobody.
            agent = _match_agent(
                codes,
                packs,
                agents,
                step.manual_pack_code if mode in CANDIDATE_MODES else None,
            )
            if executor:
                verdict = "human"
            else:
                # Cognitive codes only, like ``required_codes`` and an
                # assignee's ``missing_codes``: a boundary code is why the
                # step stays with people, not something an assessment holds.
                human = _match_human(set(cognitive), people_layer)
                verdict = "agent" if agent else "human" if human else "gap"
        else:
            verdict = "out_of_scope"
        skill = skill_status.get(step.id, "none")
        if (
            skill == "ready"
            and agent is not None
            and agent["pack_manual"]
            and skill_pack.get(step.id) != agent["pack_id"]
        ):
            # HRP-863: the file was written for the pack the step had before
            # the company named this one - not a skill of this agent type.
            # Kept, not deleted: naming the old pack back makes it ready again.
            skill = "none"
        result_rows.append(
            {
                "step_id": step.id,
                "position": step.position,
                "title": step.title,
                "state": step.state,
                "codes": [p.code for p in primitives],
                "required_codes": cognitive,
                "in_scope": bool(cognitive),
                "mode": mode,
                "mode_manual": bool(cognitive and step.manual_mode),
                "quality": step_quality(primitives),
                "verdict": verdict,
                "agent": agent,
                "human": human,
                "human_backup": verdict == "agent" and human is not None,
                "accountable": accountable,
                "needs_accountable": (
                    accountable is None
                    and bool(cognitive)
                    and (
                        mode in ("draft_then_review", "review_required")
                        or step.responsibility != "none"
                    )
                ),
                "gap_label": (
                    gap_label_for(step, container) if verdict == "gap" else None
                ),
                "hours_per_year": step_hours(step),
                "skill_status": skill,
                "tentative": step.state != "accepted" or step.id in unsure,
            }
        )

    # HRP-861: the hours keys of a row are set here, off the row's own mode,
    # so a mode the company set by hand (HRP-863) is already in it.
    for r, (step, _primitives) in zip(result_rows, steps, strict=True):
        r["review_human_share"] = review_share(step, r["mode"])

    in_scope = [r for r in result_rows if r["in_scope"]]
    candidates = [r for r in in_scope if r["mode"] in CANDIDATE_MODES]
    estimated = [r for r in in_scope if r["hours_per_year"] is not None]
    hours = dict.fromkeys(("moves", "to_review", "stays"), 0.0)
    for r in estimated:
        hours[BUCKET_OF_MODE[r["mode"]]] += r["hours_per_year"]
    total = sum(hours.values())
    # HRP-861: "before" is ``to_review``, untouched; this is "after" - what
    # the checkers keep - and the difference is freed like the agent bucket.
    to_review_after = sum(
        (
            r["hours_per_year"] * r["review_human_share"] / 100
            for r in estimated
            if r["review_human_share"] is not None
        ),
        0.0,
    )
    # HRP-862: potential is what an agent type could take; automated is what
    # an agent the tenant registered ("I already use this") does today - on a
    # step whose mode lets an agent have it at all. A step the mode keeps with
    # a person counts in ``stays``, and counting its hours here as well made
    # the card read "120 of 156 already automated" next to 44 that stay.
    automated = sum(
        (
            r["hours_per_year"]
            for r in estimated
            if r["mode"] in CANDIDATE_MODES
            and r["verdict"] == "agent"
            and r["agent"]["agent_id"] is not None
        ),
        0.0,
    )
    shares = None
    if (
        len(in_scope) >= MIN_STEPS_FOR_SHARES
        and total > 0
        and any(r["hours_per_year"] is not None for r in candidates)
    ):
        shares = {bucket: value * 100 / total for bucket, value in hours.items()}

    needs = await _hire_need_of_step(db, tenant_id, container_id)
    for r in result_rows:
        r["hire_need"] = needs.get(str(r["step_id"]))

    quality_counts = dict.fromkeys(QUALITY_ORDER, 0)
    for r in in_scope:
        quality_counts[r["quality"]] += 1

    # The one rate the ROI is priced at (§5.2); no GEO benchmark behind it.
    tenant = await db.get(Tenant, tenant_id)
    # HRP-868: a step may name its own rate, so the money is summed here.
    tenant_rate = tenant.hourly_rate if tenant is not None else None
    money = money_of(
        estimated, {step.id: step_rate(step, tenant_rate) for step, _ in steps}
    )

    # Only a caller allowed to start a mapping run pays for finding out
    # there is one to start: a plain reader (HRP-810) could never act on
    # the answer, and the scan walks the tenant's whole competence tree.
    unmapped = (
        await _unmapped_competences(db, tenant_id, referenced)
        if schedule_mapping
        else []
    )
    mapping_pending = bool(unmapped) and await _schedule_mapping(
        tenant_id, unmapped, user_id
    )

    logger.info(
        "coverage computed: container=%s steps=%d people=%d agents=%d in %.0f ms",
        container.id,
        len(result_rows),
        len(people_layer),
        len(agents),
        (time.perf_counter() - started) * 1000,
    )
    return {
        "container_id": container.id,
        "title": container.title,
        # For the skills bundle's README; the packs are loaded here anyway.
        "pack_titles": {p["code"]: p["title"] for p in packs},
        "status": container.status,
        "mapping_pending": mapping_pending,
        "candidate_step_ids": [r["step_id"] for r in candidates],
        "shares": shares,
        "hours": {
            "total": total,
            **hours,
            "to_review_after": to_review_after,
            "freed": max(
                0.0, hours["moves"] + hours["to_review"] - to_review_after
            ),  # clamped like the money, see ``money_of``
            "automated": automated,
            "unestimated": len(in_scope) - len(estimated),
        },
        "review_human_share_default": DEFAULT_REVIEW_HUMAN_SHARE,
        "quality": quality_counts,
        "hourly_rate": (
            float(tenant.hourly_rate)
            if tenant is not None and tenant.hourly_rate is not None
            else None
        ),
        "hourly_rate_currency": tenant.hourly_rate_currency if tenant else None,
        "money": money,
        "steps": result_rows,
    }


def summary_of(result: dict[str, Any]) -> dict[str, Any]:
    """HRP-862: what the list page shows of a computed coverage. Hours and
    shares only - no money and nobody's name: one summary is stored for
    every reader of the list, whatever each of them may see on the process.
    Rounded, so the same breakdown always compares equal to what is stored.
    ``automated_share`` has the denominator of every other share here, the
    estimated hours, and follows the same gate: a breakdown the process page
    shows no percentages for shows none in the list either."""
    hours, shares = result["hours"], result["shares"]
    return {
        "hours": {key: round(value, 2) for key, value in hours.items()},
        "shares": shares and {key: round(value, 2) for key, value in shares.items()},
        "automated_share": (
            None
            if shares is None
            else round(hours["automated"] * 100 / hours["total"], 2)
        ),
    }


async def remember_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    result: dict[str, Any],
) -> bool:
    """Store ``summary_of(result)`` on the container, for the list; True when
    it was written. The one writer: the coverage read calls it, ``gaps``
    - the same computation, for the To do tab and the hire guard - does not.

    Written only when the figures changed, and without moving ``updated_at``:
    the list is ordered by it, and a figure recomputed on somebody's read is
    not an edit of the container.

    One statement rather than a read-modify-write: the row is not read back,
    the "changed?" test is the WHERE clause, and a container edit committed
    while the coverage was being computed keeps its own ``updated_at``. Two
    reads racing can still leave the older figures behind - accepted: the
    next read of either writes them over, and nothing but a list column
    hangs on them. A cache that cannot be written is not worth the read it
    serves, so a failure is rolled back and logged, not raised."""
    summary = summary_of(result)
    # ``compute`` loaded the container into this session, so ``get`` is an
    # identity-map hit: an unchanged summary - most reads, the mapping polls
    # included - costs no statement and no commit.
    loaded = await db.get(WorkContainer, container_id)
    if loaded is not None and loaded.coverage_summary == summary:
        return False
    try:
        written = await db.execute(
            update(WorkContainer)
            .where(
                WorkContainer.id == container_id,
                WorkContainer.tenant_id == tenant_id,
                WorkContainer.coverage_summary.is_distinct_from(summary),
            )
            # In the SET clause with the value it has, so ``onupdate`` stays out.
            .values(coverage_summary=summary, updated_at=WorkContainer.updated_at)
            # "fetch", not False: a container already loaded in this
            # session must not keep the figures it had before the write.
            .execution_options(synchronize_session="fetch")
        )
        await db.commit()
    except SQLAlchemyError:
        logger.exception("coverage summary not stored: container=%s", container_id)
        await db.rollback()
        return False
    return bool(written.rowcount)  # type: ignore[attr-defined]


# Used by ``compute`` above (resolved at call time) and by ``gaps``.
async def _hire_need_of_step(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """step id (as a string) → the newest hire need of the container that
    still points at a vacancy (a deleted vacancy leaves ``vacancy_id``
    NULL and the need drops out of the screen)."""
    rows = await db.execute(
        select(WorkHireNeed)
        .where(
            WorkHireNeed.tenant_id == tenant_id,
            WorkHireNeed.container_id == container_id,
            WorkHireNeed.vacancy_id.is_not(None),
        )
        .order_by(WorkHireNeed.created_at.desc(), WorkHireNeed.id.desc())
    )
    out: dict[str, dict[str, Any]] = {}
    for need in rows.scalars().all():
        for step_id in need.step_ids:
            out.setdefault(
                str(step_id),
                {"id": need.id, "vacancy_id": need.vacancy_id, "label": need.label},
            )
    return out


def redact_people(
    result: dict[str, Any], *, visible: set[uuid.UUID] | None = None
) -> dict[str, Any]:
    """HRP-810: the coverage of a reader whose HR scope is ``visible`` (the
    employee ids ``access_scope.get_visible_employee_ids`` allows; None for
    nobody). A matched colleague outside it is dropped, the verdict stays;
    an assignee stays named - the company made that choice, no assessment
    did - but without the capabilities they lack."""
    for row in result["steps"]:
        human = row["human"]
        if human is None:
            continue
        if visible is not None and human["employee_id"] in visible:
            continue
        if human["label"] == "assigned":
            row["human"] = {**human, "missing_codes": []}
        else:
            row["human"] = None
            row["human_backup"] = False
    return result


def gap_kind(row: dict[str, Any]) -> str | None:
    """Which To do section a coverage row belongs to, or None when it
    belongs to neither (§5.10)."""
    if row["verdict"] == "gap":
        return "no_owner"
    # The mode has to agree, not only the pack match: a tenant may add any
    # catalog code to its own agent, including a judgement or a boundary
    # one, and such a step would otherwise be listed with a skill button
    # that the service refuses.
    if (
        row["verdict"] == "agent"
        and row["mode"] in CANDIDATE_MODES
        and (row["agent"]["agent_id"] is None or row["skill_status"] != "ready")
    ):
        return "not_automated_yet"
    return None


async def gaps(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    schedule_mapping: bool = True,
) -> list[dict[str, Any]]:
    """Everything unclosed, in breakdown order: the steps nobody covers
    (``no_owner``, each with the hire need it was already handed to,
    HRP-759) and the ones an agent could take but nobody has automated
    yet (``not_automated_yet``). One list with a ``kind``, so the filter
    lives in one place and the hire guard can read it."""
    result = await compute(
        db, tenant_id, container_id, user_id=user_id, schedule_mapping=schedule_mapping
    )
    rows = []
    for r in result["steps"]:
        kind = gap_kind(r)
        if kind is None:
            continue
        rows.append(
            {
                "step_id": r["step_id"],
                "position": r["position"],
                "title": r["title"],
                "kind": kind,
                "mode": r["mode"],
                "gap_label": r["gap_label"],
                "required_codes": r["required_codes"],
                "agent": r["agent"],
                "skill_status": r["skill_status"],
                "hire_need": r["hire_need"],
            }
        )
    return rows
