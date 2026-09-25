"""What became of the model's capability proposals (HRP-776, decision
2026-09-09 «clarification of decision 3»): per step and code, whether the
company confirmed the code, left it pending, removed it or added one by
hand. The proposal is the payload of the newest applied decomposition
session of the container; the outcome is the step's current links.
Nothing new is stored - the statistics are a diff. Accepting the
breakdown is not a confirmation of its codes (coverage keeps a step with
an unconfirmed low-confidence code tentative after accept, decision
2026-09-10), so a kept code stays ``pending`` until someone vouches.

A step deleted since apply is a rejected step, not a code edit, and is
skipped. Containers without an applied session (hand-built) have no
proposal and contribute nothing.

A step reclassified since apply (HRP-945) carries the model's second
opinion, not only the company's edits: its rows are flagged
``reclassified``, a code the model added there is ``model_added``, and
``stats`` counts such rows apart from the company's corrections. A step
reclassified before ``reclassified_at`` existed is recognised only by a
code the model added; one where the model only kept or dropped codes still
reads as the company's edits.

Per tenant the numbers say which codes the company keeps correcting; the
same numbers across tenants (``tenant_id=None``) are the platform's
calibration by code - layer one of «generalising processes between
companies» (decision 2026-09-09): sequences of code sets compare without
any text, so nothing of a tenant's wording leaves it.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.primitives.models import Primitive
from app.modules.work.models import (
    WorkDecompositionSession,
    WorkStep,
    WorkStepPrimitive,
)

# What the company did with a proposed code, or added itself.
OUTCOMES = ("confirmed", "pending", "removed", "added")
# HRP-945: a code the model added when the step was reclassified.
MODEL_ADDED = "model_added"


async def outcomes(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """One row per (step, code) of every applied proposal that still has
    its step: ``{tenant_id, container_id, step_id, code, outcome,
    confidence, reclassified}``. ``confidence`` is the model's, ``None`` for
    a code added afterwards. ``confirmed`` is an explicit act - a chip
    click, the picker saved, a code added by hand - never accept alone."""
    stmt = (
        select(WorkDecompositionSession)
        .where(WorkDecompositionSession.status == "applied")
        .order_by(
            WorkDecompositionSession.container_id,
            WorkDecompositionSession.created_at.desc(),
            WorkDecompositionSession.id,
        )
    )
    if tenant_id is not None:
        stmt = stmt.where(WorkDecompositionSession.tenant_id == tenant_id)
    newest: dict[uuid.UUID, WorkDecompositionSession] = {}
    for sess in (await db.execute(stmt)).scalars().all():
        newest.setdefault(sess.container_id, sess)

    # A code retired between ready and apply was never linked: not a
    # correction by the company, so it leaves the proposal.
    active = set(
        (await db.execute(select(Primitive.code).where(Primitive.retired_in.is_(None))))
        .scalars()
        .all()
    )
    # step id -> {code: confidence} as proposed
    proposed: dict[uuid.UUID, dict[str, float | None]] = {}
    # Every code the payload named, active or not: a code retired after
    # apply keeps its link and is still the model's proposal, not an addition.
    named: dict[uuid.UUID, set[str]] = {}
    owner: dict[uuid.UUID, WorkDecompositionSession] = {}
    for sess in newest.values():
        created = (sess.applied_result or {}).get("created_steps") or []
        steps = (sess.payload or {}).get("steps") or []
        # apply_session writes one created id per payload step; a mismatch
        # would pair codes with the wrong steps, so it must be loud.
        for step_id, step in zip(created, steps, strict=True):
            evidence = {
                e["code"]: e.get("confidence") for e in step.get("evidence") or []
            }
            sid = uuid.UUID(step_id)
            proposed[sid] = {
                c: evidence.get(c) for c in step.get("primitives") or [] if c in active
            }
            named[sid] = set(step.get("primitives") or [])
            owner[sid] = sess
    if not proposed:
        return []

    # ponytail: one IN over every proposed step of the scope; chunk it or
    # join through the session if a platform-wide export ever gets slow.
    alive = {
        s.id: s.reclassified_at is not None
        for s in (
            await db.execute(select(WorkStep).where(WorkStep.id.in_(list(proposed))))
        )
        .scalars()
        .all()
    }
    current: dict[uuid.UUID, dict[str, WorkStepPrimitive]] = {sid: {} for sid in alive}
    if alive:
        rows = await db.execute(
            select(WorkStepPrimitive, Primitive.code)
            .join(Primitive, Primitive.id == WorkStepPrimitive.primitive_id)
            .where(WorkStepPrimitive.step_id.in_(list(alive)))
        )
        for link, code in rows.all():
            current[link.step_id][code] = link

    out: list[dict[str, Any]] = []
    for sid in alive:
        sess = owner[sid]
        base = {
            "tenant_id": sess.tenant_id,
            "container_id": sess.container_id,
            "step_id": sid,
        }
        links = current[sid]
        # A code outside the proposal that still carries the model's source
        # can only come from a reclassification: that marks the step even
        # when it was reclassified before ``reclassified_at`` existed.
        additions = links.keys() - named[sid]
        by_model = {
            code for code in additions if links[code].source == "system_suggested"
        }
        reclassified = alive[sid] or bool(by_model)
        for code, confidence in proposed[sid].items():
            link = links.get(code)
            # Accept is not a confirmation: coverage keeps such a step
            # tentative until the chip is confirmed or removed, and the
            # statistics say the same thing.
            if link is None:
                outcome = "removed"
            elif link.confirmed_at is not None:
                outcome = "confirmed"
            else:
                outcome = "pending"
            out.append(
                {
                    **base,
                    "code": code,
                    "outcome": outcome,
                    "confidence": confidence,
                    "reclassified": reclassified,
                }
            )
        for code in additions:
            out.append(
                {
                    **base,
                    "code": code,
                    "outcome": MODEL_ADDED if code in by_model else "added",
                    "confidence": None,
                    "reclassified": reclassified,
                }
            )
    return out


def stats(
    rows: Iterable[dict[str, Any]], *, by: str = "code"
) -> dict[Any, dict[str, int]]:
    """Counts per ``by`` (``code``, ``container_id`` or ``tenant_id``):
    ``proposed`` (the model's codes), the four outcomes, ``kept`` =
    confirmed + pending, and ``reclassified`` - the rows of reclassified
    steps, kept out of every other count so the rest is the company's own
    corrections. ``added`` codes are not proposed."""
    out: dict[Any, Counter[str]] = {}
    for row in rows:
        counter = out.setdefault(row[by], Counter())
        if row.get("reclassified"):
            counter["reclassified"] += 1
            continue
        counter[row["outcome"]] += 1
        if row["outcome"] not in ("added", MODEL_ADDED):
            counter["proposed"] += 1
    return {
        key: {
            "proposed": c["proposed"],
            "kept": c["confirmed"] + c["pending"],
            **{o: c[o] for o in OUTCOMES},
            "reclassified": c["reclassified"],
        }
        for key, c in sorted(out.items(), key=lambda kv: str(kv[0]))
    }
