"""Tests for app.core.crypto — R4b.1 security hardening."""

from __future__ import annotations

import base64

import pytest
from app.config import settings
from app.core import crypto


class TestCrypto:
    def test_round_trip(self) -> None:
        token = crypto.encrypt_secret("hello world")
        assert token != "hello world"
        assert crypto.decrypt_secret(token) == "hello world"

    def test_empty_round_trip(self) -> None:
        assert crypto.encrypt_secret("") == ""
        assert crypto.decrypt_secret(None) is None
        assert crypto.decrypt_secret("") is None

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(ValueError):
            crypto.decrypt_secret("not-a-real-token!!!")

    def test_saas_requires_explicit_key(self, monkeypatch) -> None:
        """SaaS mode + missing key must fail closed."""
        monkeypatch.setattr(settings, "encryption_key", "")
        monkeypatch.setattr(settings, "deployment_mode", "saas")
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY must be configured"):
            crypto.encrypt_secret("anything")

    def test_short_key_rejected(self, monkeypatch) -> None:
        """An explicit-but-too-short key must be rejected, not silently padded."""
        too_short = base64.urlsafe_b64encode(b"\x01" * 16).decode("ascii")
        monkeypatch.setattr(settings, "encryption_key", too_short)
        with pytest.raises(RuntimeError, match="at least 32 bytes"):
            crypto.encrypt_secret("anything")

    def test_explicit_32_byte_key_accepted(self, monkeypatch) -> None:
        good = base64.urlsafe_b64encode(b"\x02" * 32).decode("ascii")
        monkeypatch.setattr(settings, "encryption_key", good)
        token = crypto.encrypt_secret("payload")
        assert crypto.decrypt_secret(token) == "payload"

    def test_onprem_fallback_warns_once(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(settings, "encryption_key", "")
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(crypto, "_fallback_warned", False)
        caplog.set_level("WARNING", logger=crypto.__name__)

        crypto.encrypt_secret("x")
        crypto.encrypt_secret("y")

        warnings = [
            r for r in caplog.records if "ENCRYPTION_KEY not set" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            "fallback warning must fire exactly once per process"
        )

    def test_mask_secret_cap(self) -> None:
        # Short secret: most of the chars must stay bulletted.
        assert crypto.mask_secret("abcde") == "•" * 4 + "e"  # cap = max(1, 5//3) = 1
        # Length 9 → cap = max(1, 9//3) = 3
        assert crypto.mask_secret("abcdefghi") == "•" * 4 + "ghi"
        # Long secret: reveal the requested ``last`` chars.
        assert crypto.mask_secret("abcdefghijklmnop") == "•" * 4 + "mnop"

    def test_mask_secret_short_no_reveal(self) -> None:
        # Length <= last: everything bulleted.
        assert crypto.mask_secret("abc") == "•••"
        assert crypto.mask_secret(None) is None
        assert crypto.mask_secret("") is None
