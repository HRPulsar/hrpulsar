"""R4c — recruitment onboarding wizard + demo data (SCR-A1..A5)."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import onboarding_service, service
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
)
from app.modules.recruitment.schemas import VacancyCreate
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class TestOnboardingState:
    async def test_initial_state_is_welcome(
        self, db: AsyncSession, tenant
    ):
        state = await onboarding_service.get_state(db, tenant.id)
        assert state["step"] == "welcome"
        assert state["dismissed_at"] is None
        assert state["demo_seeded_at"] is None

    async def test_step_advances_with_vacancy(
        self, db: AsyncSession, tenant, user
    ):
        await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title="First"),
        )
        state = await onboarding_service.get_state(db, tenant.id)
        assert state["step"] == "vacancy_created"

    async def test_dismiss_persists_timestamp(
        self, db: AsyncSession, tenant
    ):
        state = await onboarding_service.dismiss(db, tenant.id)
        assert state["dismissed_at"] is not None


class TestDemoSeed:
    async def test_seed_creates_demo_rows(
        self, db: AsyncSession, tenant, user
    ):
        result = await onboarding_service.seed_demo(db, tenant.id, user.id)
        assert result["vacancy_id"] is not None
        assert len(result["candidate_ids"]) == 3
        assert result["interview_id"] is not None

        vacancies = (
            await db.execute(select(Vacancy).where(Vacancy.tenant_id == tenant.id))
        ).scalars().all()
        assert any(v.title == onboarding_service.DEMO_VACANCY_TITLE for v in vacancies)

        demo_candidates = (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.source == "demo",
                )
            )
        ).scalars().all()
        assert len(demo_candidates) == 3

        interview = (
            await db.execute(select(Interview).where(Interview.tenant_id == tenant.id))
        ).scalar_one_or_none()
        assert interview is not None
        assert interview.analysis_status == "completed"
        assert interview.analysis_data is not None

    async def test_seed_twice_raises_conflict(
        self, db: AsyncSession, tenant, user
    ):
        await onboarding_service.seed_demo(db, tenant.id, user.id)
        with pytest.raises(HTTPException) as exc:
            await onboarding_service.seed_demo(db, tenant.id, user.id)
        assert exc.value.status_code == 409

    async def test_cleanup_removes_only_demo(
        self, db: AsyncSession, tenant, user
    ):
        # Create a real (non-demo) vacancy that must survive the cleanup.
        real = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title="Real vacancy"),
        )

        await onboarding_service.seed_demo(db, tenant.id, user.id)
        removed = await onboarding_service.cleanup_demo(db, tenant.id)
        assert removed["candidates"] == 3
        assert removed["vacancies"] == 1

        # Demo rows gone.
        leftovers = (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.source == "demo",
                )
            )
        ).scalars().all()
        assert leftovers == []

        # Real vacancy still there.
        survivors = (
            await db.execute(
                select(Vacancy).where(Vacancy.tenant_id == tenant.id)
            )
        ).scalars().all()
        assert any(v.id == uuid.UUID(str(real["id"])) for v in survivors)

    async def test_cleanup_clears_cv_links(
        self, db: AsyncSession, tenant, user
    ):
        await onboarding_service.seed_demo(db, tenant.id, user.id)
        await onboarding_service.cleanup_demo(db, tenant.id)

        cv_rows = (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.tenant_id == tenant.id
                )
            )
        ).scalars().all()
        assert cv_rows == []

    async def test_cleanup_cross_tenant_isolation(
        self, db: AsyncSession, tenant, user
    ):
        # Seed demo in tenant, then call cleanup with a different tenant
        # id — original demo rows must remain.
        await onboarding_service.seed_demo(db, tenant.id, user.id)
        other_id = uuid.uuid4()
        # cleanup_demo expects the tenant to exist; for cross-tenant test
        # we only need to verify "no leak". A non-existent tenant raises
        # 404 via _get_tenant; create one quickly.
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{other_id.hex[:6]}")
        db.add(other)
        await db.commit()

        await onboarding_service.cleanup_demo(db, other.id)
        # Demo rows in original tenant are untouched.
        rows = (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.source == "demo",
                )
            )
        ).scalars().all()
        assert len(rows) == 3
