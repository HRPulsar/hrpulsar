"""Celery side of the AI decomposition (HRP-755, HRP-775).

A copy of ``ai_competence_generation.tasks`` cut down to two LLM calls
(``v2work.v5``, decision 2026-09-10): load the ``pending`` row, flip to
``running``, split the description into steps with the first call, then
classify the fixed list with the second - the capability codes of the
first call are discarded, its titles, descriptions and scales stay. Only
catalog codes are kept, then the payload is persisted, the row flipped to
``ready`` and the credits consumed in one commit - a run that fails or is
cancelled at any point is never charged. The reaper beat job frees a
container whose worker died without updating its row.

``split_steps`` / ``classify_steps`` are the two calls on their own, so
the request-path reclassification (``service.reclassify_step``) and the
review script (``scripts/run_decomposition_review.py``) run the same
prompts as the worker.

Since W6 a step's ``SKILL.md`` is generated here too (§5.12): three
minutes of HTTP is proxy-timeout territory, a closed tab used to lose a
file that had in fact been written, and the bulk generation of §5.11 is
not synchronous at all. Same split as a decomposition - the handler
prechecks, the task consumes in the commit that writes the file.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import billing_hooks
from app.core.celery_app import celery
from app.core.errors import exception_summary
from app.modules.ai.tasks import _run_with_async_session
from app.modules.work.models import (
    HOURS_PER_RUN_MAX,
    HOURS_PER_RUN_MIN,
    QUOTE_MAX,
    RUNS_PER_YEAR_MAX,
    WorkDecompositionSession,
    WorkStepSkill,
)
from app.modules.work.schemas import (
    DecompositionSchema,
    GeneratedSkillSchema,
    StepClassification,
    classification_schema,
)
from app.modules.work.service import release_session_hold

logger = logging.getLogger(__name__)

# No heartbeat refreshes updated_at during an LLM call (compgen has one),
# so the cutoff counts from the run's start and again from the phase flip.
# A healthy call is about a minute; the full retry budget (attempts x 600 s
# SDK timeout) is far longer, and a run reaped mid-call is not charged -
# the worker's guarded flip sees the row is no longer running and drops
# the answer.
REAPER_STUCK_AGE_MINUTES = 30
MIN_ATTEMPTS = 3
WS_EVENT = "work.session.updated"


async def _broadcast(
    sess: WorkDecompositionSession,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Best-effort status fan-out; the editor polls anyway."""
    try:
        from app.core.websocket import manager

        payload: dict[str, Any] = {
            "type": WS_EVENT,
            "payload": {
                "session_id": str(sess.id),
                "container_id": str(sess.container_id),
                "status": sess.status,
                "phase": sess.phase,
            },
        }
        if error_code:
            payload["payload"]["error_code"] = error_code
        if error_message:
            payload["payload"]["error_message"] = error_message
        await manager.publish_to_user(str(sess.tenant_id), str(sess.user_id), payload)
    except Exception:  # noqa: BLE001
        logger.exception("work decomposition ws broadcast failed")


async def _terminate(
    db: AsyncSession,
    sess: WorkDecompositionSession,
    *,
    error_code: str,
    message: str,
    commit: bool = True,
) -> dict[str, Any]:
    """``commit=False`` for the reaper, which ends a whole sweep in one
    transaction and broadcasts once it is in."""
    sess.status = "error"
    sess.phase = None
    sess.error_code = error_code
    sess.error_message = message[:2000]
    sess.finished_at = datetime.now(UTC)
    # The run is over and nothing will be charged against its hold
    # (HRP-547); a cancel released its own on the way past.
    await release_session_hold(db, sess.tenant_id, sess.id)
    if commit:
        await db.commit()
        await _broadcast(sess, error_code=error_code, error_message=sess.error_message)
    return {"status": "error", "session_id": str(sess.id), "error_code": error_code}


async def _force_terminate_running(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    exc: BaseException,
) -> None:
    """After an unexpected crash the body's session may be unusable: open a
    fresh one and flip the row so the container's active-run slot frees."""
    async with session_factory() as db:
        sess = await db.get(WorkDecompositionSession, session_id)
        if sess is None or sess.status not in ("pending", "running"):
            return
        await _terminate(
            db,
            sess,
            error_code="service_error",
            # The class name is as much of an unexpected exception as a
            # reader gets; ``execute_session`` logged the traceback.
            message=f"Decomposition crashed: {type(exc).__name__}",
        )


def _hours(step: Mapping[str, Any]) -> dict[str, Any]:
    """W6: the two estimates, an out-of-range one dropped rather than
    clamped - a clamped number would be our invention, a missing one
    reads as "hours not set" and stays out of the shares."""
    hours, runs = step.get("hours_per_run"), step.get("runs_per_year")
    if runs is not None and math.isfinite(runs):
        # The schema takes a number: a model that answers 0.5 for a biennial
        # step must not fail the whole paid answer over an integer. NaN and
        # infinity (``json`` accepts both) are left for the range check
        # below to drop - ``round`` would raise on them.
        runs = round(runs)
    if hours is not None and not HOURS_PER_RUN_MIN <= hours <= HOURS_PER_RUN_MAX:
        logger.warning("work decomposition: dropped hours_per_run=%r", hours)
        hours = None
    if runs is not None and not 1 <= runs <= RUNS_PER_YEAR_MAX:
        logger.warning("work decomposition: dropped runs_per_year=%r", runs)
        runs = None
    return {"hours_per_run": hours, "runs_per_year": runs}


def _normalise(steps: Sequence[Mapping[str, Any]], valid_codes: set[str]) -> dict:
    """Keep catalog codes only, and one evidence entry per kept code
    (HRP-776): evidence for an unknown or dropped code goes with it, a
    quote is cut to ``QUOTE_MAX``. The hours estimate is range-checked."""
    out = []
    for step in steps:
        wanted = list(dict.fromkeys(step.get("primitives") or []))
        codes = [c for c in wanted if c in valid_codes]
        if len(codes) != len(wanted):
            logger.warning(
                "work decomposition: dropped unknown codes %s on %r",
                sorted(set(wanted) - valid_codes),
                step.get("title"),
            )
        evidence: dict[str, dict[str, Any]] = {}
        for e in step.get("evidence") or []:
            if e["code"] in codes and e["code"] not in evidence:
                evidence[e["code"]] = {
                    "code": e["code"],
                    "quote": (e.get("quote") or "")[:QUOTE_MAX],
                    "confidence": e["confidence"],
                }
        out.append(
            {
                **step,
                **_hours(step),
                "primitives": codes,
                "evidence": list(evidence.values()),
            }
        )
    return {"steps": out}


def _max_attempts(tenant_settings: Any) -> int:
    from app.modules.ai_settings import service as ai_settings_service

    return max(
        MIN_ATTEMPTS, ai_settings_service.get_effective_max_retries(tenant_settings)
    )


def _failure_message(exc: RuntimeError, phase: str) -> tuple[str, str]:
    """``error_message`` is shown to everyone who reads the container, so
    the provider's own words - which can quote the prompt, the endpoint or
    a response body from whatever that endpoint really is - go to the log
    and the row keeps our code."""
    code = str(exc) or "service_error"
    logger.warning(
        "work decomposition failed while %s (%s): %s",
        phase,
        code,
        exception_summary(exc.__cause__ or exc),
    )
    message = (
        "Model output exceeded the output-token budget"
        if code == "output_truncated"
        else f"Decomposition failed while {phase}"
    )
    return code, message


# --- The two calls ----------------------------------------------------------
# Both raise ``RuntimeError(error_code)`` after the retry budget, like
# ``_generate_with_retries`` they wrap. ``container`` is the snapshot dict
# (type / title / description / goal), ``primitives`` the active catalog
# rows in catalog order.


def _language(tenant_settings: Any) -> str:
    from app.modules.ai_settings import service as ai_settings_service

    return ai_settings_service.build_language_directive(tenant_settings)


async def split_steps(
    container: Mapping[str, Any],
    *,
    primitives: Sequence[Any],
    tenant_settings: Any,
    credentials: Any,
    model: str | None,
    max_attempts: int,
) -> list[dict[str, Any]]:
    """Phase one: the v4 prompt as it was - steps with their attributes.
    The codes it returns are a first guess the second phase replaces."""
    from app.modules.ai_competence_generation.tasks import _generate_with_retries
    from app.modules.work import prompts

    language = _language(tenant_settings)
    parsed, _ = await _generate_with_retries(
        # Restated last: the JSON schema and the English examples come after
        # the system prompt and would otherwise out-argue the directive.
        user_prompt=f"{prompts.build_user_prompt(container)}\n\n{language}",
        system="\n\n".join([prompts.build_system_prompt(primitives), language]),
        schema=DecompositionSchema,
        tenant_settings=tenant_settings,
        max_attempts=max_attempts,
        credentials=credentials,
        model=model,
    )
    assert isinstance(parsed, DecompositionSchema)
    return [s.model_dump() for s in parsed.steps]


async def classify_steps(
    container: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    *,
    primitives: Sequence[Any],
    tenant_settings: Any,
    credentials: Any,
    model: str | None,
    max_attempts: int,
    only: int | None = None,
    comment: str | None = None,
) -> list[dict[str, Any]]:
    """Phase two: codes, responsibility and output type for the fixed
    list, one entry per step in order. With ``only`` (a 0-based index) the
    same prompt classifies that one step, the rest being context, and the
    result is a one-element list."""
    from app.modules.ai_competence_generation.tasks import _generate_with_retries
    from app.modules.work import prompts

    language = _language(tenant_settings)
    schema = classification_schema(1 if only is not None else len(steps))
    parsed, _ = await _generate_with_retries(
        user_prompt=(
            f"{prompts.build_classify_user_prompt(container, steps, only=only, comment=comment)}"
            f"\n\n{language}"
        ),
        system="\n\n".join(
            [prompts.build_classify_system_prompt(primitives), language]
        ),
        schema=schema,
        tenant_settings=tenant_settings,
        max_attempts=max_attempts,
        credentials=credentials,
        model=model,
    )
    return [
        StepClassification.model_validate(c).model_dump()
        for c in parsed.model_dump()["steps"]
    ]


async def _execute_body(
    session_factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> dict[str, Any]:
    from app.modules.ai import providers as ai_providers
    from app.modules.ai_settings import service as ai_settings_service
    from app.modules.primitives.models import Primitive

    async with session_factory() as db:
        sess = await db.get(WorkDecompositionSession, session_id)
        if sess is None:
            logger.warning("work decomposition session %s not found", session_id)
            return {"status": "missing"}
        if sess.status != "pending":
            return {"status": sess.status, "session_id": str(sess.id)}
        sess.status = "running"
        sess.phase = "splitting"
        await db.commit()
        await _broadcast(sess)

        tenant_settings = await ai_settings_service.get_or_default(db, sess.tenant_id)
        effective_model = await ai_settings_service.get_effective_model_async(
            db, tenant_settings
        )
        sess.llm_model = effective_model
        primitives = (
            (
                await db.execute(
                    select(Primitive)
                    .where(Primitive.retired_in.is_(None))
                    .order_by(Primitive.sort_index, Primitive.code)
                )
            )
            .scalars()
            .all()
        )
        container = sess.base_snapshot.get("container") or {}
        max_attempts = _max_attempts(tenant_settings)
        # A cancel may have landed since the running flip: check before
        # paying for the call.
        await db.refresh(sess, attribute_names=["status"])
        if sess.status == "cancelled":
            return {"status": "cancelled", "session_id": str(sess.id)}
        credentials = await ai_providers.resolve_generation_target(
            db, sess.tenant_id, effective_model
        )
        call: dict[str, Any] = {
            "primitives": primitives,
            "tenant_settings": tenant_settings,
            "credentials": credentials,
            "model": effective_model,
            "max_attempts": max_attempts,
        }
        # Last statement before an LLM phase: the commit releases the
        # connection, so the idle-in-transaction timeout cannot kill it
        # under a long call. Nothing may touch ``db`` until the call ends.
        await db.commit()

        try:
            steps = await split_steps(container, **call)
        except RuntimeError as exc:
            await db.refresh(sess, attribute_names=["status"])
            if sess.status != "running":
                # Cancelled (or reaped) while the model was failing.
                return {"status": sess.status, "session_id": str(sess.id)}
            code, message = _failure_message(exc, "splitting")
            return await _terminate(db, sess, error_code=code, message=message)

        # Between the phases: a cancel or the reaper ends the run unbilled,
        # and the phase flip refreshes updated_at for the reaper's cutoff.
        await db.refresh(sess, attribute_names=["status"])
        if sess.status != "running":
            return {"status": sess.status, "session_id": str(sess.id)}
        sess.phase = "classifying"
        await db.commit()
        await _broadcast(sess)

        try:
            classes = await classify_steps(container, steps, **call)
        except RuntimeError as exc:
            await db.refresh(sess, attribute_names=["status"])
            if sess.status != "running":
                return {"status": sess.status, "session_id": str(sess.id)}
            code, message = _failure_message(exc, "classifying")
            return await _terminate(db, sess, error_code=code, message=message)
        merged = [{**step, **cls} for step, cls in zip(steps, classes, strict=True)]

        # A cancel (or the reaper) may have landed during the LLM call: the
        # answer is discarded and nothing is billed. The flip is guarded on
        # the row so a cancel committed between the check and the write
        # cannot be overwritten - and then charged.
        flipped = await db.execute(
            update(WorkDecompositionSession)
            .where(
                WorkDecompositionSession.id == sess.id,
                WorkDecompositionSession.status == "running",
            )
            .values(
                status="ready",
                phase=None,
                payload=_normalise(merged, {p.code for p in primitives}),
                finished_at=datetime.now(UTC),
            )
            .returning(WorkDecompositionSession.id)
        )
        if flipped.scalar_one_or_none() is None:
            await db.rollback()
            await db.refresh(sess)
            return {"status": sess.status, "session_id": str(session_id)}
        params = sess.params or {}
        await billing_hooks.consume_action(
            db,
            sess.tenant_id,
            sess.user_id,
            params.get("billing_action") or "work_decomposition.start",
            amount_override=params.get("cost"),
        )
        await release_session_hold(db, sess.tenant_id, sess.id)
        await db.commit()
        await db.refresh(sess)
        await _broadcast(sess)
        return {"status": "ready", "session_id": str(sess.id)}


async def execute_session(
    session_factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> dict[str, Any]:
    """Drive one session pending -> ready/error. Separate from the Celery
    task so tests call it with their own session factory."""
    # ponytail: no heartbeat pulser (HRP-122) - two LLM calls of about a
    # minute each; add it if /health/celery flips during a decomposition or
    # the 30-minute reaper cutoff proves too tight.
    try:
        return await _execute_body(session_factory, session_id)
    except Exception as exc:  # noqa: BLE001 - the row must not stay running
        logger.exception("work decomposition %s crashed", session_id)
        try:
            await _force_terminate_running(session_factory, session_id, exc)
        except Exception:  # noqa: BLE001
            logger.exception("work decomposition %s: could not mark error", session_id)
        return {
            "status": "error",
            "session_id": str(session_id),
            "error_code": "service_error",
        }


@celery.task(bind=True, max_retries=0, name="work.run_decomposition_session")
def run_decomposition_session(self, session_id_str: str) -> dict[str, Any]:
    session_id = uuid.UUID(session_id_str)
    return _run_with_async_session(lambda sf: execute_session(sf, session_id))


async def _reap_stuck_sessions_body(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """OOM / SIGKILL / host reboot leave a row in ``running`` forever, a
    broker that lost the message leaves one in ``pending`` - either holds
    the container's active-run slot. Flip such rows to ``error``."""
    cutoff = datetime.now(UTC) - timedelta(minutes=REAPER_STUCK_AGE_MINUTES)
    message = (
        f"Decomposition worker exited without finishing within "
        f"{REAPER_STUCK_AGE_MINUTES} minutes."
    )
    async with session_factory() as db:
        rows = await db.execute(
            select(WorkDecompositionSession).where(
                WorkDecompositionSession.status.in_(("pending", "running")),
                WorkDecompositionSession.updated_at < cutoff,
            )
        )
        stuck = list(rows.scalars().all())
        for sess in stuck:
            await _terminate(
                db, sess, error_code="reaped_stuck", message=message, commit=False
            )
        if stuck:
            # One sweep, one transaction: the rows were selected together
            # and nothing about one of them depends on another.
            await db.commit()
            for sess in stuck:
                await _broadcast(
                    sess, error_code="reaped_stuck", error_message=sess.error_message
                )
    return {"reaped": len(stuck)}


@celery.task(bind=True, max_retries=0, name="work.reap_stuck_sessions")
def reap_stuck_sessions(self) -> dict[str, Any]:
    return _run_with_async_session(_reap_stuck_sessions_body)


# --- The step's SKILL.md (W6, §5.12) ----------------------------------------


async def _release_skill_hold(
    db: AsyncSession, tenant_id: uuid.UUID, skill_id: uuid.UUID
) -> None:
    """Drop the hold the handler took for this run (HRP-547). Idempotent,
    and the expiry sweep is the backstop for a run that never reached
    here at all."""
    from app.modules.work.router import SKILL_RESERVE_ENTITY

    await billing_hooks.release_action(
        db,
        tenant_id,
        entity_type=SKILL_RESERVE_ENTITY,
        entity_id=skill_id,
        action="work_skill.generate",
    )


async def _fail_skill(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skill_id: uuid.UUID,
    claimed_at: datetime,
    message: str,
) -> dict[str, Any]:
    """A failure writes the status and the error but never clears
    ``content``: the last working file stays in place, and nothing is
    charged - the tenant pays for a delivered skill only.

    Guarded on the claim stamp like the success path: a call that finally
    raises after its row was read as stale and re-claimed must not mark
    the newer run failed, nor overwrite the file that run is about to
    deliver.

    The credit hold goes either way: nothing will be charged against it."""
    flipped = await db.execute(
        update(WorkStepSkill)
        .where(
            WorkStepSkill.id == skill_id,
            WorkStepSkill.status == "generating",
            WorkStepSkill.updated_at == claimed_at,
        )
        .values(status="failed", error_message=message[:2000])
        .returning(WorkStepSkill.id)
    )
    if flipped.scalar_one_or_none() is None:
        await db.rollback()
        return {"status": "superseded", "skill_id": str(skill_id)}
    await _release_skill_hold(db, tenant_id, skill_id)
    await db.commit()
    return {"status": "failed", "skill_id": str(skill_id), "error": message[:200]}


async def _execute_skill_body(
    session_factory: async_sessionmaker[AsyncSession],
    skill_id: uuid.UUID,
    claimed_at: datetime,
    cost: float | None,
) -> dict[str, Any]:
    from app.modules.ai import llm_client
    from app.modules.ai import providers as ai_providers
    from app.modules.ai_settings import service as ai_settings_service
    from app.modules.ai_workforce import service as agents_service
    from app.modules.primitives.models import Primitive
    from app.modules.work import coverage, skills
    from app.modules.work.models import WorkContainer, WorkStep, WorkStepPrimitive

    async with session_factory() as db:
        row = await db.get(WorkStepSkill, skill_id)
        if row is None:
            logger.warning("work skill row %s not found", skill_id)
            return {"status": "missing"}
        if row.status != "generating":
            return {"status": row.status, "skill_id": str(skill_id)}
        step = await db.get(WorkStep, row.step_id)
        container = await db.get(WorkContainer, step.container_id) if step else None
        if step is None or container is None:  # the breakdown was replaced
            return {"status": "missing", "skill_id": str(skill_id)}
        primitives = (
            (
                await db.execute(
                    select(Primitive)
                    .join(
                        WorkStepPrimitive,
                        WorkStepPrimitive.primitive_id == Primitive.id,
                    )
                    .where(WorkStepPrimitive.step_id == step.id)
                    .order_by(Primitive.sort_index, Primitive.code)
                )
            )
            .scalars()
            .all()
        )
        # Re-read, not trusted from the claim: the step's capabilities or
        # its responsibility may have been edited while the task queued,
        # and the tenant must not pay for a skill the service would now
        # refuse to start.
        mode = coverage.effective_mode(step, primitives)
        if mode is None or mode.startswith("blocked_"):
            return await _fail_skill(
                db,
                row.tenant_id,
                skill_id,
                claimed_at,
                "The step is no longer one an agent may perform",
            )
        packs = await agents_service.list_packs(db, row.tenant_id)
        pack = next((p for p in packs if p["id"] == row.pack_id), None)
        if pack is None:  # deactivated between the claim and the run
            return await _fail_skill(
                db,
                row.tenant_id,
                skill_id,
                claimed_at,
                "The agent pack is no longer available",
            )

        tenant_settings = await ai_settings_service.get_or_default(db, row.tenant_id)
        model = await ai_settings_service.get_effective_model_async(db, tenant_settings)
        indicators = await skills.load_indicators(
            db, row.tenant_id, [p.id for p in primitives]
        )
        system = skills.build_system_prompt(
            pack["code"],
            step,
            extras=ai_settings_service.build_system_prompt_extras(tenant_settings),
        )
        prompt = skills.build_user_prompt(
            container=container, step=step, primitives=primitives, indicators=indicators
        )
        credentials = await ai_providers.resolve_generation_target(
            db, row.tenant_id, model
        )
        pack_code, tenant_id, user_id = pack["code"], row.tenant_id, row.generated_by_id
        title = step.title
        # Last statement before the LLM call: the commit releases the
        # connection, so the idle-in-transaction timeout cannot kill it
        # under a long call. Nothing may touch ``db`` until the call ends.
        await db.commit()

        try:
            parsed = await llm_client.generate_json(
                prompt,
                system=system,
                schema=GeneratedSkillSchema,
                tenant_settings=tenant_settings,
                credentials=credentials,
                model=model,
            )
        except Exception as exc:  # noqa: BLE001 - any failure lands on the row
            logger.exception("skill generation failed for skill row %s", skill_id)
            return await _fail_skill(
                db, tenant_id, skill_id, claimed_at, type(exc).__name__
            )
        assert isinstance(parsed, GeneratedSkillSchema)

        skill_name, content = skills.render(
            pack_code,
            parsed.name or title,
            parsed.description,
            parsed.body,
            fallback_name=title,
        )
        # Guarded on the claim stamp, not merely on the status: a run
        # restarted after this one was read as stale holds the same row,
        # and the older answer must be dropped unbilled rather than
        # overwrite the newer file and charge a second time.
        flipped = await db.execute(
            update(WorkStepSkill)
            .where(
                WorkStepSkill.id == skill_id,
                WorkStepSkill.status == "generating",
                WorkStepSkill.updated_at == claimed_at,
            )
            .values(
                status="ready",
                skill_name=skill_name,
                content=content,
                error_message=None,
                llm_model=model,
                generated_at=datetime.now(UTC),
            )
            .returning(WorkStepSkill.id)
        )
        if flipped.scalar_one_or_none() is None:
            await db.rollback()
            return {"status": "superseded", "skill_id": str(skill_id)}
        await billing_hooks.consume_action(
            db, tenant_id, user_id, "work_skill.generate", amount_override=cost
        )
        await _release_skill_hold(db, tenant_id, skill_id)
        await db.commit()
        return {"status": "ready", "skill_id": str(skill_id)}


async def execute_skill(
    session_factory: async_sessionmaker[AsyncSession],
    skill_id: uuid.UUID,
    claimed_at: datetime,
    cost: float | None = None,
) -> dict[str, Any]:
    """Drive one skill row generating -> ready/failed. Separate from the
    Celery task so tests call it with their own session factory."""
    try:
        return await _execute_skill_body(session_factory, skill_id, claimed_at, cost)
    except Exception as exc:  # noqa: BLE001 - the row must not stay generating
        logger.exception("work skill %s crashed", skill_id)
        try:
            async with session_factory() as db:
                row = await db.get(WorkStepSkill, skill_id)
                if row is not None:
                    await _fail_skill(
                        db, row.tenant_id, skill_id, claimed_at, type(exc).__name__
                    )
        except Exception:  # noqa: BLE001
            logger.exception("work skill %s: could not mark failed", skill_id)
        return {"status": "failed", "skill_id": str(skill_id)}


@celery.task(bind=True, max_retries=0, name="work.generate_step_skill")
def generate_step_skill(
    self, skill_id_str: str, claimed_at_iso: str, cost: float | None = None
) -> dict[str, Any]:
    skill_id = uuid.UUID(skill_id_str)
    claimed_at = datetime.fromisoformat(claimed_at_iso)
    return _run_with_async_session(
        lambda sf: execute_skill(sf, skill_id, claimed_at, cost)
    )
