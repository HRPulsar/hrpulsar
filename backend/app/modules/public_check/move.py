"""Saved checks move into the visitor's own workspace (HRP-927, epic HRP-918).

What moves: the ready checks kept by the click of their own confirmation
letter (no term left - that letter is the proof the address's owner wants
them; a save alone proves nothing) of the address which equals the email
of the user the checks move to.
Each moves once: ``moved_at`` and ``moved_tenant_id`` are stamped under a
row lock, so a repeat - a second confirmation, a double click, a retry, a
race - finds nothing left to move.

A check becomes one process container owned by that user. Its steps are
rebuilt from the frozen result, the one source that survives the purge of
the sandbox: process order, hours and frequency, responsibility, output
type and the codes still in the catalog (a retired one is dropped, as apply
drops it). The breakdown stays unaccepted - a ``draft`` container of
``system_suggested`` steps with unconfirmed codes, which Coverage shows as
preliminary, as after an apply of the model's breakdown. No credits: an
onboarding step of a new workspace.

Three ways in: (a) the approval of a SaaS signup request and (b) the
confirmed email of an open registration, both through ``move_after_signup``,
which never fails its caller; (c) the button of "my checks", into the
workspace of the signed-in user whose email is the link's address
(``move_by_link``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.primitives.catalog_data import CATALOG_VERSION
from app.modules.primitives.models import Primitive
from app.modules.public_check.models import PublicCheck, PublicCheckEmail
from app.modules.public_check.schemas import Answers, CheckCreate, CheckResult
from app.modules.public_check.service import (
    _kept,
    _magic_address,
    _normalise,
    _title,
    process_text,
)
from app.modules.work.models import WorkContainer, WorkStep, WorkStepPrimitive

logger = logging.getLogger(__name__)


async def move_checks(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, email: str
) -> tuple[int, int]:
    """Move the address's checks into the tenant, owned by the user; the
    numbers moved and skipped. Each check in a savepoint of its own: one
    that cannot become a process (a snapshot that no longer validates, a
    step the work tables refuse) is logged and skipped, stays unmoved, and
    the rest still move. Flushed, not committed: the caller's commit
    carries the containers and the stamps together."""
    now = datetime.now(UTC)
    checks = (
        await db.scalars(
            select(PublicCheck)
            .join(PublicCheckEmail, PublicCheck.email_id == PublicCheckEmail.id)
            .where(
                PublicCheckEmail.email == _normalise(email),
                PublicCheckEmail.verified_at.is_not(None),
                PublicCheck.status == "ready",
                PublicCheck.moved_at.is_(None),
                _kept(),
            )
            .order_by(PublicCheck.created_at)
            # A concurrent move waits here and, once the first commits,
            # re-reads ``moved_at`` on the new row version - and skips it.
            .with_for_update(of=PublicCheck)
            .execution_options(populate_existing=True)
        )
    ).all()
    if not checks:
        return 0, 0
    active = dict(
        (
            await db.execute(
                select(Primitive.code, Primitive.id).where(
                    Primitive.retired_in.is_(None)
                )
            )
        )
        .tuples()
        .all()
    )
    moved = 0
    for check in checks:
        try:
            async with db.begin_nested():
                await _move_one(db, check, tenant_id, user_id, active, now)
        except Exception:
            # The check id only: the row holds the visitor's address.
            logger.exception("public check: check %s not moved, skipped", check.id)
            continue
        moved += 1
    return moved, len(checks) - moved


async def _move_one(
    db: AsyncSession,
    check: PublicCheck,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    active: dict[str, uuid.UUID],
    now: datetime,
) -> None:
    from app.modules.work import coverage

    result = CheckResult.model_validate(check.result)
    container = WorkContainer(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        type="process",
        title=_title(check.description),
        # The text the breakdown was made from, answers included: a new
        # run in the workspace reads what the check's run read.
        description=process_text(
            CheckCreate.model_construct(
                description=check.description,
                answers=Answers.model_validate(check.answers),
                dictated=check.dictated,
            )
        ),
        status="draft",
        source="ai",
        owner_id=user_id,
        created_by_id=user_id,
        catalog_version=CATALOG_VERSION,
    )
    db.add(container)
    steps = sorted(
        [
            *result.buckets.moves,
            *result.buckets.to_review,
            *result.buckets.stays,
            *result.out_of_scope,
        ],
        key=lambda s: s.position,
    )
    for position, step in enumerate(steps, start=1):
        row = WorkStep(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            container_id=container.id,
            position=position,
            title=step.title,
            description=step.description,
            responsibility=step.reason.responsibility,
            output_type=step.reason.output_type,
            hours_per_run=(
                Decimal(str(step.hours_per_run))
                if step.hours_per_run is not None
                else None
            ),
            runs_per_year=step.runs_per_year,
            state="system_suggested",
        )
        db.add(row)
        db.add_all(
            WorkStepPrimitive(
                tenant_id=tenant_id,
                step_id=row.id,
                primitive_id=active[code],
                source="system_suggested",
            )
            for code in dict.fromkeys(step.codes)
            if code in active
        )
    await db.flush()
    # The list column reads the stored figures (HRP-862); nobody has
    # opened the process yet, so without them it shows a dash.
    container.coverage_summary = coverage.summary_of(
        await coverage.compute(
            db,
            tenant_id,
            container.id,
            user_id=user_id,
            schedule_mapping=False,
            people=False,
        )
    )
    check.moved_at = now
    check.moved_tenant_id = tenant_id
    # Inside the savepoint: a stamp that cannot be written skips the check
    # with its process.
    await db.flush()


async def move_after_signup(db: AsyncSession, user: User) -> None:
    """(a) and (b): the new user's checks follow them into their workspace.
    In a session of its own, after the caller's commit: a failure is logged
    and the checks stay where they are - the approval or the confirmation
    that called it has already gone through and its session is untouched."""
    try:
        async with AsyncSession(db.bind, expire_on_commit=False) as own:
            moved, skipped = await move_checks(
                own, tenant_id=user.tenant_id, user_id=user.id, email=user.email
            )
            await own.commit()
    except Exception:
        logger.exception("public check: checks of user %s not moved", user.id)
        return
    if moved or skipped:
        logger.info(
            "public check: %d check(s) moved to tenant %s, %d skipped",
            moved,
            user.tenant_id,
            skipped,
        )


async def move_by_link(db: AsyncSession, token: str, user: User) -> dict[str, int]:
    """(c): the checks behind a "my checks" link into the signed-in user's
    workspace - only when the user's email is the link's address, the one
    the letter proved; anyone else holding the link is 403. ``schemas.Moved``."""
    address = await _magic_address(db, token)
    if _normalise(user.email) != address.email:
        raise AppError("public_check_move_wrong_account", 403)
    moved, skipped = await move_checks(
        db, tenant_id=user.tenant_id, user_id=user.id, email=address.email
    )
    await db.commit()
    return {"moved": moved, "skipped": skipped}
