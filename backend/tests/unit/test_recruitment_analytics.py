"""R4c — recruitment analytics (SCR-16, SCR-28, SCR-56)."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import analytics_service, service
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCloseData,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_vacancy(db: AsyncSession, tenant, user, title: str):
    return await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=title)
    )


async def _make_candidate(db: AsyncSession, tenant, user) -> dict:
    return await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"F{uuid.uuid4().hex[:4]}",
            last_name=f"L{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )


class TestVacancyAnalytics:
    async def test_empty_vacancy_returns_zero_funnel(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Empty")
        data = await analytics_service.vacancy_analytics(
            db, tenant.id, uuid.UUID(str(vac["id"]))
        )
        assert data["total_candidates"] == 0
        assert data["win_loss"] == {
            "hired": 0,
            "rejected": 0,
            "withdrew": 0,
            "in_progress": 0,
        }

    async def test_funnel_counts_candidates(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Funnel")
        for _ in range(3):
            cand = await _make_candidate(db, tenant, user)
            await service.attach_candidate(
                db,
                tenant.id,
                user.id,
                CandidateVacancyCreate(
                    candidate_id=uuid.UUID(str(cand["id"])),
                    vacancy_id=uuid.UUID(str(vac["id"])),
                ),
            )

        data = await analytics_service.vacancy_analytics(
            db, tenant.id, uuid.UUID(str(vac["id"]))
        )
        # Funnel rows are seeded from configured stages (none here — the
        # test DB is bootstrapped via metadata.create_all without seed
        # rows) so the rendered list is allowed to be empty. The aggregate
        # candidate count is what the dashboard renders as a fallback.
        assert data["total_candidates"] == 3
        assert data["win_loss"]["in_progress"] == 3

    async def test_unknown_vacancy_returns_404(
        self, db: AsyncSession, tenant
    ):
        with pytest.raises(HTTPException) as exc:
            await analytics_service.vacancy_analytics(
                db, tenant.id, uuid.uuid4()
            )
        assert exc.value.status_code == 404

    async def test_win_loss_after_close_hired(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Close")
        cand = await _make_candidate(db, tenant, user)
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vac["id"])),
            ),
        )
        await service.close_vacancy(
            db,
            tenant.id,
            uuid.UUID(str(vac["id"])),
            VacancyCloseData(
                resolution="hired",
                hired_candidate_id=uuid.UUID(str(cand["id"])),
            ),
        )

        data = await analytics_service.vacancy_analytics(
            db, tenant.id, uuid.UUID(str(vac["id"]))
        )
        assert data["win_loss"]["hired"] == 1


class TestRecruitmentSummary:
    async def test_empty_tenant_returns_empty(
        self, db: AsyncSession, tenant
    ):
        data = await analytics_service.recruitment_summary(db, tenant.id)
        assert data == {
            "top_velocity": [],
            "top_drop_off": [],
            "ai_variance_by_recruiter": [],
        }

    async def test_summary_returns_shape(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Summary")
        cand = await _make_candidate(db, tenant, user)
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vac["id"])),
            ),
        )

        data = await analytics_service.recruitment_summary(db, tenant.id)
        assert isinstance(data["top_velocity"], list)
        assert isinstance(data["top_drop_off"], list)
        assert isinstance(data["ai_variance_by_recruiter"], list)


class TestComparisonRadar:
    async def test_radar_returns_per_candidate_scores(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Radar")
        cand = await _make_candidate(db, tenant, user)
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vac["id"])),
            ),
        )

        data = await analytics_service.comparison_radar(
            db, tenant.id, uuid.UUID(str(vac["id"]))
        )
        assert data["vacancy_id"] == uuid.UUID(str(vac["id"]))
        assert isinstance(data["candidates"], list)
        assert isinstance(data["competences"], list)


class TestCrossTenantAnalytics:
    async def test_other_tenant_vacancy_not_visible(
        self, db: AsyncSession, tenant, user
    ):
        vac = await _make_vacancy(db, tenant, user, "Isolated")
        other_tenant = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await analytics_service.vacancy_analytics(
                db, other_tenant, uuid.UUID(str(vac["id"]))
            )
        assert exc.value.status_code == 404
