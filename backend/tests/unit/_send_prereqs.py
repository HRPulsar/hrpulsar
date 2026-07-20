"""Test helpers for the assessment lifecycle.

Two helpers live here:

- ``seed_send_prereqs`` — fills criteria_type + scale_id so an assessment
  can leave ``draft`` (v1.6.0 requirement).
- ``advance_to_done`` — bridges through ``on_review`` (HRP-27): marks
  every participant as completed and runs the on_review → done
  transitions. Tests that explicitly drive an assessment to ``done``
  should call this instead of ``change_status(..., "done")`` because the
  direct hop from ``in_progress`` to ``done`` is no longer allowed.
"""

from __future__ import annotations

import uuid

from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentParticipant,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_send_prereqs(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> None:
    """Set the minimum criteria + scale needed to leave draft.

    Idempotent: leaves whichever field is already populated alone.
    """
    a = await db.get(Assessment, assessment_id)
    if a is None:
        return

    dirty = False
    if not a.criteria_type:
        a.criteria_type = "current_positions"
        dirty = True

    if a.scale_id is None:
        scale = AnswerScale(
            tenant_id=tenant_id,
            title=f"TestScale-{uuid.uuid4().hex[:6]}",
            is_default=False,
        )
        db.add(scale)
        await db.flush()
        for i, code in enumerate(("yes", "no")):
            db.add(
                AnswerOption(
                    scale_id=scale.id,
                    title=code.capitalize(),
                    code=code,
                    weight=i,
                    sort_index=i,
                )
            )
        await db.flush()
        a.scale_id = scale.id
        dirty = True

    if dirty:
        await db.commit()


async def advance_to_in_progress(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict:
    """Force-flip a Sent assessment into ``in_progress`` for tests.

    HRP-192 removed the manual ``change_status(sent → in_progress)`` path,
    so existing tests that just wanted an "in_progress" fixture cannot
    use the service layer anymore. The production auto-flip lives inside
    ``record_answer`` (first answer pushes Sent → In progress); for tests
    that don't care about the answer trail we mutate the row directly to
    keep them focused. Returns the same dict shape as ``change_status``
    so existing assertions on ``started_at`` / ``status_code`` keep working.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from app.modules.assessment.models import AssessmentStatus as _Status
    from sqlalchemy.orm import selectinload

    a = await db.get(Assessment, assessment_id)
    if a is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    new_status = (
        await db.execute(select(_Status).where(_Status.code == "in_progress"))
    ).scalar_one()
    a.status_id = new_status.id
    a.status = new_status
    if a.started_at is None:
        a.started_at = _dt.now(_tz.utc)
    await db.commit()

    # Re-fetch with the same eager-loaded relationships that change_status
    # returns so the assertions on the read shape keep working. Avoid
    # service.get_assessment_detail because it triggers extra side-effect
    # queries (employee map, scopes) the tests downstream don't need.
    fresh = (
        await db.execute(
            select(Assessment)
            .options(
                selectinload(Assessment.assessment_type),
                selectinload(Assessment.status),
                selectinload(Assessment.employee),
            )
            .where(Assessment.id == assessment_id, Assessment.tenant_id == tenant_id)
        )
    ).scalar_one()
    from app.modules.assessment.service import _assessment_to_read

    return _assessment_to_read(fresh)


async def advance_to_done(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict:
    """Drive an in-flight assessment all the way to ``done``.

    Marks every participant as completed (so the on_review precondition
    holds), pushes the assessment through ``on_review`` if it isn't
    already, then transitions to ``done``. Returns the final assessment
    read shape — same return type as ``change_status``.

    Used by tests that don't care about the lifecycle journey and just
    need a finalized assessment to assert on results / recommendations.
    """
    a = await db.get(Assessment, assessment_id)
    if a is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    parts = (
        (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == assessment_id
                )
            )
        )
        .scalars()
        .all()
    )
    for p in parts:
        if not p.is_completed:
            p.is_completed = True
    if parts:
        await db.commit()

    await db.refresh(a, ["status"])
    if a.status is None or a.status.code != "on_review":
        await service.change_status(db, tenant_id, assessment_id, "on_review")
    return await service.change_status(db, tenant_id, assessment_id, "done")
