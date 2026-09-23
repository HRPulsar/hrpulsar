"""Every URL the Coverage client calls must be a URL the app serves.

The client and the routers are tested apart, each against its own mocks: a
renamed route or a typo in a literal fails neither side and surfaces as a
404 on the screen. HRP-863 added a call into another module's router (the
agent packs a step can be set to), which is exactly the kind that drifts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.main import app

_CLIENT = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "api" / "work.ts"
)

# A quoted or back-ticked literal that starts with a slash, up to the first
# quote, back-tick or query string.
_URL_RE = re.compile(r"[`\"](/(?:work|ai-workforce|primitives)[^`\"?]*)")


def _shape(path: str) -> str:
    """``/${id}`` and ``/{step_id}`` both become ``/{}``; a trailing
    ``${...`` that is not a path segment (a query builder) is dropped."""
    path = re.sub(r"/\$?\{[^}]*\}", "/{}", path)
    return re.sub(r"\$\{.*$", "", path).rstrip("/")


@pytest.mark.skipif(not _CLIENT.exists(), reason="frontend tree not present")
def test_the_coverage_client_calls_urls_that_exist():
    mounted = {_shape(getattr(route, "path", "")) for route in app.routes}
    referenced = {
        "/api" + _shape(raw) for raw in _URL_RE.findall(_CLIENT.read_text("utf-8"))
    }
    assert "/api/ai-workforce/packs" in referenced, "did the client move?"
    missing = sorted(referenced - mounted)
    assert missing == [], (
        "work.ts calls URLs the backend does not serve:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )
