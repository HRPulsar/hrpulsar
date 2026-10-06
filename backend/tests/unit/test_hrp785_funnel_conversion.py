"""HRP-785: conversion in the Funnel block of the vacancy Analytics tab.

reached(s) counts candidates whose furthest progress stage (current stage
or any history end) is at or past ``s``; conversion(s) = reached(s) /
reached(previous progress stage), whole percent. Overall = candidates on a
terminal-positive stage / all candidates.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.recruitment import analytics_service, service, vacancy_service
from app.modules.recruitment.analytics_service import funnel_conversion
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    VacancyAnalytics,
    VacancyCreate,
)
from app.modules.recruitment.vacancy_service import DEFAULT_RECRUITMENT_STAGES
from sqlalchemy.ext.asyncio import AsyncSession

STAGES = [
    SimpleNamespace(id=uuid.uuid4(), code=code, sort_order=so, stage_type=kind)
    for code, _name, so, kind, _color in DEFAULT_RECRUITMENT_STAGES
]
ID = {s.code: s.id for s in STAGES}


def _cv(*path: str):
    """A candidate who walked ``path`` and now stands on its last stage."""
    history = [
        {"from_stage_id": str(ID[a]), "to_stage_id": str(ID[b])}
        for a, b in zip(path, path[1:], strict=False)
    ]
    return SimpleNamespace(stage_id=ID[path[-1]], status_history=history)


def _by_code(result: dict) -> dict:
    return {s.code: result.get(s.id) for s in STAGES}


def test_rejected_after_tech_interview_counts_up_to_it() -> None:
    rows = [
        _cv("new", "screening", "tech_interview", "rejected"),
        _cv("new", "screening"),
        _cv("new", "hired"),
        _cv("new"),
    ]
    out = _by_code(funnel_conversion(STAGES, rows))
    assert out["new"] == (4, None)  # first stage: no conversion
    assert out["screening"] == (3, 75)
    assert out["tech_interview"] == (2, 67)  # 2 / 3, half up
    assert out["manager_interview"] == (1, 50)
    assert out["offer"] == (1, 100)
    assert out["hired"] == (1, 100)
    assert out["probation_completed"] == (0, 0)
    # Rejected / withdrew-type stages take no conversion.
    assert out["rejected"] is None
    assert out["withdrew"] is None


def test_nobody_reached_the_previous_stage() -> None:
    out = _by_code(funnel_conversion(STAGES, [_cv("new")]))
    assert out["screening"] == (0, 0)
    assert out["tech_interview"] == (0, None)  # 0 / 0


def test_empty_vacancy() -> None:
    out = _by_code(funnel_conversion(STAGES, []))
    assert out["new"] == (0, None)
    assert all(v is None or v == (0, None) for v in out.values())


def test_history_reaches_back_from_a_lower_current_stage() -> None:
    # Moved back from Offer to Screening: Offer still counts as reached.
    out = _by_code(funnel_conversion(STAGES, [_cv("new", "offer", "screening")]))
    assert out["offer"] == (1, 100)


async def test_analytics_payload(db: AsyncSession, tenant, user) -> None:
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    vacancy_id = uuid.UUID(str(vacancy["id"]))

    empty = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
    assert empty["overall_conversion_percent"] is None

    stages = {
        s["code"]: uuid.UUID(str(s["id"]))
        for s in await service.get_effective_vacancy_stages(db, tenant.id, vacancy_id)
    }
    for target in ("hired", "rejected", None):
        candidate = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="A", last_name="B", email=f"{uuid.uuid4().hex[:8]}@x.com"
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(candidate["id"])), vacancy_id=vacancy_id
            ),
        )
        if target:
            await service.patch_candidate_vacancy(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                CandidateVacancyPatch(stage_id=stages[target]),
            )

    data = VacancyAnalytics.model_validate(
        await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
    )
    assert data.overall_conversion_percent == 33  # 1 hired of 3
    funnel = {f.stage_name: f for f in data.funnel}
    assert funnel["Screening"].conversion_percent == 33  # only the hire passed it
    assert funnel["Rejected"].conversion_percent is None
    assert funnel["New"].reached_count == 3
