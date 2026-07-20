"""Cross-tenant access tests for recruitment R3a/R4a flows.

R3b leftover M-3: a caller authenticated for tenant A must never be
able to read or mutate an interview / report / consent owned by tenant
B. Existing service code already gates on ``tenant_id`` in every
``select(...)`` clause; these tests pin that contract so future
refactors cannot regress it.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.modules.company.models import Tenant
from app.modules.recruitment import service
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    InterviewCreate,
    ReportGenerateRequest,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def other_tenant(db: AsyncSession) -> Tenant:
    other = Tenant(
        name=f"Other Corp {uuid.uuid4().hex[:6]}",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)
    return other


async def _make_interview(db: AsyncSession, tenant, user) -> dict:
    vac = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"F{uuid.uuid4().hex[:4]}",
            last_name=f"L{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(cand["id"])),
            vacancy_id=uuid.UUID(str(vac["id"])),
        ),
    )
    interview = await service.create_interview(
        db,
        tenant.id,
        user.id,
        uuid.UUID(str(cv["id"])),
        InterviewCreate(notes="x"),
    )
    return {"vacancy": vac, "interview": interview}


class TestInterviewCrossTenant:
    async def test_get_interview_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        ctx = await _make_interview(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.get_interview(
                db,
                other_tenant.id,
                uuid.UUID(str(ctx["interview"]["id"])),
                role="admin",
            )
        assert exc.value.status_code == 404

    async def test_enqueue_transcribe_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        ctx = await _make_interview(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.enqueue_transcribe(
                db,
                other_tenant.id,
                uuid.UUID(str(ctx["interview"]["id"])),
            )
        assert exc.value.status_code == 404

    async def test_update_interview_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        ctx = await _make_interview(db, tenant, user)
        from app.modules.recruitment.schemas import InterviewUpdate

        with pytest.raises(HTTPException) as exc:
            await service.update_interview(
                db,
                other_tenant.id,
                uuid.UUID(str(ctx["interview"]["id"])),
                InterviewUpdate(notes="hijack"),
            )
        assert exc.value.status_code == 404


class TestReportCrossTenant:
    async def test_get_report_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        vac = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="V")
        )
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )

        with pytest.raises(HTTPException) as exc:
            await service.get_report(
                db, other_tenant.id, uuid.UUID(str(res["export_id"]))
            )
        assert exc.value.status_code == 404

    async def test_delete_report_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        vac = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="V")
        )
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )

        with pytest.raises(HTTPException) as exc:
            await service.delete_report(
                db, other_tenant.id, uuid.UUID(str(res["export_id"]))
            )
        assert exc.value.status_code == 404


class TestComparisonCrossTenant:
    async def test_compare_unknown_vacancy_in_other_tenant_returns_404(
        self, db: AsyncSession, tenant, user, other_tenant
    ) -> None:
        vac = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="V")
        )
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="A",
                last_name="B",
                email=f"{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await service.compare_candidates(
                db,
                other_tenant.id,
                uuid.UUID(str(vac["id"])),
                [uuid.UUID(str(cand["id"]))],
            )
        assert exc.value.status_code == 404
