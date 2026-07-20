"""HRP-254 (D6) + HRP-391 — public OpenAPI and the demo surface.

``backend/app/main.py::_filtered_openapi`` strips operations tagged
``platform-admin`` / ``billing`` / etc. from the public schema. Since
HRP-391 the public-demo sandbox is enterprise-only: the ``demo`` tag is
additionally hidden whenever ``deployment_mode != "saas"``, matching the
router's 404 gate. In SaaS the demo endpoints stay visible — they are
part of the public surface there.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.main import app


@pytest.fixture
def saas_schema(monkeypatch) -> dict:
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    return app.openapi()


@pytest.fixture
def onprem_schema(monkeypatch) -> dict:
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    return app.openapi()


def test_demo_start_endpoint_present_in_saas(saas_schema):
    paths = saas_schema.get("paths", {})
    assert "/api/demo/start" in paths
    op = paths["/api/demo/start"].get("post")
    assert op is not None
    assert "demo" in op.get("tags", [])


def test_demo_endpoints_hidden_in_onprem(onprem_schema):
    """HRP-391: community builds 404 on /api/demo/* — the spec must not
    advertise routes that do not exist."""
    paths = onprem_schema.get("paths", {})
    assert "/api/demo/start" not in paths
    assert "/api/demo/save-access" not in paths


def test_demo_visibility_not_sticky_across_modes(monkeypatch):
    """The base schema is cached by FastAPI; the mode-dependent filter
    must not mutate the cache (a shallow copy guards this)."""
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    assert "/api/demo/start" not in app.openapi().get("paths", {})
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    assert "/api/demo/start" in app.openapi().get("paths", {})


def test_platform_demo_sessions_endpoint_hidden(saas_schema):
    paths = saas_schema.get("paths", {})
    assert "/api/platform/demo-sessions" not in paths


def test_platform_admin_dashboard_endpoint_hidden(saas_schema):
    """Sanity-check: the rest of platform-admin is still filtered too."""
    paths = saas_schema.get("paths", {})
    assert "/api/platform/dashboard" not in paths
    assert "/api/platform/tenants" not in paths
