"""HRP-688: draft → sent must refuse an assessment whose evaluation
criteria resolve to zero indicators.

Without the guard the questionnaire opened with no questions at all —
just a live "Submit answers" button — and a participant could "complete"
an assessment having evaluated nothing.

The guard counts the indicators the questionnaire would actually show
(the HRP-43 cascade), so it fires regardless of the criteria type: an
empty position matrix, a competence with no indicators authored, and a
cascade that filters every indicator out all look the same to it.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import AssessmentCompetence
from app.modules.assessment.schemas import AssessmentCreate, MassAssessmentCreate
from app.modules.competence.models import Indicator, SkillLevel
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import seed_one_indicator, seed_send_prereqs


async def _make_assessment(db, tenant, user, employee) -> dict:
    return await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title=f"hrp688-{uuid.uuid4().hex[:6]}",
            employee_id=employee.id,
            type_code="self",
        ),
    )


async def _drop_competences(db: AsyncSession, assessment_id: uuid.UUID) -> None:
    """Criteria + scale are set, but the matrix resolved to nothing."""
    await db.execute(
        delete(AssessmentCompetence).where(
            AssessmentCompetence.assessment_id == assessment_id
        )
    )
    await db.commit()


async def _deactivate_indicators(db: AsyncSession, assessment_id: uuid.UUID) -> None:
    """Competences stay attached, but carry no *active* indicator."""
    rows = (
        (
            await db.execute(
                select(AssessmentCompetence).where(
                    AssessmentCompetence.assessment_id == assessment_id
                )
            )
        )
        .scalars()
        .all()
    )
    inds = (
        (
            await db.execute(
                select(Indicator).where(
                    Indicator.competence_id.in_([r.competence_id for r in rows])
                )
            )
        )
        .scalars()
        .all()
    )
    for ind in inds:
        ind.is_active = False
    await db.commit()


class TestChangeStatusRequiresIndicators:
    async def test_blocks_when_criteria_resolve_to_no_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        await _drop_competences(db, created["id"])

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 422

        a = await db.get(service.Assessment, created["id"])
        await db.refresh(a, ["status"])
        assert a.status.code == "draft"

    async def test_blocks_when_competences_have_no_active_indicator(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        await _deactivate_indicators(db, created["id"])

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 422

    async def test_blocks_when_cascade_filters_every_indicator_out(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """The competence is attached and has an active indicator, but the
        target skill level sits below it — the questionnaire would show
        nothing. Guard must key on the count, not on "a competence exists"."""
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        ind_id = await seed_one_indicator(db, tenant.id, created["id"])
        await _deactivate_indicators(db, created["id"])

        ind = await db.get(Indicator, ind_id)
        ind.is_active = True
        ind_level = await db.get(SkillLevel, ind.skill_level_id)
        ind_level.sort_index = 5
        low = SkillLevel(
            tenant_id=tenant.id, title=f"low-{uuid.uuid4().hex[:6]}", sort_index=1
        )
        db.add(low)
        await db.flush()
        link = (
            await db.execute(
                select(AssessmentCompetence).where(
                    AssessmentCompetence.assessment_id == created["id"],
                    AssessmentCompetence.competence_id == ind.competence_id,
                )
            )
        ).scalar_one()
        link.skill_level_id = low.id
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 422

    async def test_allows_send_with_at_least_one_indicator(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])

        result = await service.change_status(db, tenant.id, created["id"], "sent")
        assert result["status_code"] == "sent"


class TestBulkChangeStatusRequiresIndicators:
    async def test_bulk_skips_empty_child_with_reason(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Mass launch: the healthy child goes out, the empty one stays
        draft and reports its own skip reason."""
        from tests.unit.test_assessment_hrp83_deadline import _make_extra_employee

        emp2 = await _make_extra_employee(db, tenant, "688")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-688 bulk",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )
        a1_id = group["assessments"][0]["id"]
        a2_id = group["assessments"][1]["id"]
        await seed_send_prereqs(db, tenant.id, a1_id)
        await seed_send_prereqs(db, tenant.id, a2_id)
        await _drop_competences(db, a2_id)

        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")
        assert result["changed"] == 1
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["no_indicators"] == 1

        a2 = await db.get(service.Assessment, a2_id)
        await db.refresh(a2, ["status"])
        assert a2.status.code == "draft"
