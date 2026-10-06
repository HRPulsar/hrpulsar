"""Every URL the public check pages call must be a URL the app serves.

The pages (HRP-924, HRP-925, HRP-926) and the public check router are
tested apart, each against its own mocks: a renamed route or a typo in a
literal of the client fails neither side and surfaces as a 404 - which the
result page reads as "this link has expired".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.main import app

_CLIENT = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "api"
    / "public-check.ts"
)

# A quoted or back-ticked literal that starts with /public-check, up to the
# first quote, back-tick or query string.
_URL_RE = re.compile(r"[`\"](/public-check[^`\"?]*)")


def _shape(path: str) -> str:
    """``/${encodeURIComponent(token)}`` and ``/{token}`` both become ``/{}``."""
    return re.sub(r"/\$?\{[^/]*\}+", "/{}", path).rstrip("/")


@pytest.mark.skipif(not _CLIENT.exists(), reason="frontend tree not present")
def test_the_public_check_client_calls_urls_that_exist():
    mounted = {_shape(getattr(route, "path", "")) for route in app.routes}
    referenced = {
        "/api" + _shape(raw) for raw in _URL_RE.findall(_CLIENT.read_text("utf-8"))
    }
    assert referenced == {
        "/api/public-check/checks",
        "/api/public-check/checks/{}",
        # Saved by email (HRP-926).
        "/api/public-check/checks/{}/save",
        "/api/public-check/links",
        "/api/public-check/confirm/{}",
        "/api/public-check/unsubscribe/{}",
        "/api/public-check/mine/{}",
        "/api/public-check/mine/{}/checks/{}",
        # Moved into a workspace (HRP-927).
        "/api/public-check/mine/{}/move",
        # Dictation (HRP-947).
        "/api/public-check/transcribe",
        # Funnel beacons (HRP-931).
        "/api/public-check/events",
    }, "did the client move or grow a call?"
    missing = sorted(referenced - mounted)
    assert missing == [], (
        "public-check.ts calls URLs the backend does not serve:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


@pytest.mark.skipif(not _CLIENT.exists(), reason="frontend tree not present")
def test_the_public_check_client_limits_match_the_schema():
    """The input page mirrors the backend's limits; a drift lets the page
    accept a text the API refuses with 422 (HRP-923 halved the maximum)."""
    from app.modules.public_check import schemas

    source = _CLIENT.read_text("utf-8")
    for name in ("DESCRIPTION_MIN", "DESCRIPTION_MAX", "ANSWER_MAX", "UTM_MAX"):
        found = re.search(rf"export const {name} = ([\d_]+);", source)
        assert found, f"{name} is gone from public-check.ts"
        assert int(found.group(1).replace("_", "")) == getattr(schemas, name), name


@pytest.mark.skipif(not _CLIENT.exists(), reason="frontend tree not present")
def test_the_recording_timer_matches_the_server():
    """The page stops a recording at the length the server's ceilings and
    minute counting are sized for (HRP-947)."""
    from app.modules.public_check import voice

    found = re.search(
        r"export const VOICE_MAX_SECONDS = (\d+);", _CLIENT.read_text("utf-8")
    )
    assert found, "VOICE_MAX_SECONDS is gone from public-check.ts"
    assert int(found.group(1)) == voice.MAX_SECONDS
    # The page outwaits the server's ceiling, so the server's 503 comes first.
    timeout = re.search(
        r"export const VOICE_TIMEOUT_MS = ([\d_]+);", _CLIENT.read_text("utf-8")
    )
    assert timeout, "VOICE_TIMEOUT_MS is gone from public-check.ts"
    assert int(timeout.group(1).replace("_", "")) > voice.TRANSCRIBE_TIMEOUT_S * 1000
