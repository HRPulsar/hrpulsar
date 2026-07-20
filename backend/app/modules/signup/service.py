"""Service layer for the moderated signup flow (HRP-259 — M1).

Handles three transitions plus the Slack moderation side effects:

* ``create_signup_request``  — landing form submit, sends verify email.
* ``verify_signup_request``  — visitor clicks emailed link, flips to
  ``pending_moderation`` and emits ``signup.email_verified`` so the
  enterprise Slack handler can post the moderation card.
* ``approve_signup`` / ``reject_signup`` — invoked by the EE Slack
  Bolt listener (see ``ee.slack_signup_actions``); approve provisions
  a real Tenant + User pair and emails a one-time magic-login link.

Anti-abuse: per-IP rate limit + Cloudflare Turnstile on create, same
shape as the demo bootstrap. Both fail closed so a Redis flake or
empty bot-guard secret in prod cannot widen the funnel.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from jwt import PyJWTError as JWTError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    create_magic_login_token,
    create_signup_verify_token,
    decode_token,
    hash_password,
)
from app.modules.signup.models import SignupRequest
from app.modules.signup.schemas import SignupRequestCreate

logger = logging.getLogger(__name__)


_TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)

_turnstile_bypass_warned = False


def _warn_signup_turnstile_bypass_once() -> None:
    """One-shot warning when SIGNUP_TURNSTILE_SECRET is empty.

    Production validator below refuses to start a deployed tier
    without it; this covers dev / staging without a secret while
    still leaving a single audit line in the logs.
    """
    global _turnstile_bypass_warned
    if _turnstile_bypass_warned:
        return
    _turnstile_bypass_warned = True
    logger.warning(
        "signup turnstile: SIGNUP_TURNSTILE_SECRET is empty — bot "
        "guard is BYPASSED. Set the secret before opening the public "
        "/register form."
    )


async def _verify_turnstile(token: str | None, *, remote_ip: str | None) -> bool:
    """Cloudflare Turnstile verifier — mirror of demo.turnstile.

    A dedicated copy keeps both flows independently configurable (one
    can ship Turnstile before the other) without coupling secrets.
    """
    secret = settings.signup_turnstile_secret
    if not secret:
        _warn_signup_turnstile_bypass_once()
        return True
    if not token:
        return False
    import httpx

    payload: dict[str, str] = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(_TURNSTILE_VERIFY_URL, data=payload)
        if resp.status_code != 200:
            logger.warning(
                "signup turnstile: siteverify returned HTTP %s",
                resp.status_code,
            )
            return False
        body = resp.json()
        return bool(body.get("success"))
    except Exception:  # noqa: BLE001
        logger.exception("signup turnstile: verification failed")
        return False


async def _enforce_rate_limit(remote_ip: str | None) -> None:
    """Per-IP per-hour throttle backed by an atomic Redis pipeline.

    Same shape as ``demo.service._enforce_rate_limit``: pipeline so we
    can't crash between INCR and EXPIRE, and Redis failure fails
    closed (a transient flake is preferable to opening the funnel).
    """
    limit = settings.signup_rate_limit_per_ip_per_hour
    if remote_ip is None or limit <= 0:
        return
    client = None
    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        key = f"signup:rl:{remote_ip}"
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 3600)
            count, _ = await pipe.execute()
        if count > limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many signup attempts from this address; please try again later.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "signup rate-limit: redis unavailable, refusing request"
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Signup temporarily unavailable; please try again in a minute.",
        ) from exc
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()  # type: ignore[attr-defined]


async def _find_by_email(
    db: AsyncSession, email: str
) -> SignupRequest | None:
    """Case-insensitive lookup. Mirrors the DB unique index."""
    result = await db.execute(
        select(SignupRequest).where(func.lower(SignupRequest.email) == email.lower())
    )
    return result.scalar_one_or_none()


async def create_signup_request(
    db: AsyncSession,
    data: SignupRequestCreate,
    *,
    remote_ip: str | None,
    source: str = "landing",
    demo_tenant_id_snapshot: uuid.UUID | None = None,
) -> SignupRequest:
    """Create a fresh SignupRequest and email a verification link.

    Idempotency: a repeat submit for a still-pending row re-issues a
    verify email but does not reset the timestamps. A submit for an
    already-approved/rejected email returns 409 — the email belongs
    to someone we either let in or actively blocked, so we don't let
    the form quietly reopen the queue. ``email`` is stored as the
    visitor typed it for display; uniqueness is enforced on
    ``lower(email)`` via a Postgres unique index.
    """
    if not await _verify_turnstile(data.turnstile_token, remote_ip=remote_ip):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Bot guard challenge failed."
        )
    await _enforce_rate_limit(remote_ip)

    email_norm = data.email.lower().strip()

    existing = await _find_by_email(db, email_norm)
    if existing is not None:
        if existing.status in ("approved", "rejected"):
            # Neutral 409 — don't leak whether the address was let in
            # or rejected (avoids handing an enumeration oracle to a
            # scripted scraper).
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A signup request for this email already exists.",
            )
        # Pending row: re-send the verify email but keep the existing
        # created_at + id. ``status`` stays whatever it was — a click
        # on the old link must still flip a pending_email_verify row
        # to pending_moderation; a click on the new link is harmless.
        await _send_signup_verify_email(existing)
        return existing

    row = SignupRequest(
        email=email_norm,
        first_name=(data.first_name or "").strip() or None,
        last_name=(data.last_name or "").strip() or None,
        company_name=(data.company_name or "").strip() or None,
        role=(data.role or "").strip() or None,
        status="pending_email_verify",
        source=source,
        demo_tenant_id_snapshot=demo_tenant_id_snapshot,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await _send_signup_verify_email(row)
    return row


async def _send_signup_verify_email(row: SignupRequest) -> None:
    """Best-effort send of the verify-email link. Never raises."""
    try:
        from app.core.email import send_signup_verify_email

        token = create_signup_verify_token(str(row.id))
        send_signup_verify_email(row.email, token)
    except Exception:
        logger.exception(
            "signup: failed to send verify email for request %s", row.id
        )


async def verify_signup_request(
    db: AsyncSession, token: str
) -> tuple[SignupRequest, bool]:
    """Validate a verify token; flip pending_email_verify → pending_moderation.

    Returns ``(row, already_verified)``. ``already_verified`` is True
    for a repeat click (idempotent — the SPA shows the same waiting
    screen). Approved / rejected / expired rows raise 409 so we don't
    walk a finalized request back into the moderation queue.
    """
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Verification link is invalid or expired."
        ) from exc
    if payload.get("type") != "signup_verify":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Verification link is invalid."
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Verification link is invalid."
        )
    try:
        request_id = uuid.UUID(str(sub))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Verification link is invalid."
        ) from exc

    # SELECT ... FOR UPDATE + populate_existing is the standard remedy for
    # async cross-request TOCTOU in this codebase (see memory
    # ``feedback_sqlalchemy_race_fix``). Without it, two concurrent verify
    # clicks (Outlook SafeLinks / Gmail link-preview prefetch + the
    # visitor's own click) would both observe pending_email_verify, both
    # flip to pending_moderation, and the signup.email_verified event
    # would publish twice — double Slack moderation cards + duplicate
    # analytics conversion beacons.
    row = (
        await db.execute(
            select(SignupRequest)
            .where(SignupRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Signup request not found."
        )

    if row.status == "pending_email_verify":
        row.email_verified_at = datetime.now(timezone.utc)
        row.status = "pending_moderation"
        await db.commit()
        await db.refresh(row)
        await _publish_email_verified(row)
        return row, False

    if row.status == "pending_moderation":
        # Visitor clicked the verify link twice — already in the queue.
        # The row was locked by the first call, so we observe the
        # post-transition state without re-publishing.
        return row, True

    # approved / rejected / expired — the request is no longer pending.
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "This signup request has already been processed.",
    )


async def _publish_email_verified(row: SignupRequest) -> None:
    """Emit ``signup.email_verified`` so EE handlers can fan out.

    Slack moderation message is the canonical subscriber but the event
    is generic — analytics or any future audit hook can subscribe
    without touching this module.
    """
    try:
        from app.core.events import publish

        await publish(
            "signup.email_verified",
            {
                "signup_request_id": str(row.id),
                "email": row.email,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "company_name": row.company_name,
                "role": row.role,
                "source": row.source,
            },
        )
    except Exception:
        logger.exception(
            "signup: failed to publish signup.email_verified for %s", row.id
        )


def _slugify(name: str) -> str:
    """Mirror ``auth.service._slugify`` — kept private so the two
    modules can evolve independently."""
    import re

    slug = (name or "").lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:255] or "tenant"


async def approve_signup(
    db: AsyncSession,
    signup_request_id: uuid.UUID,
    *,
    moderator_slack_user_id: str,
) -> tuple[SignupRequest, str, dict[str, Any]]:
    """Approve a pending_moderation row, provision Tenant + User + role.

    Returns ``(row, magic_login_token, tenant_user_payload)``. The
    caller (Slack Bolt handler) is responsible for emailing the magic
    link and updating the Slack moderation card via ``chat.update``.
    Re-approval of a finalised row raises 409 — moderators see an
    ephemeral "already processed" reply instead.
    """
    from app.modules.auth.models import Role, User, user_roles
    from app.modules.company.models import Tenant

    row = await db.get(SignupRequest, signup_request_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Signup request not found."
        )
    if row.status != "pending_moderation":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Signup request is not awaiting moderation.",
        )

    # ── Tenant ----------------------------------------------------------
    # The slug uniqueness check is best-effort — two concurrent approves
    # with the same company_name would both observe base_slug as free
    # and race on the unique index. Wrap the insert in a small retry so
    # the collision triggers the suffix path instead of bubbling a 500
    # back to the moderator.
    from sqlalchemy.exc import IntegrityError

    base_slug = _slugify(row.company_name or row.email.split("@", 1)[0])
    candidate_slugs = [base_slug] + [
        f"{base_slug}-{uuid.uuid4().hex[:6]}" for _ in range(4)
    ]
    tenant: Tenant | None = None
    last_error: Exception | None = None
    for slug in candidate_slugs:
        if (
            await db.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none():
            continue
        attempt = Tenant(name=row.company_name or row.email, slug=slug)
        db.add(attempt)
        try:
            await db.flush()
            tenant = attempt
            break
        except IntegrityError as exc:
            last_error = exc
            await db.rollback()
            # After rollback the row.status change is gone too — re-load
            # the row in the same session so the loop's outer commit
            # ladders the same SignupRequest instance.
            row = await db.get(SignupRequest, signup_request_id)
            if row is None or row.status != "pending_moderation":
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Signup request is not awaiting moderation.",
                ) from exc
    if tenant is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Could not assign a unique tenant slug after several attempts.",
        ) from last_error

    # HRP-181 REDO mirror: seed the canonical 9-stage recruitment funnel,
    # but isolate failures via SAVEPOINT so a half-applied chain doesn't
    # block account creation.
    try:
        from app.modules.recruitment.vacancy_service import (
            seed_default_recruitment_stages,
        )

        async with db.begin_nested():
            await seed_default_recruitment_stages(db, tenant.id)
    except Exception:
        logger.exception(
            "signup-approve: failed to seed default recruitment stages "
            "for tenant %s",
            tenant.id,
        )

    # ── User ------------------------------------------------------------
    # Random password — the user only ever logs in via the magic-link
    # JWT. Password reset is available if they want to set one later.
    user = User(
        email=row.email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        first_name=row.first_name or "",
        last_name=row.last_name or "",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    admin_role = (
        await db.execute(
            select(Role).where(
                Role.code == "admin", Role.is_system.is_(True)
            )
        )
    ).scalar_one_or_none()
    if admin_role is not None:
        await db.execute(
            user_roles.insert().values(user_id=user.id, role_id=admin_role.id)
        )

    # ── Mark signup approved -------------------------------------------
    now = datetime.now(timezone.utc)
    row.status = "approved"
    row.moderated_at = now
    row.moderated_by_slack_user_id = moderator_slack_user_id

    await db.commit()
    await db.refresh(row)
    await db.refresh(user)
    await db.refresh(tenant)

    token = create_magic_login_token(str(user.id), str(tenant.id))

    payload = {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "user_id": str(user.id),
        "user_email": user.email,
    }
    return row, token, payload


async def reject_signup(
    db: AsyncSession,
    signup_request_id: uuid.UUID,
    *,
    moderator_slack_user_id: str,
    reason: str | None = None,
) -> SignupRequest:
    """Reject a pending_moderation row.

    No Tenant / User is created — the row stays around as an audit
    trail and the verified email is permanently barred from being
    re-submitted via the landing form (the next /signup-request POST
    for the same address returns 409).
    """
    row = await db.get(SignupRequest, signup_request_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Signup request not found."
        )
    if row.status != "pending_moderation":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Signup request is not awaiting moderation.",
        )

    reason_clean = (reason or "").strip() or None

    row.status = "rejected"
    row.moderated_at = datetime.now(timezone.utc)
    row.moderated_by_slack_user_id = moderator_slack_user_id
    row.reject_reason = reason_clean

    await db.commit()
    await db.refresh(row)

    # Best-effort notification to the visitor — never blocks reject.
    try:
        from app.core.email import send_signup_rejected_email

        send_signup_rejected_email(row.email, reason_clean)
    except Exception:
        logger.exception(
            "signup: failed to send rejection email for request %s", row.id
        )

    return row
