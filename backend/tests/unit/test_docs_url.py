"""Swagger UI is hidden on a SaaS production, the schema is not."""

import pytest
from app.config import settings
from app.main import _docs_url, app


@pytest.mark.parametrize(
    ("debug", "mode", "expected"),
    [
        (False, "saas", None),
        (True, "saas", "/api/docs"),
        (False, "onprem", "/api/docs"),
    ],
)
def test_docs_url_follows_mode_and_debug(monkeypatch, debug, mode, expected):
    monkeypatch.setattr(settings, "debug", debug)
    monkeypatch.setattr(settings, "deployment_mode", mode)
    assert _docs_url() == expected


def test_schema_route_stays():
    assert app.openapi_url == "/api/openapi.json"
