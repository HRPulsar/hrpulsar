"""HRP-276 (H4) + HRP-264 review — config-level startup gate for the
public demo.

The Settings ``_demo_secrets_required_in_prod`` model validator must
refuse to instantiate when production has ``DEMO_ENABLED=true`` but
either lacks a Turnstile secret OR has no LLM spend guard at all
(killswitch off AND credits/concurrency unset).

Tests instantiate ``Settings`` directly with overrides instead of
mutating env vars so a failing case in one test cannot leak into the
next file.
"""

from __future__ import annotations

import pytest
from app.config import Settings


def _settings(**overrides):
    """Construct Settings with the demo-prod fields explicit.

    pydantic-settings will still source other fields from ``.env``; the
    validator only inspects the four fields we override here.
    """
    base = {
        # HRP-391: demo_enabled=true is only legal in SaaS — pin the mode
        # so these tests keep exercising the prod-secrets validator (the
        # test env sets DEPLOYMENT_MODE=onprem globally).
        "deployment_mode": "saas",
        "demo_enabled": False,
        "demo_turnstile_secret": "",
        "demo_ai_killswitch": True,
        # signup_turnstile_secret has its own prod validator
        # (HRP-264) — set a placeholder so demo-focused tests don't
        # trip it accidentally when sentry_environment='production'.
        "signup_turnstile_secret": "test-signup-secret",
        # jwt_secret has its own prod validator (review P0-6) rejecting the
        # placeholder default; set a strong value so demo-focused tests in
        # production don't trip it.
        "jwt_secret": "test-jwt-secret-not-the-default-placeholder",
        "sentry_environment": "development",
    }
    base.update(overrides)
    return Settings(**base)


def test_demo_validator_blocks_prod_without_turnstile_secret():
    with pytest.raises(ValueError, match="DEMO_TURNSTILE_SECRET"):
        _settings(
            demo_enabled=True,
            demo_turnstile_secret="",
            sentry_environment="production",
        )


def test_demo_validator_blocks_staging_without_turnstile_secret():
    with pytest.raises(ValueError, match="DEMO_TURNSTILE_SECRET"):
        _settings(
            demo_enabled=True,
            demo_turnstile_secret="",
            sentry_environment="staging",
        )


def test_demo_validator_blocks_prod_when_all_spend_guards_off():
    """Killswitch off + zero credits + zero concurrency = uncapped LLM
    spend on the public demo path. The validator rejects this combo;
    any single spend guard (credits OR concurrency OR killswitch) is
    enough to pass."""
    with pytest.raises(ValueError, match="spend guard"):
        _settings(
            demo_enabled=True,
            demo_turnstile_secret="secret-token",
            demo_ai_killswitch=False,
            demo_initial_credits=0,
            demo_max_concurrent_sessions=0,
            sentry_environment="production",
        )


def test_demo_validator_accepts_credits_without_killswitch():
    """The product default: killswitch off, but credits + concurrency
    cap regulate spend. Should boot cleanly in prod."""
    s = _settings(
        demo_enabled=True,
        demo_turnstile_secret="secret-token",
        demo_ai_killswitch=False,
        demo_initial_credits=250,
        demo_max_concurrent_sessions=50,
        sentry_environment="production",
    )
    assert s.demo_ai_killswitch is False
    assert s.demo_initial_credits == 250


def test_demo_validator_permits_dev_without_secrets():
    """Dev environments stay permissive — local devs run ``DEMO_ENABLED=
    true`` without a real Turnstile site to iterate on the flow."""
    s = _settings(
        demo_enabled=True,
        demo_turnstile_secret="",
        demo_ai_killswitch=False,
        sentry_environment="development",
    )
    assert s.demo_enabled is True


def test_demo_validator_no_op_when_demo_disabled():
    """``DEMO_ENABLED=false`` is the default for paid-only deploys —
    the validator must not require demo-only env vars there."""
    s = _settings(
        demo_enabled=False,
        demo_turnstile_secret="",
        demo_ai_killswitch=False,
        sentry_environment="production",
    )
    assert s.demo_enabled is False


def test_demo_validator_passes_prod_with_full_config():
    s = _settings(
        demo_enabled=True,
        demo_turnstile_secret="secret-token",
        demo_ai_killswitch=True,
        sentry_environment="production",
    )
    assert s.demo_enabled is True
    assert s.demo_turnstile_secret == "secret-token"


def test_demo_enabled_rejected_outside_saas():
    """HRP-391: the public-demo sandbox is enterprise-only — enabling it
    in an onprem (community / self-hosted) deploy is a config error."""
    with pytest.raises(ValueError, match="DEPLOYMENT_MODE=saas"):
        _settings(demo_enabled=True, deployment_mode="onprem")


def test_demo_enabled_accepted_in_saas():
    s = _settings(demo_enabled=True, deployment_mode="saas")
    assert s.demo_enabled is True


def test_demo_disabled_fine_in_onprem():
    s = _settings(demo_enabled=False, deployment_mode="onprem")
    assert s.deployment_mode == "onprem"
