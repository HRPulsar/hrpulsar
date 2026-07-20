"""GF8: CPA Enhancements — criteria, participant roles, analytics, copy."""

import uuid

import pytest
from app.modules.assessment.models import (
    Assessment,
    AssessmentResult,
)
from app.modules.assessment.service import (
    add_cpa_criteria,
    add_cpa_participant,
    copy_cpa,
    create_cpa,
    get_cpa_analytics,
    get_cpa_detail,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class _Stub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestCPAEnhancements:
    async def _make_cpa(self, db, tenant, user, assessment_types):
        data = _Stub(
            title="Q1 2026 Review", type_code="360", scale_id=None, ended_at=None
        )
        return await create_cpa(db, tenant.id, user.id, data)

    # --- CPACriteria ---

    async def test_add_cpa_criteria(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        data = _Stub(criteria_type="competence", config={"min_score": 3}, weight=1.5)
        result = await add_cpa_criteria(db, tenant.id, cpa["id"], data)

        assert result["criteria_type"] == "competence"
        assert result["config"] == {"min_score": 3}
        assert result["weight"] == 1.5
        assert result["cpa_id"] == cpa["id"]

    async def test_add_cpa_criteria_position_type(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        data = _Stub(criteria_type="position", config=None, weight=1.0)
        result = await add_cpa_criteria(db, tenant.id, cpa["id"], data)
        assert result["criteria_type"] == "position"

    async def test_add_cpa_criteria_not_found(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        data = _Stub(criteria_type="point", config=None, weight=1.0)
        with pytest.raises(HTTPException):
            await add_cpa_criteria(db, tenant.id, uuid.uuid4(), data)

    # --- CPAParticipant ---

    async def test_add_cpa_participant_reviewer(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        data = _Stub(user_id=user.id, role="reviewer")
        result = await add_cpa_participant(db, tenant.id, cpa["id"], data)

        assert result["role"] == "reviewer"
        assert result["user_id"] == user.id
        assert result["cpa_id"] == cpa["id"]

    async def test_add_cpa_participant_calibrator(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        data = _Stub(user_id=user.id, role="calibrator")
        result = await add_cpa_participant(db, tenant.id, cpa["id"], data)
        assert result["role"] == "calibrator"

    async def test_add_cpa_participant_observer(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        data = _Stub(user_id=user.id, role="observer")
        result = await add_cpa_participant(db, tenant.id, cpa["id"], data)
        assert result["role"] == "observer"

    # --- CPA Detail ---

    async def test_get_cpa_detail(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        await add_cpa_criteria(
            db,
            tenant.id,
            cpa["id"],
            _Stub(criteria_type="point", config={"max": 10}, weight=2.0),
        )
        await add_cpa_participant(
            db, tenant.id, cpa["id"], _Stub(user_id=user.id, role="reviewer")
        )

        detail = await get_cpa_detail(db, tenant.id, cpa["id"])

        assert detail["title"] == "Q1 2026 Review"
        assert len(detail["criteria"]) == 1
        assert len(detail["participants"]) == 1
        assert detail["assessment_count"] == 0

    async def test_get_cpa_detail_not_found(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        with pytest.raises(HTTPException):
            await get_cpa_detail(db, tenant.id, uuid.uuid4())

    # --- CPA Analytics ---

    async def test_cpa_analytics_empty(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        analytics = await get_cpa_analytics(db, tenant.id, cpa["id"])

        assert analytics["cpa_id"] == cpa["id"]
        assert analytics["total_assessments"] == 0
        assert analytics["completed_assessments"] == 0
        assert analytics["ranking"] == []

    async def test_cpa_analytics_with_results(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)

        atype = assessment_types["360"]
        done_status = assessment_statuses["done"]

        a = Assessment(
            tenant_id=tenant.id,
            employee_id=employee.id,
            type_id=atype.id,
            status_id=done_status.id,
            initiator_id=user.id,
            cpa_id=cpa["id"],
        )
        db.add(a)
        await db.flush()

        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(title="Test Group", tenant_id=tenant.id)
        db.add(group)
        await db.flush()
        comp = Competence(title="Test Comp", group_id=group.id, tenant_id=tenant.id)
        db.add(comp)
        await db.flush()

        db.add(
            AssessmentResult(assessment_id=a.id, competence_id=comp.id, avg_score=4.5)
        )
        await db.commit()

        analytics = await get_cpa_analytics(db, tenant.id, cpa["id"])

        assert analytics["total_assessments"] == 1
        assert analytics["completed_assessments"] == 1
        assert len(analytics["ranking"]) == 1
        assert analytics["ranking"][0]["avg_score"] == 4.5
        assert analytics["ranking"][0]["rank"] == 1

    # --- CPA Copy ---

    async def test_copy_cpa(self, db: AsyncSession, tenant, user, assessment_types):
        cpa = await self._make_cpa(db, tenant, user, assessment_types)
        await add_cpa_criteria(
            db,
            tenant.id,
            cpa["id"],
            _Stub(criteria_type="competence", config={"threshold": 3}, weight=1.0),
        )
        await add_cpa_participant(
            db, tenant.id, cpa["id"], _Stub(user_id=user.id, role="reviewer")
        )

        new_cpa = await copy_cpa(db, tenant.id, user.id, cpa["id"], "Q2 2026 Review")

        assert new_cpa["title"] == "Q2 2026 Review"
        assert new_cpa["id"] != cpa["id"]
        assert new_cpa["status"] == "draft"

        # Verify criteria and participants were copied
        detail = await get_cpa_detail(db, tenant.id, new_cpa["id"])
        assert len(detail["criteria"]) == 1
        assert detail["criteria"][0]["criteria_type"] == "competence"
        assert len(detail["participants"]) == 1
        assert detail["participants"][0]["role"] == "reviewer"

    async def test_copy_cpa_not_found(
        self, db: AsyncSession, tenant, user, assessment_types
    ):
        with pytest.raises(HTTPException):
            await copy_cpa(db, tenant.id, user.id, uuid.uuid4(), "New CPA")
