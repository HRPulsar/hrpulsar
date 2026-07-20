"""Core no-op RBAC seam, rebound by the enterprise edition.

Community builds have no platform-level roles, so every function below is a
no-op default. In SaaS, ``ee.rbac.register_rbac()`` (called from
``ee.register_enterprise``) monkey-patches these module attributes to the
real implementations — the sanctioned "core no-op seam, rebound through
``ee``" mechanism of the open-core architecture (the other instance of
this pattern is ``app/core/billing_hooks.py``).

Callers MUST call through the module::

    from app.core import rbac_hooks
    rbac_hooks.login_response_extras(role_codes)

Importing the names directly would capture the no-op before rebinding.
"""

from collections.abc import Sequence
from typing import Any


def user_read_extras(role_codes: Sequence[str]) -> dict[str, Any]:
    """Extra fields merged into the auth user payload (``/auth/me``, login).

    Enterprise adds the ``is_platform_admin`` flag here; community keeps the
    ``UserRead`` schema defaults.
    """
    return {}


def login_response_extras(role_codes: Sequence[str]) -> dict[str, Any]:
    """Extra fields merged into a successful login / select-tenant response.

    Enterprise adds the post-login ``redirect_to`` for platform-level roles.
    """
    return {}


def extra_invite_tiers() -> dict[str, frozenset[str]]:
    """Additional inviter tiers merged over the core invitation hierarchy.

    Maps inviter role code -> role codes that inviter may grant.
    """
    return {}


def admin_equivalent_codes() -> frozenset[str]:
    """Role codes treated as tenant-admin-equivalent in auth flows."""
    return frozenset({"admin"})
