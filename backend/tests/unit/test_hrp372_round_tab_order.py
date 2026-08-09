"""HRP-372: the round list is returned in hiring order, deterministically.

``list_rounds`` used to sort by ``created_at``, which only accidentally
matches the order the tab strip has to render — a Pre-interview created
after Interview 2 landed at the end of the strip.
"""

from __future__ import annotations

from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import RoundCreate
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_vacancy,
)


def _labels(rounds: list[dict]) -> list[str]:
    return [
        f"interview-{r['round_number']}" if r["type"] == "interview" else r["type"]
        for r in rounds
    ]


class TestRoundOrdering:
    async def test_pre_interview_first_even_when_created_last(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )

        rounds = await service.list_rounds(db, tenant.id, cv.id)
        assert _labels(rounds) == ["pre_interview", "interview-1", "interview-2"]

    async def test_final_last_even_when_created_before_interviews(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="final")
        )
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )

        rounds = await service.list_rounds(db, tenant.id, cv.id)
        assert _labels(rounds) == ["pre_interview", "interview-1", "final"]

    async def test_interviews_sort_numerically_not_lexicographically(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        # Explicit numbers so the 10 vs 2 comparison is exercised.
        for number in (10, 2):
            await service.create_round(
                db,
                tenant.id,
                user.id,
                cv.id,
                RoundCreate(type="interview", round_number=number),
            )

        rounds = await service.list_rounds(db, tenant.id, cv.id)
        assert [r["round_number"] for r in rounds] == [2, 10]

    async def test_order_is_stable_across_repeated_reads(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        for kind in ("final", "interview", "pre_interview", "interview"):
            await service.create_round(
                db, tenant.id, user.id, cv.id, RoundCreate(type=kind)
            )

        first = _labels(await service.list_rounds(db, tenant.id, cv.id))
        second = _labels(await service.list_rounds(db, tenant.id, cv.id))
        assert (
            first
            == second
            == [
                "pre_interview",
                "interview-1",
                "interview-2",
                "final",
            ]
        )
