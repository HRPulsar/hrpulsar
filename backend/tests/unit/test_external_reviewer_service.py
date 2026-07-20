"""Tests for GF4: Anonymous / Open Access Assessments (External Reviewers)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import ExternalReviewer
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_assessment(
    db, tenant, employee, assessment_statuses, assessment_types
):
    """Helper to create a test assessment."""
    from app.modules.assessment.models import Assessment

    draft_status = assessment_statuses["draft"]
    a_type = assessment_types["360"]

    a = Assessment(
        title="Test Assessment",
        employee_id=employee.id,
        tenant_id=tenant.id,
        initiator_id=employee.user_id,
        type_id=a_type.id,
        status_id=draft_status.id,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


class TestCreateExternalReviewer:
    async def test_create(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        result = await service.create_external_reviewer(
            db, tenant.id, a.id, name="John External", email="john@external.com"
        )
        assert result["name"] == "John External"
        assert result["email"] == "john@external.com"
        assert result["assessment_id"] == a.id
        assert result["token"] is not None
        assert result["completed_at"] is None
        assert result["share_url"].startswith("/review/")

    async def test_create_anonymous(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        result = await service.create_external_reviewer(
            db, tenant.id, a.id, name=None, email=None
        )
        assert result["name"] is None
        assert result["email"] is None
        assert result["token"] is not None

    async def test_creates_participant(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        result = await service.create_external_reviewer(
            db, tenant.id, a.id, name="Reviewer", email=None, role="peer"
        )

        from app.modules.assessment.models import AssessmentParticipant
        from sqlalchemy import select

        p_result = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.external_reviewer_id == result["id"]
            )
        )
        p = p_result.scalar_one()
        assert p.role == "peer"
        assert p.user_id is None

    async def test_invalid_assessment(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.create_external_reviewer(
                db, tenant.id, uuid.uuid4(), name="X", email=None
            )
        assert exc.value.status_code == 404


class TestListExternalReviewers:
    async def test_list(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        for i in range(3):
            await service.create_external_reviewer(
                db, tenant.id, a.id, name=f"Reviewer {i}", email=None
            )
        results = await service.list_external_reviewers(db, tenant.id, a.id)
        assert len(results) >= 3


class TestDeleteExternalReviewer:
    async def test_delete(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        created = await service.create_external_reviewer(
            db, tenant.id, a.id, name="To Delete", email=None
        )
        deleted = await service.delete_external_reviewer(db, tenant.id, created["id"])
        assert deleted["id"] == created["id"]

        results = await service.list_external_reviewers(db, tenant.id, a.id)
        assert all(r["id"] != created["id"] for r in results)

    async def test_delete_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_external_reviewer(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404


class TestSubmitExternalAnswers:
    async def test_submit_expired(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        created = await service.create_external_reviewer(
            db, tenant.id, a.id, name="Expired", email=None
        )
        er = await db.get(ExternalReviewer, created["id"])
        er.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.submit_external_answers(db, er.token, [])
        assert exc.value.status_code == 400

    async def test_submit_invalid_token(self, db: AsyncSession):
        with pytest.raises(HTTPException) as exc:
            await service.submit_external_answers(db, "nonexistent-token", [])
        assert exc.value.status_code == 404

    async def test_get_external_assessment_invalid_token(self, db: AsyncSession):
        with pytest.raises(HTTPException) as exc:
            await service.get_external_assessment(db, "nonexistent-token")
        assert exc.value.status_code == 404

    async def test_get_external_assessment_expired(
        self, db: AsyncSession, employee, tenant, assessment_statuses, assessment_types
    ):
        a = await _create_assessment(
            db, tenant, employee, assessment_statuses, assessment_types
        )
        created = await service.create_external_reviewer(
            db, tenant.id, a.id, name="Exp", email=None
        )
        er = await db.get(ExternalReviewer, created["id"])
        er.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.get_external_assessment(db, er.token)
        assert exc.value.status_code == 400
