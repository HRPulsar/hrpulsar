import uuid

import pytest
from app.modules.dictionary import service
from app.modules.dictionary.schemas import DictionaryItemCreate, DictionaryItemUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestDictionaryCRUD:
    async def test_create_item(self, db: AsyncSession, tenant):
        data = DictionaryItemCreate(title="Junior", description="Entry level")
        item = await service.create_item(db, tenant.id, "grade", data)
        assert item["title"] == "Junior"
        assert item["type"] == "grade"
        assert item["tenant_id"] == tenant.id

    async def test_create_duplicate_title_fails(self, db: AsyncSession, tenant):
        data = DictionaryItemCreate(title="UniqueGrade")
        await service.create_item(db, tenant.id, "grade", data)

        with pytest.raises(Exception) as exc:
            await service.create_item(db, tenant.id, "grade", data)
        assert (
            "409" in str(exc.value.status_code)
            or "exists" in str(exc.value.detail).lower()
        )

    async def test_list_items(self, db: AsyncSession, tenant):
        await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="G1")
        )
        await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="G2")
        )

        items = await service.list_items(db, tenant.id, "grade")
        titles = [i["title"] for i in items]
        assert "G1" in titles
        assert "G2" in titles

    async def test_get_item(self, db: AsyncSession, tenant):
        item = await service.create_item(
            db, tenant.id, "specialization", DictionaryItemCreate(title="Backend")
        )
        result = await service.get_item(db, tenant.id, item["id"])
        assert result["title"] == "Backend"

    async def test_update_item(self, db: AsyncSession, tenant):
        item = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="Old")
        )
        updated = await service.update_item(
            db, tenant.id, item["id"], DictionaryItemUpdate(title="New")
        )
        assert updated["title"] == "New"

    async def test_delete_item(self, db: AsyncSession, tenant):
        item = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="ToDelete")
        )
        await service.delete_item(db, tenant.id, item["id"])

        with pytest.raises(HTTPException):
            await service.get_item(db, tenant.id, item["id"])

    async def test_get_item_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(Exception) as exc:
            await service.get_item(db, tenant.id, uuid.uuid4())
        assert "404" in str(exc.value.status_code)


class TestDeleteGuardHRP73:
    """HRP-57 §8.2: blocking destructive deletes of Specialization / Grade.

    Position.specialization_id has ondelete=SET NULL and GradeSpecialization
    cascades on the FK — without this guard the operator would silently
    orphan rows or wipe whole matrix profiles.
    """

    async def test_block_specialization_delete_when_position_links(
        self, db: AsyncSession, tenant
    ):
        from app.modules.position import service as position_service
        from app.modules.position.schemas import PositionCreate

        spec = await service.create_item(
            db, tenant.id, "specialization", DictionaryItemCreate(title="UsedSpec")
        )
        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(title="Consumer", specialization_id=spec["id"]),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "in_use"
        assert exc.value.detail["counts"]["positions"] == 1
        # HRP-286: message is now a generic one-liner; specifics live in counts/usage.
        assert exc.value.detail["message"] == (
            "This item has connections with other object(s). It can't be deleted"
        )

    async def test_block_specialization_delete_when_chain_exists(
        self, db: AsyncSession, tenant
    ):
        from app.modules.grade_system import service as grade_service
        from app.modules.grade_system.schemas import GradeSpecializationCreate

        spec = await service.create_item(
            db, tenant.id, "specialization", DictionaryItemCreate(title="ChainSpec")
        )
        grade = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="J")
        )
        await grade_service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"], specialization_id=spec["id"]
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["counts"]["chains"] == 1

    async def test_grade_delete_blocked_when_referenced_by_position(
        self, db: AsyncSession, tenant
    ):
        from app.modules.position import service as position_service
        from app.modules.position.schemas import PositionCreate

        grade = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="StuckGrade")
        )
        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(title="Consumer 2", grade_id=grade["id"]),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["type"] == "grade"

    async def test_unrelated_dictionary_type_still_deletable(
        self, db: AsyncSession, tenant
    ):
        item = await service.create_item(
            db, tenant.id, "role", DictionaryItemCreate(title="DispensableRole")
        )
        await service.delete_item(db, tenant.id, item["id"])
        with pytest.raises(HTTPException):
            await service.get_item(db, tenant.id, item["id"])


class TestDeleteGuardRestrictedFKs:
    """Prod fix (Sentry 7559975192): assessments / assessment_groups / pdps /
    exam_pass_marks have FKs on ``dictionary_items.id`` without ``ondelete``,
    so a bare DELETE used to bubble up as a 500 ForeignKeyViolationError.
    The service now gates the delete and surfaces a structured 409 with
    aggregate counts before the constraint can fire.
    """

    async def test_block_specialization_delete_when_assessment_links(
        self, db: AsyncSession, tenant, user, employee, assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.models import Assessment

        spec = await service.create_item(
            db, tenant.id, "specialization",
            DictionaryItemCreate(title="AssessedSpec"),
        )
        db.add(
            Assessment(
                tenant_id=tenant.id,
                title="Live assessment",
                employee_id=employee.id,
                type_id=assessment_types["self"].id,
                status_id=assessment_statuses["draft"].id,
                initiator_id=user.id,
                specialization_id=spec["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["counts"]["assessments"] == 1
        assert exc.value.detail["message"] == (
            "This item has connections with other object(s). It can't be deleted"
        )

    async def test_block_grade_delete_when_assessment_group_links(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.assessment.models import AssessmentGroup

        grade = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="GroupedGrade")
        )
        db.add(
            AssessmentGroup(
                tenant_id=tenant.id,
                title="Onboarding wave",
                initiator_id=user.id,
                grade_id=grade["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["counts"]["assessment_groups"] == 1

    async def test_block_specialization_delete_when_pdp_links(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.assessment.models import PDP

        spec = await service.create_item(
            db, tenant.id, "specialization",
            DictionaryItemCreate(title="PdpSpec"),
        )
        db.add(
            PDP(
                tenant_id=tenant.id,
                title="Growth plan",
                employee_id=employee.id,
                author_id=user.id,
                specialization_id=spec["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["counts"]["pdps"] == 1

    async def test_block_grade_delete_when_exam_pass_mark_links(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.exam.models import ExamPassMark, MassExam

        grade = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="MarkedGrade")
        )
        mass_exam = MassExam(
            tenant_id=tenant.id,
            title="Quarterly knowledge check",
            initiator_id=user.id,
        )
        db.add(mass_exam)
        await db.flush()
        db.add(
            ExamPassMark(
                mass_exam_id=mass_exam.id,
                grade_id=grade["id"],
                min_score_percent=70,
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["counts"]["exam_pass_marks"] == 1
