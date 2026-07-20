import warnings
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# PyJWT warns when the HMAC key is < 32 bytes. Production is already forced to
# a strong secret by the config validator (Settings._secrets_not_default_in_prod),
# so this fires only on the short dev/test placeholder — silence the per-call
# noise rather than spam every token operation.
warnings.filterwarnings("ignore", category=jwt.InsecureKeyLengthWarning)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, tenant_id: str, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": "access",
        # Monotonic per-user token epoch (review P1-12). Bumped on
        # password change/reset so tokens minted earlier stop validating.
        "ver": token_version,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_demo_access_token(user_id: str, tenant_id: str) -> str:
    """Issue a long-lived access token for a demo session.

    TTL is pinned to ``settings.demo_session_ttl_seconds`` — the same
    setting that controls how long the demo tenant lives — so the JWT
    can't expire before the tenant does. Demo sessions don't get a
    refresh token (HRP-276 / M7), so a 30-min default would log the
    visitor out long before their tenant is reclaimed.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        seconds=settings.demo_session_ttl_seconds
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str, tenant_id: str, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": "refresh",
        # See create_access_token: bumped on password change/reset to
        # revoke this long-lived (7-day) token early (review P1-12).
        "ver": token_version,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_reset_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": user_id,
        "type": "reset",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_email_verification_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {
        "sub": user_id,
        "type": "email_verify",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_signup_verify_token(signup_request_id: str) -> str:
    """Token emailed to a landing/demo signup so they can confirm their
    address before the request shows up in the Slack moderation queue.

    Subject is the ``SignupRequest.id``, not a ``User.id`` — the user
    record does not exist yet at this stage. Distinct ``type`` keeps it
    out of any other validation path that decodes JWTs.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.signup_verify_token_ttl_hours
    )
    payload = {
        "sub": signup_request_id,
        "type": "signup_verify",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_magic_login_token(user_id: str, tenant_id: str) -> str:
    """One-time login link emailed after a Slack moderator approves a
    signup request. The handler dedupes ``jti`` in Redis so a stolen or
    re-clicked link cannot be replayed.
    """
    import uuid as _uuid

    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.magic_login_token_ttl_hours
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": "magic_login",
        "jti": _uuid.uuid4().hex,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
