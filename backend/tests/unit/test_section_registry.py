"""HRP-820: every API route belongs to a section or to the explicit
allowlist - a new router cannot slip past the matrix."""

from app.core import sections
from app.main import app
from fastapi.routing import APIRoute


def _api_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")]


def test_every_api_route_is_placed():
    lost = [
        f"{sorted(r.methods)} {r.path}"
        for r in _api_routes()
        if r.path not in sections.PERSONAL_PATHS
        and sections.section_for_path(r.path) is None
        and not sections.is_allowlisted(r.path)
    ]
    assert not lost, f"routes outside every section and the allowlist: {lost}"


def test_prefixes_are_claimed_once():
    seen: dict[str, str] = {}
    for section in sections.SECTIONS:
        for prefix in section.prefixes:
            assert prefix not in seen, f"{prefix}: {seen[prefix]} and {section.code}"
            seen[prefix] = section.code
    for prefix in sections.ALLOWLIST_PREFIXES:
        assert sections.section_for_path("/api" + prefix) is None, prefix


def test_longest_prefix_wins_and_siblings_do_not_match():
    assert sections.section_for_path("/api/analytics/pdp/x/progress").code == "development"
    assert sections.section_for_path("/api/analytics/division-matrix").code == "analytics"
    assert sections.section_for_path("/api/assessments-grouped").code == "assessments"
    assert sections.section_for_path("/api/employees").code == "employees"
    assert sections.section_for_path("/api/employees-x") is None
    assert sections.section_for_path("/api/auth/me") is None


def test_personal_paths_are_real_routes_inside_sections():
    paths = {r.path for r in _api_routes()}
    for path in sections.PERSONAL_PATHS:
        assert path in paths, path
        assert sections.section_for_path(path) is not None, path


def test_shared_reads_are_real_reads_inside_sections():
    # HRP-827: only the GET on a shared path leaves the gate - a write
    # sharing the path must stay gated.
    gets = {r.path for r in _api_routes() if r.methods <= {"GET", "HEAD"}}
    for path in sections.SHARED_READS:
        assert path in gets, path
        assert sections.section_for_path(path) is not None, path
    gated = [
        r
        for r in _api_routes()
        if r.path in sections.SHARED_READS and not r.methods <= {"GET", "HEAD"}
    ]
    assert gated and all(sections.gated_section(r) is not None for r in gated)
    for r in _api_routes():
        if r.path in sections.SHARED_READS and r.methods <= {"GET", "HEAD"}:
            assert sections.gated_section(r) is None, r.path


def test_every_section_covers_every_role():
    for section in sections.SECTIONS:
        assert set(section.defaults) == set(sections.ROLE_CODES), section.code
        assert not section.admin_locked or section.never_hidden, section.code
