"""HRP-920 — the public process check ("AI or Human?") is a SaaS opt-in.

Off by default, an on-prem install never opens CORS for a check host or
scopes a cookie to a parent domain. Switched on with a host, the origin
joins CORS_ORIGINS (what ``app.main`` feeds the CORS middleware) and the
cookie domain is the parent the check host shares with the app.

Settings are built directly with overrides, like the demo-validator tests,
so nothing leaks between cases through env vars.
"""

from __future__ import annotations

import pytest
from app.config import Settings, settings
from fastapi.middleware.cors import CORSMiddleware

APP_ORIGINS = "https://hrpulsar.com,https://app.hrpulsar.com"


def _settings(**overrides):
    base = {"cors_origins": APP_ORIGINS, "frontend_url": ""}
    base.update(overrides)
    return Settings(**base)


def test_defaults_off_and_cors_untouched():
    s = _settings()
    assert s.public_check_enabled is False
    assert s.public_check_host == ""
    assert s.cors_origins == APP_ORIGINS
    assert s.public_check_origin == ""
    assert s.public_check_cookie_domain == ""


def test_host_without_the_flag_changes_nothing():
    s = _settings(public_check_host="check.hrpulsar.com")
    assert s.cors_origins == APP_ORIGINS
    assert s.public_check_origin == ""
    assert s.public_check_cookie_domain == ""


def test_enabled_appends_the_host_to_cors_once():
    s = _settings(public_check_enabled=True, public_check_host="check.hrpulsar.com")
    assert s.public_check_origin == "https://check.hrpulsar.com"
    assert s.cors_origins == f"{APP_ORIGINS},https://check.hrpulsar.com"
    # Already listed by the operator → not duplicated.
    s = _settings(
        public_check_enabled=True,
        public_check_host="check.hrpulsar.com",
        cors_origins=f"{APP_ORIGINS},https://check.hrpulsar.com",
    )
    assert s.cors_origins == f"{APP_ORIGINS},https://check.hrpulsar.com"


def test_explicit_scheme_is_kept_for_dev_hosts():
    s = _settings(
        public_check_enabled=True,
        public_check_host="http://localhost:3240",
        cors_origins="http://localhost:3100",
    )
    assert s.cors_origins == "http://localhost:3100,http://localhost:3240"
    assert s.public_check_cookie_domain == ""


def test_enabled_without_a_host_is_refused():
    with pytest.raises(ValueError, match="PUBLIC_CHECK_HOST"):
        _settings(public_check_enabled=True, public_check_host="")


def test_cookie_domain_is_the_parent_shared_with_the_app():
    s = _settings(public_check_enabled=True, public_check_host="check.hrpulsar.com")
    assert s.public_check_cookie_domain == "hrpulsar.com"
    # FRONTEND_URL alone is enough to establish the shared parent.
    s = _settings(
        public_check_enabled=True,
        public_check_host="check.hrpulsar.com",
        cors_origins="",
        frontend_url="https://app.hrpulsar.com",
    )
    assert s.public_check_cookie_domain == "hrpulsar.com"


def test_cookie_domain_stays_host_scoped_on_a_foreign_domain():
    s = _settings(public_check_enabled=True, public_check_host="check.example.org")
    assert s.public_check_cookie_domain == ""


def test_app_cors_allowlist_is_built_from_cors_origins():
    """The contract the validator relies on: main.py reads ``cors_origins``."""
    from app.main import app

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == [
        o.strip() for o in settings.cors_origins.split(",") if o.strip()
    ]
