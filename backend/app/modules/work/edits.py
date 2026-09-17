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

OUTCOMES = ("confirmed", "pending", "removed", "added")


async def outcomes(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """One row per (step, code) of every applied proposal that still has
    its step: ``{tenant_id, container_id, step_id, code, outcome,
    confidence}``. ``confidence`` is the model's, ``None`` for a code the
    company added. ``confirmed`` is an explicit act - a chip click, the
    picker saved, a code added by hand - never accept alone."""
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
            owner[sid] = sess
    if not proposed:
        return []

    # ponytail: one IN over every proposed step of the scope; chunk it or
    # join through the session if a platform-wide export ever gets slow.
    alive = {
        s.id: s.state
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
                {**base, "code": code, "outcome": outcome, "confidence": confidence}
            )
        for code in links.keys() - proposed[sid].keys():
            out.append({**base, "code": code, "outcome": "added", "confidence": None})
    return out


def stats(
    rows: Iterable[dict[str, Any]], *, by: str = "code"
) -> dict[Any, dict[str, int]]:
    """Counts per ``by`` (``code``, ``container_id`` or ``tenant_id``):
    ``proposed`` (the model's codes), the four outcomes, and ``kept`` =
    confirmed + pending. ``added`` codes are not proposed."""
    out: dict[Any, Counter[str]] = {}
    for row in rows:
        counter = out.setdefault(row[by], Counter())
        counter[row["outcome"]] += 1
        if row["outcome"] != "added":
            counter["proposed"] += 1
    return {
        key: {
            "proposed": c["proposed"],
            "kept": c["confirmed"] + c["pending"],
            **{o: c[o] for o in OUTCOMES},
        }
        for key, c in sorted(out.items(), key=lambda kv: str(kv[0]))
    }
