"""REST API endpoints for recruitment module — aggregator.

The actual endpoints live in the ``routers/`` subpackage, split by
resource (project-review #19): vacancies, candidates, assessments,
interviews, consents, reports, onboarding, e2e_seed. This module keeps
the single ``router`` mounted in ``app/main.py`` plus the historical
public names other code and tests rely on.

The aggregator router carries no tags of its own — each sub-router
declares ``tags=["recruitment"]`` itself, so including them here does
not duplicate the tag on every operation.
"""

from __future__ import annotations

from fastapi import APIRouter

# Kept as module attributes: tests monkeypatch service functions through
# this module (e.g. ``recruitment_router.service``) — see
# tests/unit/ee/test_demo_analysis_cache.py.
from app.modules.recruitment import service  # noqa: F401
from app.modules.recruitment.routers import (
    assessments,
    candidates,
    consents,
    e2e_seed,
    interviews,
    onboarding,
    reports,
    vacancies,
)
from app.modules.recruitment.routers.common import (  # noqa: F401
    recruitment_public_limiter,
)
from app.modules.recruitment.routers.interviews import enqueue_analyze  # noqa: F401

router = APIRouter()

for _sub in (
    vacancies,
    candidates,
    assessments,
    interviews,
    consents,
    reports,
    onboarding,
    e2e_seed,
):
    router.include_router(_sub.router)
