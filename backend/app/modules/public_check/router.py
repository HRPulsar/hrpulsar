"""The public process check API (HRP-922): anonymous, served on the check
host (HRP-920). Every route answers 404 while the service is off - on-prem
and Community have no such service.

Creating a check is guarded (HRP-923), cheapest refusal first: the pause,
a per-IP throttle, the captcha, then the service's daily budget. Both 429s
carry ``Retry-After``.
Polling a result is not limited - a cheap read the page repeats every
second or two.

Saving a check by email and asking for a link again (HRP-926) send
letters: the same per-IP throttle in a bucket of their own and the same
captcha, plus a cap of letters per address in the service. The links of
the letters (confirm, "my checks", unsubscribe) carry 256-bit tokens and
are not throttled, like polling.

One route is not anonymous: moving the checks of a "my checks" link into
the caller's workspace (HRP-927) needs a signed-in user of that address.

Dictation (HRP-947) - the pause, then a per-IP throttle in a bucket of its
own; its other guards are in ``voice``."""

from __future__ import annotations

import logging
import math
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.client_ip import client_ip
from app.core.errors import AppError
from app.core.rate_limit import make_limiter
from app.core.turnstile import verify_turnstile
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.public_check import funnel, move, service, voice
from app.modules.public_check.schemas import (
    CheckCreate,
    CheckCreated,
    CheckEvent,
    CheckRead,
    Confirmed,
    LinkRequest,
    LinkSent,
    Moved,
    SavedChecks,
    SaveRequest,
    SaveResult,
    Transcript,
    Unsubscribed,
)
from app.modules.work.access import manage_actor

logger = logging.getLogger(__name__)


def require_enabled() -> None:
    # The same answer as an unknown link: a switched-off service is no oracle.
    if not settings.public_check_enabled:
        raise AppError("public_check_not_found", 404)


def _client(request: Request) -> str:
    # The visitor behind our proxy, not the proxy (``client_ip``).
    return client_ip(request) or get_remote_address(request)


limiter = make_limiter(_client)


# Read per request, so a changed setting needs no new decorator.
@limiter.limit(lambda: settings.public_check_rate_limit)
async def _throttle(request: Request) -> None:
    """One hit on the visitor's budget of new checks. Its own function,
    not the route's decorator: the refusal must be our coded 429, and
    slowapi's handler answers with text of its own."""


@limiter.limit(lambda: settings.public_check_rate_limit)
async def _throttle_mail(request: Request) -> None:
    """One hit on the visitor's budget of letter-sending requests (saves
    and link requests): a bucket apart from new checks, so saving a result
    never costs a check."""


async def _throttled(throttle, request: Request) -> None:
    """One hit on a per-IP bucket; over it - our coded 429."""
    try:
        await throttle(request)
    except RateLimitExceeded as exc:
        raise AppError(
            "public_check_rate_limited",
            429,
            headers={"Retry-After": _retry_after(request)},
        ) from exc


# The ``action`` of each form's widget (``useTurnstileGate`` on the page):
# a token solved for one form passes no other.
ACTION_CHECK = "public_check"
ACTION_SAVE = "public_check_save"
ACTION_LINK = "public_check_link"


async def _guard(
    throttle, request: Request, turnstile_token: str | None, action: str
) -> None:
    """The per-IP throttle, then the captcha, solved for this form on the
    check host: cheapest refusal first."""
    await _throttled(throttle, request)
    if not await verify_turnstile(
        settings.public_check_turnstile_secret,
        turnstile_token,
        remote_ip=client_ip(request),
        action=action,
        hostname=urlsplit(settings.public_check_origin).hostname,
    ):
        raise AppError("public_check_captcha_failed", 400)


def _retry_after(request: Request) -> str:
    """Seconds until the visitor's exhausted window resets - what slowapi
    itself would put in its headers (the failed limit is on the request)."""
    item, keys = request.state.view_rate_limit
    try:
        reset = limiter.limiter.get_window_stats(item, *keys).reset_time
    except Exception:  # noqa: BLE001 - the storage blinked; the window bounds it
        return str(item.get_expiry())
    return str(max(1, math.ceil(reset - time.time())))


router = APIRouter(
    prefix="/public-check",
    tags=["public-check"],
    dependencies=[Depends(require_enabled)],
)


@router.post("/checks", response_model=CheckCreated, status_code=202)
async def create_check(
    data: CheckCreate, request: Request, db: AsyncSession = Depends(get_db)
):
    """Queue a check; the page polls ``GET /checks/{token}`` until it is
    ``ready`` or ``error``."""
    # Before the throttle and the captcha: a paused service spends neither
    # the visitor's budget nor a call to Cloudflare.
    if settings.public_check_paused:
        raise service.closed_for_today()
    await _guard(_throttle, request, data.turnstile_token, ACTION_CHECK)
    await service.spend_daily("checks", settings.public_check_daily_limit)
    check, token, owner_key = await service.create_check(db, data)
    # Imported here like the other routers: Celery stays out of the
    # request-path import graph.
    from app.core.task_enqueue import enqueue_task
    from app.modules.public_check import tasks

    try:
        # No tenant or user in the headers: nobody is listening for the
        # task's events, and the run names its own context (``work.tasks``).
        enqueue_task(
            tasks.run_check,
            str(check.id),
            tenant_id=None,
            user_id=None,
            module="public_check",
            action=service.USAGE_ACTION,
        )
    except Exception as exc:
        # The queue is down: the row says so at once rather than read as
        # queued until it goes stale.
        logger.exception("public check %s could not be queued", check.id)
        await service.fail_check(db, check.id, "service_error")
        raise AppError("public_check_unavailable", 503) from exc
    return {
        "token": token,
        "owner_key": owner_key,
        "status": check.status,
        "expires_at": check.expires_at,
    }


@router.get("/checks/{token}", response_model=CheckRead)
async def get_check(token: str, db: AsyncSession = Depends(get_db)):
    return await service.get_check(db, token)


# --- Saved by email (HRP-926) -------------------------------------------------


@router.post("/checks/{token}/save", response_model=SaveResult)
async def save_check(
    token: str, data: SaveRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    """Keep the check by email: always ``confirm`` - a letter for this
    check goes to the address, and only its click keeps the check."""
    await _guard(_throttle_mail, request, data.turnstile_token, ACTION_SAVE)
    return {"status": await service.save_check(db, token, data)}


async def _send_link(bind, email: str) -> None:
    """``service.request_link`` after the answer, in a session of its own -
    the request's is closed by then. A failure is logged: nobody waits."""
    try:
        async with AsyncSession(bind, expire_on_commit=False) as db:
            await service.request_link(db, email)
    except Exception:
        logger.exception("public check: a link request failed")


@router.post("/links", response_model=LinkSent, status_code=202)
async def request_link(
    data: LinkRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """The "my checks" link (or a new confirmation letter) to an address.
    Always the same 202, and in the same time: the lookup and the letter
    run after the answer - a known address must not answer slower than an
    unknown one."""
    await _guard(_throttle_mail, request, data.turnstile_token, ACTION_LINK)
    background.add_task(_send_link, db.bind, data.email)
    return {}


@router.post("/confirm/{token}", response_model=Confirmed)
async def confirm_email(token: str, db: AsyncSession = Depends(get_db)):
    await service.confirm_email(db, token)
    return {}


@router.post("/unsubscribe/{token}", response_model=Unsubscribed)
async def unsubscribe(token: str, db: AsyncSession = Depends(get_db)):
    await service.unsubscribe(db, token)
    return {}


@router.get("/mine/{token}", response_model=SavedChecks)
async def list_saved(token: str, db: AsyncSession = Depends(get_db)):
    return await service.list_saved(db, token)


@router.get("/mine/{token}/checks/{check_id}", response_model=CheckRead)
async def get_saved(
    token: str, check_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await service.get_saved(db, token, check_id)


@router.delete("/mine/{token}", status_code=204)
async def delete_saved(token: str, db: AsyncSession = Depends(get_db)):
    await service.delete_saved(db, token)


# --- Moved into a workspace (HRP-927) -----------------------------------------


@router.post(
    "/mine/{token}/move",
    response_model=Moved,
    # Who may create a Coverage process may bring one in.
    dependencies=[Depends(manage_actor)],
)
async def move_saved(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The "move to HRPulsar" button of "my checks", signed in on the app
    host: the address's checks become processes of the caller's workspace -
    only when the caller's email is the link's address."""
    return await move.move_by_link(db, token, user)


# --- Dictation (HRP-947) ------------------------------------------------------


@limiter.limit(lambda: settings.public_check_voice_rate_limit)
async def _throttle_voice(request: Request) -> None:
    """One hit on the visitor's budget of recordings: a bucket of its own,
    so dictating never costs a check."""


@router.post("/transcribe", response_model=Transcript)
async def transcribe(request: Request, db: AsyncSession = Depends(get_db)):
    """A recording - multipart, the file in the field ``audio`` - in, its
    text out. No body parameter on purpose: FastAPI would read the whole
    body before the pause and the throttle; ``voice`` streams it under a
    ceiling."""
    if settings.public_check_paused:
        raise service.closed_for_today()
    await _throttled(_throttle_voice, request)
    return await voice.transcribe(db, request)


# --- Funnel beacons (HRP-931) -------------------------------------------------


@limiter.limit(lambda: funnel.EVENT_RATE_LIMIT)
async def _throttle_event(request: Request) -> None:
    """One hit on the visitor's budget of beacons, a bucket of its own."""


@router.post("/events", status_code=204)
async def track_event(
    data: CheckEvent, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    """A step of the funnel the page saw. Always 204: a beacon over the
    visitor's limit is dropped without a word - it must never break a page,
    and a script learns nothing from it."""
    try:
        await _throttle_event(request)
    except RateLimitExceeded:
        return
    await funnel.record_event(db, data.event, data.utm.source if data.utm else None)


# --- E2E seeds (HRP-932) -----------------------------------------------------
# Imported last: the seed module reads this one's throttle lazily. Every
# route of it answers 404 outside E2E/dev (``require_dev_endpoint``).
from app.modules.public_check.e2e_seed import router as _e2e_seed_router  # noqa: E402

router.include_router(_e2e_seed_router)
