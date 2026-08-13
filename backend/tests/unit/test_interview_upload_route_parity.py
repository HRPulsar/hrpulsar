"""The upload URLs the browser calls must be URLs the app actually serves.

HRP-547 hangs a credit hold off the upload lifecycle: init takes it,
complete and abort give it back. A renamed or re-prefixed route would not
fail either side's own tests — the client would just get a 404 on abort
and the tenant's credits would stay held until the TTL swept them. So the
literals in the upload client are checked against the mounted routes.

(The prefix is the specific hazard: these routers are included without one
and pick it up from ``app.main``.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.main import app

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend"

_CLIENTS = (
    _FRONTEND / "src" / "lib" / "interview-upload.ts",
    _FRONTEND / "src" / "components" / "recruitment" / "interview-upload-zone.tsx",
)

# `/recruitment/interviews/${interviewId}/upload/init` and friends, in
# api.* calls and in raw fetch() template literals.
_URL_RE = re.compile(r"/recruitment/interviews/\$\{[^}]+\}/upload[^`\"'?]*")


def _mounted_paths() -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _collapse_params(path: str) -> str:
    """`${interviewId}` and `{interview_id}` both become `{}`."""
    return re.sub(r"\$?\{[^}]*\}", "{}", path).rstrip("/")


def _referenced_urls() -> set[str]:
    """Client literals, in the shape the router declares them."""
    found: set[str] = set()
    for path in _CLIENTS:
        if not path.exists():
            continue
        for raw in _URL_RE.findall(path.read_text(encoding="utf-8")):
            # The client is API_BASE-relative; the app mounts under /api.
            found.add("/api" + _collapse_params(raw))
    return found


@pytest.mark.skipif(not _FRONTEND.exists(), reason="frontend tree not present")
class TestInterviewUploadRouteParity:
    def test_the_client_calls_urls_that_exist(self):
        mounted = {_collapse_params(p) for p in _mounted_paths() if "/upload" in p}
        referenced = _referenced_urls()
        assert referenced, "no upload URLs found — did the client move?"

        missing = sorted(referenced - mounted)
        assert (
            missing == []
        ), "The upload client calls URLs the backend does not serve:\n" + "\n".join(
            f"  - {m}" for m in missing
        )

    def test_the_lifecycle_routes_are_all_covered(self):
        """init / complete / abort each have to be reachable, or a hold leaks."""
        referenced = _referenced_urls()
        for leaf in ("init", "complete", "abort"):
            assert any(
                url.endswith(f"/upload/{leaf}") for url in referenced
            ), f"the client no longer calls /upload/{leaf}"
            assert any(
                path.endswith(f"/upload/{leaf}") for path in _mounted_paths()
            ), f"the backend no longer serves /upload/{leaf}"
