"""E2E-only seeds of the public check (HRP-932), behind ``require_dev_endpoint``:
404 outside E2E/dev, like ``recruitment/routers/e2e_seed.py``.

CI has no model key and no inbox, so the Playwright specs start from what
the model and the letters would have given and walk the rest through the
real endpoints:

* ``_test/checks`` - a ready check. The intake, the worker's claim, the
  run's delivery and the freeze are the production functions; only the
  model's answer is a fixed one (``STEPS``), passed through the worker's
  own normaliser.
* ``_test/email-token`` - the token a letter to the address would carry
  (the confirmation of its newest check still waiting, or the "my checks"
  link once confirmed), minted by the code the letter uses; only hashes
  are stored, so a new one is issued.
* ``_test/magic-login`` - the one-time login of the SaaS approval letter
  (HRP-927 moves the checks on approval), for the active user of the
  address.
* ``_test/spend-ip-budget`` - spends the caller's per-IP budget of new
  checks through the production throttle, so the next check from that
  address meets the real coded 429 without making a check per hit.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from limits import parse_many
from pydantic import BaseModel, EmailStr
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dev_guard import require_dev_endpoint
from app.core.errors import AppError
from app.core.security import create_magic_login_token
from app.database import get_db
from app.modules.auth.models import User
from app.modules.public_check import service
from app.modules.public_check.models import PublicCheckEmail
from app.modules.public_check.schemas import CheckCreate

router = APIRouter(dependencies=[Depends(require_dev_endpoint)])

# The model's answer of every seeded check, one step per outcome (as in
# tests/unit/test_public_check.py): strong codes only - an agent alone; a
# draft code - an AI draft to check; a regulatory step - review; a judgement
# code - people; a boundary code alone - out of scope. An hour a month each:
# four steps in scope, so the result has its percentages (25 / 50 / 25).
STEPS: list[dict[str, Any]] = [
    {
        "title": title,
        "description": description,
        "hours_per_run": 1,
        "runs_per_year": 12,
        "primitives": codes,
        "responsibility": responsibility,
        "output_type": output,
        "evidence": [{"code": c, "quote": title, "confidence": 0.9} for c in codes],
    }
    for title, description, codes, responsibility, output in (
        (
            "Read the request",
            "Sort the incoming request",
            ["P1", "P3"],
            "none",
            "draft",
        ),
        ("Draft the reply", "Write the answer", ["P4"], "none", "draft"),
        (
            "File the return",
            "Submit it to the authority",
            ["P1"],
            "regulatory",
            "external_change",
        ),
        ("Decide on the exception", "Approve or refuse", ["P6"], "none", "draft"),
        ("Carry the box", "Take the goods to the shelf", ["B1"], "none", "draft"),
    )
]


class _Address(BaseModel):
    email: EmailStr


class _Letter(_Address):
    # None: the choice of ``service.request_link``. ``confirm`` on a
    # confirmed address: the letter of a check saved after the confirmation.
    kind: Literal["confirm", "magic"] | None = None


@router.post("/_test/checks", include_in_schema=False)
async def seed_ready_check(
    data: CheckCreate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """A check the worker has finished: ``token`` and ``owner_key`` as the
    intake hands them to the page, ``id`` as "my checks" lists it."""
    from app.modules.primitives.models import Primitive
    from app.modules.work import tasks as work_tasks
    from app.modules.work.models import WorkDecompositionSession

    check, token, owner_key = await service.create_check(db, data)
    session_id = await service.claim_check(db, check.id)
    run = await db.get(WorkDecompositionSession, session_id)
    assert run is not None  # created with the check
    run.status = "running"  # the worker's flip before the model calls
    await db.commit()
    codes = set(
        await db.scalars(select(Primitive.code).where(Primitive.retired_in.is_(None)))
    )
    await work_tasks._deliver(
        db, run, work_tasks._normalise(STEPS, codes), charge=False
    )
    status = await service.finish_check(db, check.id)
    return {"id": check.id, "token": token, "owner_key": owner_key, "status": status}


@router.post("/_test/email-token", include_in_schema=False)
async def seed_email_token(
    data: _Letter, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """The link a letter to the address would carry now - by default the
    choice of ``service.request_link``: "my checks" once confirmed, else the
    confirmation of the newest check waiting for one. The token issued
    before stops working, as with a letter."""
    address = await db.scalar(
        select(PublicCheckEmail)
        .where(PublicCheckEmail.email == service._normalise(data.email))
        .with_for_update()
    )
    if address is None:
        raise AppError("public_check_not_found", 404)
    kind = data.kind or ("magic" if address.verified_at is not None else "confirm")
    check = None
    if kind == "confirm":
        check = await service.pending_check(db, address)
        if check is None:
            raise AppError("public_check_not_found", 404)
    token = service._issue(address, check)
    await db.commit()
    return {"kind": kind, "token": token}


@router.post("/_test/magic-login", include_in_schema=False)
async def seed_magic_login(
    data: _Address, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """The token of the approval letter of a SaaS signup, minted the way
    ``signup.service.approve_signup`` mints it (never stored)."""
    user = await db.scalar(
        select(User).where(
            func.lower(User.email) == service._normalise(data.email), User.is_active
        )
    )
    if user is None:
        raise AppError("public_check_not_found", 404)
    return {"token": create_magic_login_token(str(user.id), str(user.tenant_id))}


@router.post("/_test/spend-ip-budget", include_in_schema=False)
async def seed_spend_ip_budget(request: Request) -> dict[str, int]:
    """Hit the caller's per-IP bucket of new checks until it refuses. The
    caller is the visitor ``X-Forwarded-For`` names (the trusted-peer rule
    of production); ``hits`` is how many the bucket still took."""
    from app.modules.public_check import router as checks

    # The smallest window of PUBLIC_CHECK_RATE_LIMIT bounds the loop: with
    # the limiter off nothing ever refuses.
    ceiling = min(item.amount for item in parse_many(settings.public_check_rate_limit))
    for hits in range(ceiling + 1):
        try:
            # A fresh request state per hit: slowapi counts one per request.
            await checks._throttle(Request({**request.scope, "state": {}}))
        except RateLimitExceeded:
            return {"hits": hits}
    return {"hits": ceiling + 1}
