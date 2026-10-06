"""HRP-920 — the public process check ("AI or Human?") is a SaaS opt-in.

Off by default, an on-prem install never opens CORS for a check host or
scopes a cookie to a parent domain. Switched on with a host, the origin
joins CORS_ORIGINS (what ``app.main`` feeds the CORS middleware) and the
cookie domain is the parent the check host shares with the app.

Settings are built directly with overrides, like the demo-validator tests,
and away from the environment: no ``.env`` file, no ``PUBLIC_CHECK_*``
variables - a dev checkout that runs the check must not flip the defaults.
"""

from __future__ import annotations

import pytest
from app.config import Settings, settings
from fastapi.middleware.cors import CORSMiddleware

APP_ORIGINS = "https://hrpulsar.com,https://app.hrpulsar.com"


@pytest.fixture(autouse=True)
def _no_check_env(monkeypatch):
    for name in (
        "PUBLIC_CHECK_ENABLED",
        "PUBLIC_CHECK_HOST",
        "PUBLIC_CHECK_RATE_LIMIT",
        "PUBLIC_CHECK_TURNSTILE_SECRET",
        "PUBLIC_CHECK_DAILY_LIMIT",
        "PUBLIC_CHECK_PAUSED",
        "PUBLIC_CHECK_VOICE_RATE_LIMIT",
        "PUBLIC_CHECK_VOICE_DAILY_MINUTES",
    ):
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides):
    base = {"cors_origins": APP_ORIGINS, "frontend_url": ""}
    base.update(overrides)
    return Settings(_env_file=None, **base)


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


# --- HRP-923: the guards of the check ----------------------------------------

ON = {"public_check_enabled": True, "public_check_host": "check.hrpulsar.com"}
# The other deployed-tier validators, satisfied.
DEPLOYED = {
    "signup_turnstile_secret": "signup-secret",
    "jwt_secret": "test-jwt-secret-not-the-default-placeholder",
}


def test_guard_defaults():
    s = _settings()
    assert s.public_check_rate_limit == "5/hour;20/day"
    assert s.public_check_turnstile_secret == ""
    assert s.public_check_daily_limit == 500
    assert s.public_check_paused is False
    # Dictation (HRP-947): its own per-IP bucket and daily minutes.
    assert s.public_check_voice_rate_limit == "10/hour;30/day"
    assert s.public_check_voice_daily_minutes == 120


@pytest.mark.parametrize("env", ["production", "staging"])
def test_a_deployed_check_needs_its_captcha_secret(env):
    with pytest.raises(ValueError, match="PUBLIC_CHECK_TURNSTILE_SECRET"):
        _settings(**ON, **DEPLOYED, sentry_environment=env)
    s = _settings(
        **ON, **DEPLOYED, sentry_environment=env, public_check_turnstile_secret="x"
    )
    assert s.public_check_turnstile_secret == "x"


@pytest.mark.parametrize("env", ["production", "staging"])
@pytest.mark.parametrize(
    "name", ["public_check_daily_limit", "public_check_voice_daily_minutes"]
)
def test_a_deployed_check_needs_its_daily_cost_caps(env, name):
    deployed = {**ON, **DEPLOYED, "public_check_turnstile_secret": "x"}
    with pytest.raises(ValueError, match=name.upper()):
        _settings(**deployed, sentry_environment=env, **{name: 0})
    _settings(**deployed, sentry_environment=env)
    # Off, or in development: no cap is fine.
    _settings(**DEPLOYED, sentry_environment=env, **{name: 0})
    _settings(**ON, sentry_environment="development", **{name: 0})


def test_no_captcha_secret_is_fine_while_off_or_in_development():
    _settings(**DEPLOYED, sentry_environment="production")
    _settings(**ON, sentry_environment="development")


@pytest.mark.parametrize(
    "name", ["public_check_rate_limit", "public_check_voice_rate_limit"]
)
def test_a_rate_limit_typo_refuses_to_start(name):
    with pytest.raises(ValueError, match=name.upper()):
        _settings(**{name: "5 per hourz"})
