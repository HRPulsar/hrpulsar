"""The anonymous process check (HRP-922): a visitor's text runs through the
Coverage pipeline unchanged, inside one sandbox company of the platform.

* The sandbox - a tenant with a reserved slug and one service user (a
  decomposition run needs a user). Created on the first check, idempotent
  and race-safe on the slug's unique index. Not ``is_demo``: the demo
  lifecycle would purge it. Inactive, as is its user - unverified, with a
  random password nobody knows - so nobody signs in to it, the tenant's
  public profile does not exist and the monthly credit refill skips it; it
  has no employees, so no reminder or digest reaches it. One sandbox means
  one breakdown cache (HRP-921 keys by company): every check shares it.
* A check is a container of type ``process`` and a ``pending`` run over it.
  The run's ``params`` make the worker answer in the visitor's language,
  file the model calls under ``public_check.run`` against the check, and
  charge nothing (``work.tasks``).
* When the run is ready, its steps are materialised without the billing
  wrapper of the tenant's apply, Coverage is computed over the container,
  and the outcome is frozen on the check (``schemas.CheckResult``).
* Intake spends a daily budget (HRP-923, ``spend_daily``) behind one
  pause switch; a daily beat job purges expired checks with their
  containers (``purge_expired``).
* A visitor keeps checks by email (HRP-926): a save ties a check to an
  address and mails a letter for that check; its click - the proof the
  address's owner wants it - takes the check's term away.
  "My checks" open by a 24-hour link, letters go out in the address's own
  language with a permanent unsubscribe link (``save_check`` and below).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.redis import redis_client
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.primitives.catalog_data import CATALOG_VERSION
from app.modules.primitives.models import Primitive
from app.modules.public_check import funnel
from app.modules.public_check.models import PublicCheck, PublicCheckEmail
from app.modules.public_check.schemas import (
    CheckCreate,
    CheckResult,
    ResultStep,
    SaveRequest,
    StepReason,
)
from app.modules.work.models import WorkContainer, WorkDecompositionSession, WorkStep

logger = logging.getLogger(__name__)

# A result without an email lives this long (decision of 2026-09-23).
RESULT_TTL = timedelta(days=10)
# What the model calls of a check are filed under (HRP-923's budget and
# HRP-931's cost per check read it). Not a price-list code: no credits.
USAGE_ACTION = "public_check.run"
# Underscores: open registration derives a slug from the company name and
# turns every underscore into a hyphen (``auth.service._slugify``, the
# signup flow likewise), so no visitor can register a company that holds
# this slug before the sandbox exists - and own every check run in it.
SANDBOX_SLUG = "public_check_sandbox"
SANDBOX_NAME = "Public process check"
# ``.invalid`` (RFC 2606) can never receive mail.
SANDBOX_EMAIL = "public-check@sandbox.invalid"
TITLE_MAX = 120
# A check still pending or running after this is reported as failed - the
# worker died without a word; the decomposition reaper has the same cutoff.
STUCK_AFTER = timedelta(minutes=30)
# A daily budget key outlives its UTC day; the date in the key resets it.
DAILY_KEY_TTL_S = 2 * 86400
# Rows per transaction of the purge - short locks, no long transaction.
PURGE_BATCH = 200
# A sandbox container no check points at, older than this, is debris.
ORPHAN_AFTER = timedelta(days=1)
# Saved by email (HRP-926): how long the letters' links work, and how many
# letters one address gets an hour - a stranger's mailbox must not be
# bombed through the save form. An unconfirmed address with no check left,
# this old, is dropped by the daily purge.
CONFIRM_TTL = timedelta(days=7)
MAGIC_TTL = timedelta(hours=24)
MAIL_CAP = 3
MAIL_WINDOW_S = 3600
UNCONFIRMED_ADDRESS_TTL = RESULT_TTL
CONFIRM_TEMPLATE = "public_check_confirm"
MAGIC_TEMPLATE = "public_check_magic_link"

_FREQUENCY = {
    "daily": "every day",
    "weekly": "every week",
    "monthly": "every month",
    "quarterly": "every quarter",
    "yearly": "once a year",
    "ad_hoc": "on demand",
}
STRONG_VERDICTS = ("strong", "better_than_human")
# Read by the model before a description the visitor dictated (HRP-947).
DICTATED_NOTE = (
    "Note: the visitor dictated this description by voice. It is a speech "
    "recognition transcript and may contain misheard words."
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def ensure_sandbox(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """The sandbox tenant and its service user, created on first use. Two
    first checks at once both insert; ``ON CONFLICT DO NOTHING`` makes the
    second wait for the first and keep its rows. Flushed, not committed:
    the caller's commit carries them.

    Only an inactive tenant is the sandbox: an active one holding the slug
    is somebody's company, and visitors' texts must never land in it - the
    check is then unavailable until an operator looks."""
    sandbox = select(Tenant.id).where(
        Tenant.slug == SANDBOX_SLUG, Tenant.is_active.is_(False)
    )
    tenant_id = await db.scalar(sandbox)
    if tenant_id is None:
        await db.execute(
            insert(Tenant)
            .values(name=SANDBOX_NAME, slug=SANDBOX_SLUG, is_active=False)
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        tenant_id = await db.scalar(sandbox)
    if tenant_id is None:
        logger.error(
            "public check: slug %r is held by an active tenant; refusing to "
            "run checks in it",
            SANDBOX_SLUG,
        )
        raise AppError("public_check_unavailable", 503)
    user = select(User.id).where(
        User.tenant_id == tenant_id, User.email == SANDBOX_EMAIL
    )
    user_id = await db.scalar(user)
    if user_id is None:
        await db.execute(
            insert(User)
            .values(
                tenant_id=tenant_id,
                email=SANDBOX_EMAIL,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                first_name="Public",
                last_name="Check",
                is_active=False,
            )
            .on_conflict_do_nothing(constraint="uq_user_email_tenant")
        )
        user_id = await db.scalar(user)
    if user_id is None:  # the insert above cannot lose; never run userless
        raise AppError("public_check_unavailable", 503)
    return tenant_id, user_id


def _title(description: str) -> str:
    """The first line, cut by characters - a single long token is still a
    title, not an ellipsis."""
    line = description.splitlines()[0].strip()
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 3] + "..."


def process_text(data: CheckCreate) -> str:
    """What the model reads: the description, then the answers that change
    the breakdown. They are part of the text, so the breakdown cache tells
    two inputs apart without a key of its own. The rate is not here: it
    prices the result and changes no step. A dictated description (HRP-947)
    opens with ``DICTATED_NOTE`` - here, not in the shared Coverage prompt,
    whose version would reset every company's breakdown cache."""
    answers = data.answers
    lines = [
        f"Industry: {answers.industry}" if answers.industry else None,
        f"Team size: {answers.team_size} people" if answers.team_size else None,
        (
            f"The process runs {_FREQUENCY[answers.frequency]}."
            if answers.frequency
            else None
        ),
    ]
    facts = "\n".join(line for line in lines if line)
    text = (
        f"{DICTATED_NOTE}\n\n{data.description}" if data.dictated else data.description
    )
    return f"{text}\n\n{facts}" if facts else text


def closed_for_today() -> AppError:
    """The "try again tomorrow" refusal of the pause and of a spent daily
    budget, with ``Retry-After`` at the next 00:00 UTC."""
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    seconds = math.ceil((midnight - now).total_seconds())
    return AppError(
        "public_check_daily_limit", 429, headers={"Retry-After": str(seconds)}
    )


def daily_key(counter: str) -> str:
    """Today's (UTC) Redis key of a daily budget counter."""
    return f"public_check:daily:{counter}:{datetime.now(UTC).date().isoformat()}"


async def spend_daily(counter: str, limit: int, amount: int = 1) -> None:
    """Spend ``amount`` of today's (UTC) budget of ``counter`` or refuse
    with the "try again tomorrow" 429. Checks spend ``checks``, one each,
    on intake before they are queued; the dictated minutes of HRP-947 are
    the next counter, under the same pause switch, which closes them all
    at once. ``amount`` is a positive whole number - minutes are rounded
    up (``math.ceil``) before they are spent. ``limit`` 0 means no cap."""
    if settings.public_check_paused:
        raise closed_for_today()
    if not isinstance(amount, int) or amount < 1:
        raise ValueError(f"amount must be a positive whole number, got {amount!r}")
    if limit <= 0:
        return
    key = daily_key(counter)
    try:
        async with redis_client() as client, client.pipeline(transaction=True) as pipe:
            pipe.set(key, 0, ex=DAILY_KEY_TTL_S, nx=True)
            pipe.incrby(key, amount)
            _, spent = await pipe.execute()
    except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
        # Only an unreachable Redis; a reply error is a bug and surfaces.
        # Fail closed: what the budget guards costs money (model calls,
        # transcription), and an uncounted spend is an uncapped one.
        logger.warning(
            "public check: daily budget %r not counted, Redis unavailable; refusing",
            counter,
            exc_info=True,
        )
        raise AppError("public_check_unavailable", 503) from exc
    if int(spent) > limit:
        raise closed_for_today()


async def adjust_daily(counter: str, delta: int) -> None:
    """Correct today's ``counter`` by ``delta`` - a reservation settled at
    its real size. A failure is logged: the reservation stands, which
    over-counts and never under-counts."""
    if delta == 0:
        return
    try:
        async with redis_client() as client:
            await client.incrby(daily_key(counter), delta)
    except (RedisConnectionError, RedisTimeoutError, OSError):
        logger.warning(
            "public check: daily budget %r not corrected by %d, Redis unavailable",
            counter,
            delta,
            exc_info=True,
        )


async def create_check(
    db: AsyncSession, data: CheckCreate
) -> tuple[PublicCheck, str, str]:
    """The check, its container and its pending run, in one commit. Returns
    the row, the link token and the owner key - the only time either exists
    in clear."""
    from app.modules.work.prompts import PROMPT_VERSION

    tenant_id, user_id = await ensure_sandbox(db)
    snapshot = {
        "type": "process",
        "title": _title(data.description),
        "description": process_text(data),
        "goal": None,
    }
    container = WorkContainer(
        tenant_id=tenant_id,
        owner_id=user_id,
        created_by_id=user_id,
        catalog_version=CATALOG_VERSION,
        **snapshot,
    )
    db.add(container)
    await db.flush()
    check_id = uuid.uuid4()
    run = WorkDecompositionSession(
        tenant_id=tenant_id,
        user_id=user_id,
        container_id=container.id,
        params={
            "billing_action": USAGE_ACTION,
            "free": True,
            "content_language": data.locale,
            "usage_entity": {"type": "public_check", "id": str(check_id)},
        },
        base_snapshot={"container": snapshot},
        status="pending",
        prompt_version=PROMPT_VERSION,
    )
    db.add(run)
    await db.flush()
    token = secrets.token_urlsafe(32)
    owner_key = secrets.token_urlsafe(32)
    check = PublicCheck(
        id=check_id,
        token_hash=hash_token(token),
        owner_key_hash=hash_token(owner_key),
        status="pending",
        description=data.description,
        answers=data.answers.model_dump(mode="json", exclude_none=True),
        locale=data.locale,
        utm=(data.utm.model_dump(exclude_none=True) if data.utm else None) or None,
        dictated=data.dictated,
        container_id=container.id,
        session_id=run.id,
        expires_at=datetime.now(UTC) + RESULT_TTL,
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    return check, token, owner_key


async def _live_check(db: AsyncSession, token: str) -> PublicCheck:
    """The check behind a link. Unknown, expired and switched off all
    answer the same 404 - the link is no oracle."""
    check = await db.scalar(
        select(PublicCheck)
        .where(PublicCheck.token_hash == hash_token(token))
        .execution_options(populate_existing=True)
    )
    if check is None or (
        check.expires_at is not None and check.expires_at <= datetime.now(UTC)
    ):
        raise AppError("public_check_not_found", 404)
    return check


async def get_check(db: AsyncSession, token: str) -> dict[str, Any]:
    """The check behind a link, as ``schemas.CheckRead``."""
    return await _read(db, await _live_check(db, token))


async def _read(db: AsyncSession, check: PublicCheck) -> dict[str, Any]:
    """A check as ``schemas.CheckRead``. A read writes nothing: a run the
    worker abandoned is reported as failed, the way the decomposition
    reaper would leave it."""
    now = datetime.now(UTC)
    status, phase, error_code = check.status, None, check.error_code
    if status in ("pending", "running"):
        run = (
            await db.get(
                WorkDecompositionSession, check.session_id, populate_existing=True
            )
            if check.session_id
            else None
        )
        if run is None or run.status in ("error", "cancelled"):
            status = "error"
            error_code = (run.error_code if run else None) or "service_error"
        # The run's clock, as the reaper reads it: the phase flip refreshes it.
        elif run.updated_at < now - STUCK_AFTER:
            status, error_code = "error", "reaped_stuck"
        elif run.status == "running":
            phase = run.phase
        elif run.status in ("ready", "applied"):
            phase = "finishing"
    return {
        "status": status,
        "phase": phase,
        "error_code": error_code,
        "locale": check.locale,
        "title": _title(check.description),
        "description": check.description,
        "answers": check.answers,
        "utm": check.utm,
        "dictated": check.dictated,
        "created_at": check.created_at,
        "expires_at": check.expires_at,
        "result": check.result if status == "ready" else None,
    }


async def claim_check(db: AsyncSession, check_id: uuid.UUID) -> uuid.UUID | None:
    """``pending`` -> ``running``, once: the run's id for the worker that
    won, None for a duplicate delivery or a check already over."""
    claimed = await db.execute(
        update(PublicCheck)
        .where(PublicCheck.id == check_id, PublicCheck.status == "pending")
        .values(status="running")
        .returning(PublicCheck.session_id)
    )
    session_id = claimed.scalar_one_or_none()
    await db.commit()
    return session_id


async def fail_check(db: AsyncSession, check_id: uuid.UUID, error_code: str) -> None:
    await db.execute(
        update(PublicCheck)
        .where(
            PublicCheck.id == check_id, PublicCheck.status.in_(("pending", "running"))
        )
        .values(status="error", error_code=error_code[:40])
    )
    await db.commit()


async def finish_check(db: AsyncSession, check_id: uuid.UUID) -> str:
    """After the run: a failed one fails the check with its code; a ready
    one is materialised into the container (unbilled), Coverage is computed
    over it and frozen on the check. A run still in flight is left to the
    worker running it. Also what a redelivered task does with a check a
    dead worker left ``running``: materialising is idempotent on the
    check's key, so a run already applied is frozen too. Returns the
    check's status."""
    from app.modules.work import coverage
    from app.modules.work import service as work_service

    check = await db.get(PublicCheck, check_id)
    if check is None or check.status != "running":
        return check.status if check else "missing"
    run = (
        await db.get(WorkDecompositionSession, check.session_id, populate_existing=True)
        if check.session_id
        else None
    )
    if run is not None and run.status in ("pending", "running"):
        return "running"
    if run is None or run.status not in ("ready", "applied"):
        code = (run.error_code if run else None) or "service_error"
        await fail_check(db, check_id, code)
        return "error"
    await work_service.materialise_session(
        db, run.tenant_id, run.id, idempotency_key=f"public-check:{check_id}"
    )
    computed = await coverage.compute(
        db, run.tenant_id, run.container_id, schedule_mapping=False, people=False
    )
    steps = {
        s.id: s
        for s in (
            await db.execute(
                select(WorkStep).where(WorkStep.container_id == run.container_id)
            )
        ).scalars()
    }
    catalog = {
        code: (kind, verdict)
        for code, kind, verdict in (
            await db.execute(
                select(Primitive.code, Primitive.kind, Primitive.ai_verdict)
            )
        ).tuples()
    }
    result = build_result(computed, steps, catalog, check.answers)
    flipped = await db.execute(
        update(PublicCheck)
        .where(PublicCheck.id == check_id, PublicCheck.status == "running")
        .values(status="ready", result=result.model_dump(mode="json"))
    )
    await db.commit()
    if flipped.rowcount:  # type: ignore[attr-defined]
        return "ready"
    await db.refresh(check)  # another delivery settled it first
    return check.status


async def purge_expired(db: AsyncSession) -> dict[str, int]:
    """The daily cleanup (HRP-923): checks past their term go with their
    sandbox containers - the FK cascades take the steps, their codes and
    skills, the runs and the access rows; the AI call journal keeps its
    rows (the cost per check, HRP-931). A check without a term (NULL,
    claimed by an email) is never touched. Then the sandbox containers no
    check points at, a day old - debris of a check that never committed.

    Batches of ``PURGE_BATCH``, a commit each; a second run finds nothing.
    Containers are deleted only inside the sandbox, whatever a row says.

    Last, the unconfirmed addresses (HRP-926) older than
    ``UNCONFIRMED_ADDRESS_TTL`` with no check left - their checks expired
    unconfirmed. A confirmed address stays until its owner deletes it."""
    now = datetime.now(UTC)
    sandbox_id = await _sandbox_id(db)
    checks = 0
    while True:
        batch = (
            select(PublicCheck.id)
            .where(PublicCheck.expires_at < now)
            .limit(PURGE_BATCH)
        )
        gone = (
            await db.execute(
                delete(PublicCheck)
                .where(PublicCheck.id.in_(batch))
                .returning(*funnel.ROLLUP_COLUMNS)
            )
        ).all()
        if not gone:
            break
        # The funnel keeps what the rows counted (HRP-931).
        await funnel.roll_up(db, gone)
        await db.execute(
            delete(WorkContainer).where(
                WorkContainer.id.in_([c.container_id for c in gone if c.container_id]),
                WorkContainer.tenant_id == sandbox_id,
            )
        )
        await db.commit()
        checks += len(gone)
    orphans = 0
    while sandbox_id is not None:
        batch = (
            select(WorkContainer.id)
            .where(
                WorkContainer.tenant_id == sandbox_id,
                WorkContainer.created_at < now - ORPHAN_AFTER,
                ~exists().where(PublicCheck.container_id == WorkContainer.id),
            )
            .limit(PURGE_BATCH)
        )
        dropped = (
            await db.scalars(
                delete(WorkContainer)
                .where(WorkContainer.id.in_(batch))
                .returning(WorkContainer.id)
            )
        ).all()
        await db.commit()
        if not dropped:
            break
        orphans += len(dropped)
    addresses = (
        await db.scalars(
            delete(PublicCheckEmail)
            .where(
                PublicCheckEmail.verified_at.is_(None),
                PublicCheckEmail.created_at < now - UNCONFIRMED_ADDRESS_TTL,
                # Re-read on the row version a concurrent save just wrote
                # (READ COMMITTED re-checks the target row's own columns, not
                # the NOT EXISTS below): an address a save re-used is spared.
                PublicCheckEmail.updated_at < now - UNCONFIRMED_ADDRESS_TTL,
                ~exists().where(PublicCheck.email_id == PublicCheckEmail.id),
            )
            .returning(PublicCheckEmail.id)
        )
    ).all()
    await db.commit()
    return {
        "checks": checks,
        "orphan_containers": orphans,
        "addresses": len(addresses),
    }


async def _sandbox_id(db: AsyncSession) -> uuid.UUID | None:
    return await db.scalar(
        select(Tenant.id).where(
            Tenant.slug == SANDBOX_SLUG, Tenant.is_active.is_(False)
        )
    )


# --- Saved by email (HRP-926) -------------------------------------------------


def _unsubscribe_token(email_id: uuid.UUID) -> str:
    """The address's permanent unsubscribe token: derived, not stored, so
    every letter carries the same one while the row keeps only its hash."""
    return hmac.new(
        settings.jwt_secret.encode(),
        f"public-check-unsubscribe:{email_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def _mail_slot(email: str) -> bool:
    """Take one of the address's ``MAIL_CAP`` letters an hour; False when
    they are spent. Counted per address, whoever asks - the per-IP
    throttle cannot see a stranger's mailbox being targeted from many
    networks."""
    key = f"public_check:mail:{hash_token(email)}"
    try:
        async with redis_client() as client, client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, MAIL_WINDOW_S, nx=True)
            sent, _ = await pipe.execute()
    except (RedisConnectionError, RedisTimeoutError, OSError):
        # ponytail: fail-open, unlike the daily budget (a letter costs no
        # model call) - while Redis is down only
        # the per-IP throttle (counted per worker) holds letters per address.
        logger.warning(
            "public check: letters per address not counted, Redis unavailable",
            exc_info=True,
        )
        return True
    return int(sent) <= MAIL_CAP


def _issue(address: PublicCheckEmail, check: PublicCheck | None = None) -> str:
    """A fresh token for a letter to the address: the confirmation of
    ``check`` (7 days), or else the address's "my checks" link (24 hours).
    The one issued before for the same check, or the address's link, stops
    working; the letters of other checks keep theirs. Returns it in clear."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    if check is not None:
        check.confirm_token_hash = hash_token(token)
        check.confirm_expires_at = now + CONFIRM_TTL
    else:
        address.magic_token_hash = hash_token(token)
        address.magic_expires_at = now + MAGIC_TTL
    # The derived token follows the server secret: a rotated secret
    # re-points the stored hash at the token the next letter carries.
    address.unsubscribe_token_hash = hash_token(_unsubscribe_token(address.id))
    return token


async def pending_check(
    db: AsyncSession, address: PublicCheckEmail
) -> PublicCheck | None:
    """The address's newest live check still waiting for its confirmation -
    what a confirmation letter asked for again confirms."""
    return await db.scalar(
        select(PublicCheck)
        .where(
            PublicCheck.email_id == address.id,
            PublicCheck.expires_at > datetime.now(UTC),
        )
        .order_by(PublicCheck.created_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _mail(
    db: AsyncSession, address: PublicCheckEmail, code: str, path: str
) -> None:
    """The letter ``code`` to the address, in the address's own language -
    never the language of the request that triggered it. Links point at
    the check host. Queued like every letter to someone without an
    account; a failure is logged there, never raised here."""
    from app.core.email import enqueue_email
    from app.modules.notification.service import (
        get_template_for_locale,
        render_db_template,
    )

    template = await get_template_for_locale(db, code, address.locale)
    if template is None:
        logger.error("public check: email template %r is missing", code)
        return
    origin = settings.public_check_origin
    subject, body = render_db_template(
        template,
        {
            "link_url": f"{origin}{path}",
            "unsubscribe_url": (
                f"{origin}/unsubscribe/{_unsubscribe_token(address.id)}"
            ),
            "check_host": urlsplit(origin).hostname or origin,
        },
    )
    enqueue_email(address.email, subject, body, template_code=code)


def _normalise(email: str) -> str:
    return email.strip().lower()


async def save_check(db: AsyncSession, token: str, data: SaveRequest) -> str:
    """Tie the check behind ``token`` to an address (``schemas.SaveResult``).

    A check kept already (no term) is ``public_check_already_saved``.
    Otherwise always ``confirm``, whatever the address: a save proves
    nothing about owning it, so the answer must not tell a confirmed
    address from a new one, and the check keeps its term until the owner
    clicks the letter of this check (``confirm_email``). The letter goes
    out within the address's hourly cap; past it there is none, and the
    check waits for a later save or a link request. A new address takes
    the save's language and consent; an existing one is left as it is - the
    marketing choice waits on the check until the click."""
    check = await _live_check(db, token)
    # The owner key, not the link: a shared link reads the result and
    # nothing more. A check without a key (older than it) is never saved.
    if (
        not data.owner_key
        or check.owner_key_hash is None
        or not hmac.compare_digest(check.owner_key_hash, hash_token(data.owner_key))
    ):
        raise AppError("public_check_not_owner", 403)
    if check.expires_at is None:
        # Kept already, by a confirmed address: whoever holds a shared link
        # must not move it out of its owner's "my checks".
        raise AppError("public_check_already_saved", 409)
    email = _normalise(data.email)
    now = datetime.now(UTC)
    new_id = uuid.uuid4()
    upsert = insert(PublicCheckEmail).values(
        id=new_id,
        email=email,
        locale=data.locale,
        consent_at=now,
        unsubscribe_token_hash=hash_token(_unsubscribe_token(new_id)),
    )
    # DO UPDATE, not DO NOTHING: the row comes back locked in one statement,
    # and its ``updated_at`` moves - the purge of unconfirmed addresses
    # re-reads it on the new row version and spares an address in use.
    address_id = await db.scalar(
        upsert.on_conflict_do_update(
            index_elements=["email"],
            set_={"email": upsert.excluded.email, "updated_at": func.now()},
        ).returning(PublicCheckEmail.id)
    )
    address = await db.get(PublicCheckEmail, address_id, populate_existing=True)
    assert address is not None  # just upserted, row-locked
    check.email_id = address.id
    check.confirm_marketing = data.marketing
    # A letter sent for the check before went to the address it was saved
    # with then: it must not confirm the check for this one.
    check.confirm_token_hash = check.confirm_expires_at = None
    confirm = _issue(address, check) if await _mail_slot(email) else None
    await db.commit()
    if confirm:
        await _mail(db, address, CONFIRM_TEMPLATE, f"/confirm/{confirm}")
    return "confirm"


async def confirm_email(db: AsyncSession, token: str) -> None:
    """The link of a check's confirmation letter, clicked by the owner of
    the address: the address is confirmed, the save's marketing opt-in
    becomes the address's (an unsubscribe stands), and this check - this
    one only - loses its term. Again on a kept check is fine, also past
    the link's term; an unknown, replaced or expired link, or one of an
    expired check, is ``public_check_link_invalid``."""
    now = datetime.now(UTC)
    check = await db.scalar(
        select(PublicCheck)
        .where(
            PublicCheck.confirm_token_hash == hash_token(token),
            PublicCheck.email_id.is_not(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if check is not None and check.expires_at is None:
        return
    if (
        check is None
        or check.confirm_expires_at is None
        or check.confirm_expires_at <= now
        or check.expires_at is None
        or check.expires_at <= now
    ):
        raise AppError("public_check_link_invalid", 404)
    address = await db.get(
        PublicCheckEmail, check.email_id, with_for_update=True, populate_existing=True
    )
    assert address is not None  # the FK cascades the check away with it
    address.verified_at = address.verified_at or now
    if (
        check.confirm_marketing
        and address.unsubscribed_at is None
        and not address.marketing_opt_in
    ):
        address.marketing_opt_in = True
        address.marketing_opt_in_at = now
    check.expires_at = None
    await db.commit()


async def request_link(db: AsyncSession, email: str) -> None:
    """A visitor asks for their link. Confirmed address: the "my checks" link.
    Unconfirmed: a new confirmation letter for its newest check still
    waiting - the step it misses. Unknown, or nothing to confirm: nothing.
    All within the hourly cap. The router runs it after answering, the same
    202 for every address in the same time (no oracle, in the body or in
    the clock)."""
    address = await db.scalar(
        select(PublicCheckEmail)
        .where(PublicCheckEmail.email == _normalise(email))
        .with_for_update()
    )
    if address is None:
        return
    if address.verified_at is not None:
        code, check = MAGIC_TEMPLATE, None
    else:
        code, check = CONFIRM_TEMPLATE, await pending_check(db, address)
        if check is None:
            return
    if not await _mail_slot(address.email):
        return
    token = _issue(address, check)
    await db.commit()
    await _mail(db, address, code, f"/confirm/{token}" if check else f"/my/{token}")


async def _magic_address(db: AsyncSession, token: str) -> PublicCheckEmail:
    address = await db.scalar(
        select(PublicCheckEmail).where(
            PublicCheckEmail.magic_token_hash == hash_token(token),
            PublicCheckEmail.magic_expires_at > datetime.now(UTC),
        )
    )
    if address is None:
        raise AppError("public_check_link_invalid", 404)
    return address


def _kept():
    """A check kept by the click of its confirmation letter - the only ones
    "my checks" shows and moves: a save alone proves nothing about owning
    the address, so a stranger's save never reaches its owner's list."""
    return PublicCheck.expires_at.is_(None)


async def list_saved(db: AsyncSession, token: str) -> dict[str, Any]:
    """The checks behind a "my checks" link, newest first (``SavedChecks``)."""
    address = await _magic_address(db, token)
    checks = (
        await db.scalars(
            select(PublicCheck)
            .where(PublicCheck.email_id == address.id, _kept())
            .order_by(PublicCheck.created_at.desc())
        )
    ).all()
    return {
        "email": address.email,
        "checks": [
            {
                "id": c.id,
                "created_at": c.created_at,
                "title": _title(c.description),
                "status": c.status,
                "share_moves": ((c.result or {}).get("shares") or {}).get("moves"),
                "expires_at": c.expires_at,
                "moved": c.moved_at is not None,
            }
            for c in checks
        ],
        # HRP-927: sign in or register to move the checks.
        "account": bool(
            await db.scalar(
                select(
                    exists().where(
                        func.lower(User.email) == address.email, User.is_active
                    )
                )
            )
        ),
    }


async def get_saved(
    db: AsyncSession, token: str, check_id: uuid.UUID
) -> dict[str, Any]:
    """One check of "my checks", as ``CheckRead`` - the way back to a
    result whose own link token is not stored."""
    address = await _magic_address(db, token)
    check = await db.scalar(
        select(PublicCheck).where(
            PublicCheck.id == check_id,
            PublicCheck.email_id == address.id,
            _kept(),
        )
    )
    if check is None:
        raise AppError("public_check_not_found", 404)
    return await _read(db, check)


async def unsubscribe(db: AsyncSession, token: str) -> None:
    """The permanent link in every letter: no marketing to the address.
    Again is fine and keeps the first time."""
    address = await db.scalar(
        select(PublicCheckEmail).where(
            PublicCheckEmail.unsubscribe_token_hash == hash_token(token)
        )
    )
    if address is None:
        raise AppError("public_check_link_invalid", 404)
    address.marketing_opt_in = False
    address.unsubscribed_at = address.unsubscribed_at or datetime.now(UTC)
    await db.commit()


async def delete_saved(db: AsyncSession, token: str) -> None:
    """The visitor's "delete my data": the address and every check of it, with their
    sandbox containers, as the purge removes them. The AI call journal
    keeps its rows - they carry the check's id, nothing personal."""
    address = await _magic_address(db, token)
    sandbox_id = await _sandbox_id(db)
    gone = (
        await db.execute(
            delete(PublicCheck)
            .where(PublicCheck.email_id == address.id)
            .returning(*funnel.ROLLUP_COLUMNS)
        )
    ).all()
    # Counters, not data: the funnel keeps what the rows counted (HRP-931).
    await funnel.roll_up(db, gone)
    await db.execute(
        delete(WorkContainer).where(
            WorkContainer.id.in_([c.container_id for c in gone if c.container_id]),
            WorkContainer.tenant_id == sandbox_id,
        )
    )
    await db.execute(delete(PublicCheckEmail).where(PublicCheckEmail.id == address.id))
    await db.commit()


# --- The snapshot -------------------------------------------------------------


def deciding_codes(
    mode: str | None, codes: list[str], catalog: dict[str, tuple[str, str]]
) -> list[str]:
    """The codes behind the mode, by the order of checks in
    ``coverage.automation_mode``: a boundary code blocks physically, a
    judgement code blocks, accountability needs review (no code decides
    that), all-strong is automatable, the rest are drafts."""
    if mode == "blocked_physical":
        return [c for c in codes if catalog[c][0] == "boundary"]
    if mode == "blocked_judgment":
        return [c for c in codes if catalog[c][1] == "no"]
    if mode == "draft_then_review":
        return [c for c in codes if catalog[c][1] not in STRONG_VERDICTS]
    if mode == "automatable":
        return list(codes)
    return []


def _step(row: dict[str, Any], step: WorkStep, catalog) -> ResultStep:
    return ResultStep(
        position=row["position"],
        title=step.title,
        description=step.description,
        codes=row["codes"],
        hours_per_run=float(step.hours_per_run) if step.hours_per_run else None,
        runs_per_year=step.runs_per_year,
        hours_per_year=row["hours_per_year"],
        reason=StepReason.model_validate(
            {
                "mode": row["mode"],
                "codes": deciding_codes(row["mode"], row["codes"], catalog),
                "responsibility": step.responsibility,
                "output_type": step.output_type,
            }
        ),
    )


def build_result(
    computed: dict[str, Any],
    steps: dict[uuid.UUID, WorkStep],
    catalog: dict[str, tuple[str, str]],
    answers: dict[str, Any],
) -> CheckResult:
    """``coverage.compute`` of the sandbox container, cut to the contract of
    the result page and priced at the visitor's rate."""
    from app.modules.work import coverage

    buckets: dict[str, list[ResultStep]] = {"moves": [], "to_review": [], "stays": []}
    out_of_scope: list[ResultStep] = []
    for row in computed["steps"]:
        entry = _step(row, steps[row["step_id"]], catalog)
        if row["in_scope"]:
            buckets[coverage.BUCKET_OF_MODE[row["mode"]]].append(entry)
        else:
            out_of_scope.append(entry)
    summary = coverage.summary_of(computed)
    money = None
    rate = answers.get("hourly_rate")
    if rate:
        estimated = [
            r
            for r in computed["steps"]
            if r["in_scope"] and r["hours_per_year"] is not None
        ]
        priced = coverage.money_of(estimated, {r["step_id"]: rate for r in estimated})
        if priced is not None:
            priced.pop("unpriced")
            money = {**priced, "currency": answers.get("currency", "EUR")}
    return CheckResult.model_validate(
        {
            "preliminary": any(r["tentative"] for r in computed["steps"]),
            "catalog_version": CATALOG_VERSION,
            "shares": summary["shares"],
            "hours": summary["hours"],
            "money": money,
            "buckets": buckets,
            "out_of_scope": out_of_scope,
        }
    )
