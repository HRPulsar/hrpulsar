"""AES-GCM helpers for at-rest encryption of tenant secrets.

Used by recruitment settings (LLM/STT BYOK API keys). The key comes from
``settings.encryption_key`` — a urlsafe-base64 string that MUST decode to
at least 32 bytes. On SaaS the key is mandatory; missing or short keys
fail closed at the first call. On onprem we fall back to a key derived
from ``jwt_secret`` (sha256, always 32 bytes) so dev/self-hosted boxes
work without an extra env var.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

log = logging.getLogger(__name__)

_NONCE_BYTES = 12
_MIN_KEY_BYTES = 32

_fallback_warned = False


def _resolve_key() -> bytes:
    raw = (settings.encryption_key or "").strip()

    if raw:
        try:
            data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, binascii.Error):
            data = raw.encode()
        if len(data) < _MIN_KEY_BYTES:
            raise RuntimeError(
                "ENCRYPTION_KEY must decode to at least 32 bytes "
                f"(got {len(data)})"
            )
        return data[:_MIN_KEY_BYTES]

    # No explicit key configured.
    if settings.deployment_mode == "saas":
        raise RuntimeError(
            "ENCRYPTION_KEY must be configured in SaaS deployment"
        )

    # Dev / onprem fallback — derive a stable 32-byte key from jwt_secret.
    # Warn exactly once per process so the operator notices the implicit key.
    global _fallback_warned
    if not _fallback_warned:
        log.warning(
            "ENCRYPTION_KEY not set; deriving key from jwt_secret — DO NOT "
            "use in production"
        )
        _fallback_warned = True
    return hashlib.sha256(
        (settings.jwt_secret + "::recruitment-encryption").encode()
    ).digest()


def encrypt_secret(plaintext: str) -> str:
    """Return a urlsafe-base64 string ``<nonce>||<ciphertext+tag>``."""
    if plaintext == "":
        return ""
    aes = AESGCM(_resolve_key())
    nonce = os.urandom(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    """Decrypt a urlsafe-base64 token produced by :func:`encrypt_secret`.

    Returns ``None`` if the token is empty/missing. Raises ``ValueError`` on
    a malformed token (callers should treat that as a configuration bug).
    """
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid encrypted token") from exc
    if len(raw) < _NONCE_BYTES + 16:
        raise ValueError("encrypted token too short")
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        return AESGCM(_resolve_key()).decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:  # InvalidTag etc.
        raise ValueError("decryption failed") from exc


def mask_secret(plaintext: str | None, last: int = 4) -> str | None:
    """Return a masked preview suitable for API responses (e.g. ``••••abcd``)."""
    if not plaintext:
        return None
    if len(plaintext) <= last:
        return "•" * len(plaintext)
    # Cap the reveal at one-third of the length so short secrets don't
    # leak most of their characters (a 5-char secret revealing 4 leaves a
    # single bullet — useless mask).
    revealed = min(last, max(1, len(plaintext) // 3))
    return "•" * 4 + plaintext[-revealed:]
