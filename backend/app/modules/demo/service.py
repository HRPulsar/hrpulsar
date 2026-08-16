"""Public-demo sandbox service (HRP-251 — D3).

Exposes :func:`create_demo_session`, the one mutating call behind
``POST /api/demo/start``. Wraps every guard described in the Demo v2
plan: master switch, Turnstile bot guard, per-IP throttle, concurrent-
session cap, brand-new isolated tenant + user, seed, credit grant,
JWT pair, and a redirect URL pointing at the Elena interview that
opens the demo's first screen.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, get_args

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.redis import redis_client
from app.core.security import (
    create_demo_access_token,
    decode_token,
    hash_password,
)
from app.modules.ai_settings.models import TenantAISettings
from app.modules.ai_settings.schemas import ContentLanguage
from app.modules.ai_settings.service import DEFAULT_LANGUAGE
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.demo.seed import clone_seed_into_demo_tenant
from app.modules.demo.seed_data import (
    DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
    INVESTOR_MARKER,
)
from app.modules.demo.turnstile import verify_turnstile_token
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
)

logger = logging.getLogger(__name__)


# Stable 64-bit integer key for ``pg_advisory_xact_lock`` so two
# concurrent ``/api/demo/start`` requests serialise on the cap check.
# Generated once: ``hashtext('demo:concurrent-cap')`` rendered as a
# signed bigint. Hard-coded so we don't depend on a per-deploy SQL
# call to derive it.
_CONCURRENT_CAP_LOCK_KEY = 0x44454D4F434150  # ASCII 'DEMOCAP'


async def _enforce_rate_limit(remote_ip: str | None) -> None:
    """Per-IP per-hour throttle backed by an atomic Redis pipeline.

    ``DEMO_RATE_LIMIT_PER_IP_PER_HOUR = 0`` disables the throttle;
    ``remote_ip is None`` (proxy stripped the header in dev) also
    skips. Redis errors degrade **closed** (HRP-276 / H3) — fail-open
    would mean a single Redis flake lifts the demo's only application-
    level brake against scripted abuse.

    Implementation note: INCR and EXPIRE go through ``pipeline()`` so
    we can't crash between them and leave the IP key TTL-less. The
    earlier naive INCR-then-EXPIRE shape could permanently lock out
    an IP after a worker OOM between the two round-trips.
    """
    if remote_ip is None or settings.demo_rate_limit_per_ip_per_hour <= 0:
        return

    try:
        async with redis_client() as client:
            key = f"demo:rl:{remote_ip}"
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 3600)
                count, _ = await pipe.execute()
            if count > settings.demo_rate_limit_per_ip_per_hour:
                raise AppError(
                    "demo_rate_limited",
                    status.HTTP_429_TOO_MANY_REQUESTS,
                )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("demo rate-limit: redis unavailable, refusing request")
        raise AppError(
            "demo_sandbox_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc


async def _count_live_demo_tenants(db: AsyncSession, *, now: datetime) -> int:
    """Live demo tenant count under the standard pool predicate."""
    return (
        await db.execute(
            select(func.count(Tenant.id)).where(
                Tenant.is_demo.is_(True),
                Tenant.is_active.is_(True),
                Tenant.expires_at > now,
            )
        )
    ).scalar_one()


async def _enforce_concurrent_limit(db: AsyncSession, *, now: datetime) -> None:
    """503 when the live-session pool is full.

    Atomic variant: takes ``pg_advisory_xact_lock(_CONCURRENT_CAP_LOCK_KEY)``
    so the count + insert window serialises across parallel
    ``/demo/start`` calls. The lock is released when the current
    transaction commits — kept short on purpose (see HRP-276 / M4:
    the heavy seed runs in a separate transaction afterwards).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _CONCURRENT_CAP_LOCK_KEY},
    )
    live = await _count_live_demo_tenants(db, now=now)
    if live >= settings.demo_max_concurrent_sessions:
        raise AppError(
            "demo_sandbox_capacity_reached",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


async def _peek_concurrent_capacity(db: AsyncSession, *, now: datetime) -> None:
    """Best-effort cap check that does NOT take the advisory lock.

    HRP-276 / M4: used for fast-fail before rate-limit INCR so a full
    pool returns 503 without burning the IP's hourly allowance and
    without serialising on the advisory lock. The authoritative atomic
    check runs again inside ``_enforce_concurrent_limit`` immediately
    before the tenant insert, so a race that opens up between peek and
    enforce is caught there.
    """
    live = await _count_live_demo_tenants(db, now=now)
    if live >= settings.demo_max_concurrent_sessions:
        raise AppError(
            "demo_sandbox_capacity_reached",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


async def _create_demo_user(
    db: AsyncSession, tenant_id: uuid.UUID, *, now: datetime
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"demo-{uuid.uuid4().hex[:12]}@demo.hrpulsar.local",
        # Long random secret nobody will ever type — the demo never
        # uses password auth, it logs in via the JWT pair we return.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        first_name="Demo",
        last_name="User",
        tenant_id=tenant_id,
        email_verified_at=now,
    )
    db.add(user)
    await db.flush()

    role = (
        await db.execute(
            select(Role).where(
                Role.code == "admin",
                Role.is_system.is_(True),
            )
        )
    ).scalar_one_or_none()
    if role is None:
        # On a fresh install where the seed migration that creates the
        # system roles hasn't run, the demo user lands without any role
        # and the SPA will 403 on its first protected request. Surface
        # the misconfig instead of silently shipping a broken demo.
        logger.warning(
            "demo: system 'admin' role not found — demo user %s "
            "will start with no roles. Run the role-seed migration.",
            user.id,
        )
    else:
        await db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    return user


def _demo_content_language() -> str:
    """AI content language for a fresh demo tenant.

    White-label deployments run with ``DEFAULT_LOCALE`` other than
    ``en``; demo visitors there must get AI-generated content in the
    platform's language, not the global English default that
    ``ai_settings.get_or_default`` would lazily create on the first AI
    call. Interface locales and content languages are orthogonal axes,
    so a locale the AI layer doesn't support falls back to English.
    """
    if settings.default_locale in get_args(ContentLanguage):
        return settings.default_locale
    return DEFAULT_LANGUAGE


async def _grant_demo_credits(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    """Soft-import ``ee.credits.grant_bonus_credits`` (SaaS-only).

    On community / on-prem builds without ``ee/`` the import fails and
    we silently degrade to no credit grant — the credits engine is a
    no-op there anyway.
    """
    amount = settings.demo_initial_credits
    if amount <= 0:
        return 0
    try:
        from ee.credits import grant_bonus_credits
    except ImportError:
        return 0
    try:
        await grant_bonus_credits(db, tenant_id, user_id, amount, reason="demo_grant")
    except Exception:  # noqa: BLE001
        # Credit grant is best-effort — a transient DB hiccup, a partial
        # ee/ migration on a fresh deploy, or an HTTPException out of
        # ``_get_tc`` must not tear down a perfectly good tenant + seed.
        # The user just lands with zero bonus credits and will hit the
        # standard precheck flow on the first AI call.
        logger.exception("demo: bonus credit grant failed for tenant %s", tenant_id)
        return 0
    return amount


async def _find_first_screen_interview(
    db: AsyncSession, tenant_id: uuid.UUID
) -> uuid.UUID | None:
    """The interview the demo opens on the first screen.

    Elena Volkov's completed-interview row carries the deep AI analysis
    payload — clicking it lands on the citations panel that the demo
    pitch is built around.
    """
    return (
        await db.execute(
            select(Interview.id)
            .join(
                CandidateVacancy,
                Interview.candidate_vacancy_id == CandidateVacancy.id,
            )
            .join(Candidate, CandidateVacancy.candidate_id == Candidate.id)
            .where(
                Interview.tenant_id == tenant_id,
                Candidate.source == INVESTOR_MARKER,
                Candidate.email == DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


def _redirect_url_for(interview_id: uuid.UUID | None) -> str:
    if interview_id is None:
        return "/recruitment/vacancies"
    # The interview detail page renders the analysis panel inline —
    # there's no separate /analysis subroute. The trailing slash keeps
    # any future ``?tab=analysis`` query param attachable.
    return f"/recruitment/interviews/{interview_id}"


async def _try_resume_demo_session(
    db: AsyncSession, token: str
) -> dict[str, Any] | None:
    """Return the same demo session if ``token`` still points at a live
    demo tenant; otherwise ``None`` and the caller provisions a fresh
    one.

    Resume is silent: no rate-limit charge, no Turnstile re-check, no
    ``demo.session_started`` republish, no credit re-grant. The single
    side effect is bumping ``last_active_at`` so the inactivity sweep
    treats the call as a touch.
    """
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 — any decode/expiry error → fresh session
        return None

    if payload.get("type") != "access":
        return None
    tenant_id_raw = payload.get("tenant_id")
    user_id_raw = payload.get("sub")
    if not tenant_id_raw or not user_id_raw:
        return None
    try:
        tenant_uuid = uuid.UUID(str(tenant_id_raw))
        user_uuid = uuid.UUID(str(user_id_raw))
    except (TypeError, ValueError):
        return None

    tenant = await db.get(Tenant, tenant_uuid)
    if tenant is None or not tenant.is_demo:
        return None

    now = datetime.now(timezone.utc)
    if tenant.expires_at is not None and tenant.expires_at <= now:
        return None

    user = await db.get(User, user_uuid)
    if user is None or user.tenant_id != tenant.id:
        return None

    tenant.last_active_at = now
    await db.commit()
    await db.refresh(tenant)

    try:
        interview_id = await _find_first_screen_interview(db, tenant.id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "demo: first-screen lookup failed on resume for tenant %s", tenant.id
        )
        interview_id = None

    access = create_demo_access_token(str(user.id), str(tenant.id))
    logger.info("demo: resumed session tenant=%s user=%s", tenant.id, user.id)

    return {
        "access_token": access,
        "tenant_id": tenant.id,
        "expires_at": tenant.expires_at,
        "redirect_url": _redirect_url_for(interview_id),
        "credits_granted": 0,
        "resumed": True,
    }


async def create_demo_session(
    db: AsyncSession,
    *,
    turnstile_token: str | None,
    remote_ip: str | None,
    existing_token: str | None = None,
) -> dict[str, Any]:
    """Spin up a brand-new public-demo tenant + user + seed.

    Returns a dict with ``access_token``, ``refresh_token``,
    ``tenant_id``, ``expires_at``, ``redirect_url`` and
    ``credits_granted``. The router copies the refresh token into an
    httpOnly cookie and drops the rest into the response body.

    When ``existing_token`` is a bearer JWT for a still-live demo
    tenant the call short-circuits via :func:`_try_resume_demo_session`
    so a visitor who clicks "Try the demo" a second time lands back in
    their own sandbox instead of stranding the old one in the pool.
    """
    if not settings.demo_enabled:
        raise AppError(
            "demo_disabled",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if existing_token:
        resumed = await _try_resume_demo_session(db, existing_token)
        if resumed is not None:
            return resumed

    if not await verify_turnstile_token(turnstile_token, remote_ip=remote_ip):
        raise AppError("demo_bot_guard_failed", status.HTTP_400_BAD_REQUEST)

    # HRP-276 / M2: cheap peek first so a full pool returns 503 without
    # burning the IP's hourly INCR allowance.
    now = datetime.now(timezone.utc)
    await _peek_concurrent_capacity(db, now=now)

    await _enforce_rate_limit(remote_ip)

    # HRP-276 / M4: mini-transaction — take the advisory lock, re-check
    # the cap atomically, insert a Tenant row with a SHORT TTL, commit.
    # The mini-tx releases the lock in milliseconds so concurrent
    # /demo/start calls only serialise on the (~ms) cap check, not on
    # the (~hundreds of ms) seed clone that follows.
    #
    # HRP-276 / M4 follow-up: the tenant is born with a 5-minute
    # ``expires_at`` so a seed/credits failure can't strand a pool
    # slot for the full 4-hour session window — the next purge tick
    # (5 min default) sweeps the orphan automatically without a
    # fragile sync-cleanup path that risks deadlocking against the
    # async session's row locks. On a successful bootstrap we extend
    # ``expires_at`` to the real TTL below.
    await _enforce_concurrent_limit(db, now=now)
    tenant_uuid = uuid.uuid4()
    full_expires = now + timedelta(seconds=settings.demo_session_ttl_seconds)
    short_expires = now + timedelta(minutes=5)
    tenant = Tenant(
        id=tenant_uuid,
        name=f"Demo {tenant_uuid.hex[:6]}",
        slug=f"demo-{tenant_uuid.hex[:8]}",
        is_demo=True,
        expires_at=short_expires,
        last_active_at=now,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    # ── Outer transaction: user + role + seed + credits. No advisory
    # lock held, so parallel /demo/start calls can run their heavy
    # provisioning in parallel.
    user = await _create_demo_user(db, tenant.id, now=now)

    # Pin the tenant's AI content language to the platform default
    # locale up front — without an explicit row the first AI call would
    # lazily create one with the global English default, which is wrong
    # on white-label deployments.
    db.add(
        TenantAISettings(
            tenant_id=tenant.id,
            content_language=_demo_content_language(),
        )
    )

    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)

    credits_granted = await _grant_demo_credits(
        db, tenant_id=tenant.id, user_id=user.id
    )

    # Extend to the real session TTL only once everything provisioned
    # cleanly — see the M4 follow-up note above.
    tenant.expires_at = full_expires

    await db.commit()
    await db.refresh(tenant)
    await db.refresh(user)

    # ── Redirect target ──────────────────────────────────────────────
    # HRP-276 / L2: a transient DB error on the redirect lookup must
    # not 500-out a fully-provisioned demo (slot would be burned, user
    # would see a generic error). Fall back to /recruitment/vacancies.
    try:
        interview_id = await _find_first_screen_interview(db, tenant.id)
    except Exception:  # noqa: BLE001
        logger.exception("demo: first-screen lookup failed for tenant %s", tenant.id)
        interview_id = None

    # HRP-276 / M7: no refresh token for demo sessions. The access
    # token's TTL is pinned to ``demo_session_ttl_seconds`` (same
    # setting that drives the tenant lifetime) so the JWT can't expire
    # before the tenant does. A 7-day refresh would let a closed-tab
    # browser hold a usable credential after the tenant + its data are
    # gone. The SPA does not call /api/auth/refresh for demo sessions.
    access = create_demo_access_token(str(user.id), str(tenant.id))

    logger.info(
        "demo: created session tenant=%s user=%s credits=%s",
        tenant.id,
        user.id,
        credits_granted,
    )

    # Best-effort domain event — the EE Slack notifier subscribes and
    # pages the team in ``SLACK_LEADS_CHANNEL`` so we have a real-time
    # signal on demo uptake. Failures must not block the response: the
    # tenant is already provisioned and the visitor is about to be
    # redirected.
    try:
        from app.core.events import publish

        await publish(
            "demo.session_started",
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "tenant_slug": tenant.slug,
                "expires_at": tenant.expires_at.isoformat()
                if tenant.expires_at
                else None,
                "credits_granted": credits_granted,
                "redirect_url": _redirect_url_for(interview_id),
                "remote_ip": remote_ip or "",
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("demo: failed to publish demo.session_started event")

    return {
        "access_token": access,
        "tenant_id": tenant.id,
        "expires_at": tenant.expires_at,
        "redirect_url": _redirect_url_for(interview_id),
        "credits_granted": credits_granted,
    }
