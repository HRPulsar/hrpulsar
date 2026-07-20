"""Tests for GF1 (Work Experience, Previous Employment) and GF2 (Education, Courses)."""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from app.modules.employee import service
from app.modules.employee.schemas import (
    CourseCreate,
    CourseUpdate,
    EducationCreate,
    EducationUpdate,
    PreviousEmploymentCreate,
    PreviousEmploymentUpdate,
    WorkExperienceCreate,
    WorkExperienceUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def division(db: AsyncSession, tenant):
    from app.modules.company.models import Division

    div = Division(tenant_id=tenant.id, name="Engineering")
    db.add(div)
    await db.commit()
    await db.refresh(div)
    return div


# ---------------------------------------------------------------------------
# GF1: Work Experience
# ---------------------------------------------------------------------------


class TestWorkExperience:
    async def test_create(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        data = WorkExperienceCreate(
            division_id=division.id,
            position_id=position.id,
            start_date=date(2024, 3, 1),
            description="Led backend rewrite",
            role="Tech Lead",
        )
        result = await service.create_work_experience(
            db, tenant.id, employee.id, data, user
        )
        assert result["division_id"] == division.id
        assert result["position_id"] == position.id
        assert result["division_name"] == "Engineering"
        assert result["position_title"] == "Software Engineer"
        assert result["role"] == "Tech Lead"
        assert result["employee_id"] == employee.id
        # Title backfills from the Position so legacy renderers stay populated.
        assert result["title"] == "Software Engineer"

    async def test_create_minimal(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        data = WorkExperienceCreate(
            division_id=division.id,
            position_id=position.id,
            start_date=date(2024, 6, 1),
        )
        result = await service.create_work_experience(
            db, tenant.id, employee.id, data, user
        )
        assert result["role"] is None
        assert result["description"] is None
        assert result["division_id"] == division.id

    async def test_create_rejects_unknown_division(
        self, db: AsyncSession, employee, tenant, user, position
    ):
        data = WorkExperienceCreate(
            division_id=uuid.uuid4(),
            position_id=position.id,
            start_date=date(2024, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_work_experience(db, tenant.id, employee.id, data, user)
        assert exc.value.status_code == 400

    async def test_create_rejects_unknown_position(
        self, db: AsyncSession, employee, tenant, user, division
    ):
        data = WorkExperienceCreate(
            division_id=division.id,
            position_id=uuid.uuid4(),
            start_date=date(2024, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_work_experience(db, tenant.id, employee.id, data, user)
        assert exc.value.status_code == 400

    async def test_list(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        for i in range(3):
            await service.create_work_experience(
                db,
                tenant.id,
                employee.id,
                WorkExperienceCreate(
                    division_id=division.id,
                    position_id=position.id,
                    start_date=date(2024, 1, i + 1),
                ),
                user,
            )
        items = await service.list_work_experiences(db, tenant.id, employee.id)
        assert len(items) >= 3

    async def test_update(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        created = await service.create_work_experience(
            db,
            tenant.id,
            employee.id,
            WorkExperienceCreate(
                division_id=division.id,
                position_id=position.id,
                start_date=date(2024, 1, 1),
            ),
            user,
        )
        updated = await service.update_work_experience(
            db,
            tenant.id,
            created["id"],
            WorkExperienceUpdate(end_date=date(2024, 12, 31), description="wrap"),
            user,
        )
        assert str(updated["end_date"]) == "2024-12-31"
        assert updated["description"] == "wrap"

    async def test_delete(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        created = await service.create_work_experience(
            db,
            tenant.id,
            employee.id,
            WorkExperienceCreate(
                division_id=division.id,
                position_id=position.id,
                start_date=date(2024, 1, 1),
            ),
            user,
        )
        deleted = await service.delete_work_experience(
            db, tenant.id, created["id"], user
        )
        assert deleted["id"] == created["id"]

        # Verify it's gone
        items = await service.list_work_experiences(db, tenant.id, employee.id)
        assert all(item["id"] != created["id"] for item in items)

    async def test_create_invalid_employee(
        self, db: AsyncSession, tenant, user, division, position
    ):
        data = WorkExperienceCreate(
            division_id=division.id,
            position_id=position.id,
            start_date=date(2024, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_work_experience(
                db, tenant.id, uuid.uuid4(), data, user
            )
        assert exc.value.status_code == 404

    async def test_delete_not_found(self, db: AsyncSession, tenant, user):
        with pytest.raises(HTTPException) as exc:
            await service.delete_work_experience(db, tenant.id, uuid.uuid4(), user)
        assert exc.value.status_code == 404

    async def test_duration_in_read(
        self, db: AsyncSession, employee, tenant, user, division, position
    ):
        created = await service.create_work_experience(
            db,
            tenant.id,
            employee.id,
            WorkExperienceCreate(
                division_id=division.id,
                position_id=position.id,
                start_date=date(2023, 1, 1),
                end_date=date(2024, 7, 1),
            ),
            user,
        )
        assert created["duration"] == "1 year 6 months"


# ---------------------------------------------------------------------------
# GF1: Previous Employment
# ---------------------------------------------------------------------------


class TestPreviousEmployment:
    async def test_create(self, db: AsyncSession, employee, tenant, user):
        data = PreviousEmploymentCreate(
            company_name="Acme Corp",
            position="Senior Developer",
            description="Full-stack development",
            start_date=date(2020, 1, 1),
            end_date=date(2023, 12, 31),
        )
        result = await service.create_previous_employment(
            db, tenant.id, employee.id, data, user
        )
        assert result["company_name"] == "Acme Corp"
        assert result["position"] == "Senior Developer"
        assert str(result["end_date"]) == "2023-12-31"

    async def test_list(self, db: AsyncSession, employee, tenant, user):
        for company in ["Google", "Meta", "Apple"]:
            await service.create_previous_employment(
                db,
                tenant.id,
                employee.id,
                PreviousEmploymentCreate(
                    company_name=company,
                    position="Engineer",
                    start_date=date(2020, 1, 1),
                    end_date=date(2021, 12, 31),
                ),
                user,
            )
        items = await service.list_previous_employments(db, tenant.id, employee.id)
        assert len(items) >= 3

    async def test_update(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_previous_employment(
            db,
            tenant.id,
            employee.id,
            PreviousEmploymentCreate(
                company_name="Old Inc",
                position="Junior",
                start_date=date(2019, 1, 1),
                end_date=date(2020, 1, 1),
            ),
            user,
        )
        updated = await service.update_previous_employment(
            db,
            tenant.id,
            created["id"],
            PreviousEmploymentUpdate(position="Senior", end_date=date(2022, 6, 30)),
            user,
        )
        assert updated["position"] == "Senior"
        assert updated["company_name"] == "Old Inc"  # unchanged

    async def test_delete(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_previous_employment(
            db,
            tenant.id,
            employee.id,
            PreviousEmploymentCreate(
                company_name="Gone LLC",
                position="Intern",
                start_date=date(2018, 6, 1),
                end_date=date(2018, 12, 31),
            ),
            user,
        )
        await service.delete_previous_employment(db, tenant.id, created["id"], user)
        items = await service.list_previous_employments(db, tenant.id, employee.id)
        assert all(item["id"] != created["id"] for item in items)

    # HRP-219 validations -----------------------------------------------

    def test_create_requires_end_date(self):
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="Engineer",
                start_date=date(2020, 1, 1),
            )  # type: ignore[call-arg]

    def test_create_requires_company_name(self):
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="",
                position="Engineer",
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 1),
            )

    def test_create_requires_position(self):
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="",
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 1),
            )

    def test_create_rejects_future_dates(self):
        from datetime import timedelta

        future = date.today() + timedelta(days=30)
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="Engineer",
                start_date=date(2020, 1, 1),
                end_date=future,
            )
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="Engineer",
                start_date=future,
                end_date=future,
            )

    def test_create_rejects_today(self):
        today = date.today()
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="Engineer",
                start_date=today,
                end_date=today,
            )

    def test_create_rejects_start_after_end(self):
        with pytest.raises(ValueError):
            PreviousEmploymentCreate(
                company_name="Acme",
                position="Engineer",
                start_date=date(2023, 6, 1),
                end_date=date(2023, 1, 1),
            )

    def test_update_rejects_start_after_end(self):
        with pytest.raises(ValueError):
            PreviousEmploymentUpdate(
                start_date=date(2023, 6, 1),
                end_date=date(2023, 1, 1),
            )

    def test_update_rejects_future_start(self):
        from datetime import timedelta

        future = date.today() + timedelta(days=10)
        with pytest.raises(ValueError):
            PreviousEmploymentUpdate(start_date=future)


# ---------------------------------------------------------------------------
# GF2: Education
# ---------------------------------------------------------------------------


class TestEducation:
    async def test_create(self, db: AsyncSession, employee, tenant, user):
        data = EducationCreate(
            institution="MIT",
            degree="Master",
            field_of_study="Computer Science",
            start_date=date(2016, 9, 1),
            end_date=date(2018, 6, 15),
        )
        result = await service.create_education(db, tenant.id, employee.id, data, user)
        assert result["institution"] == "MIT"
        assert result["degree"] == "Master"
        assert result["field_of_study"] == "Computer Science"

    async def test_create_ongoing(self, db: AsyncSession, employee, tenant, user):
        data = EducationCreate(
            institution="Stanford",
            degree="PhD",
            field_of_study="Machine Learning",
            start_date=date(2024, 9, 1),
        )
        result = await service.create_education(db, tenant.id, employee.id, data, user)
        assert result["end_date"] is None

    async def test_list(self, db: AsyncSession, employee, tenant, user):
        await service.create_education(
            db,
            tenant.id,
            employee.id,
            EducationCreate(
                institution="Harvard",
                degree="Bachelor",
                field_of_study="Economics",
                start_date=date(2012, 9, 1),
            ),
            user,
        )
        items = await service.list_education(db, tenant.id, employee.id)
        assert len(items) >= 1

    async def test_update(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_education(
            db,
            tenant.id,
            employee.id,
            EducationCreate(
                institution="Old Uni",
                degree="Bachelor",
                field_of_study="Math",
                start_date=date(2014, 9, 1),
            ),
            user,
        )
        updated = await service.update_education(
            db,
            tenant.id,
            created["id"],
            EducationUpdate(field_of_study="Applied Mathematics"),
            user,
        )
        assert updated["field_of_study"] == "Applied Mathematics"
        assert updated["institution"] == "Old Uni"  # unchanged

    async def test_delete(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_education(
            db,
            tenant.id,
            employee.id,
            EducationCreate(
                institution="Delete U",
                degree="Other",
                field_of_study="Test",
                start_date=date(2010, 9, 1),
            ),
            user,
        )
        await service.delete_education(db, tenant.id, created["id"], user)
        items = await service.list_education(db, tenant.id, employee.id)
        assert all(item["id"] != created["id"] for item in items)

    # HRP-220 validations -----------------------------------------------

    def test_create_requires_institution(self):
        with pytest.raises(ValueError):
            EducationCreate(
                institution="",
                degree="BSc",
                field_of_study="Math",
                start_date=date(2014, 9, 1),
            )

    def test_create_requires_degree(self):
        with pytest.raises(ValueError):
            EducationCreate(
                institution="MIT",
                degree="",
                field_of_study="Math",
                start_date=date(2014, 9, 1),
            )

    def test_create_requires_field_of_study(self):
        with pytest.raises(ValueError):
            EducationCreate(
                institution="MIT",
                degree="BSc",
                field_of_study="",
                start_date=date(2014, 9, 1),
            )

    def test_create_rejects_start_after_end(self):
        with pytest.raises(ValueError):
            EducationCreate(
                institution="MIT",
                degree="BSc",
                field_of_study="Math",
                start_date=date(2018, 9, 1),
                end_date=date(2014, 6, 1),
            )

    def test_update_rejects_start_after_end(self):
        with pytest.raises(ValueError):
            EducationUpdate(
                start_date=date(2020, 6, 1),
                end_date=date(2018, 1, 1),
            )


# ---------------------------------------------------------------------------
# GF2: Courses & Certifications
# ---------------------------------------------------------------------------


class TestCourses:
    async def test_create(self, db: AsyncSession, employee, tenant, user):
        data = CourseCreate(
            title="AWS Solutions Architect",
            provider="Amazon Web Services",
            certificate_url="https://aws.amazon.com/cert/123",
            completed_date=date(2024, 3, 15),
            expiry_date=date(2027, 3, 15),
        )
        result = await service.create_course(db, tenant.id, employee.id, data, user)
        assert result["title"] == "AWS Solutions Architect"
        assert result["provider"] == "Amazon Web Services"
        assert result["certificate_url"] == "https://aws.amazon.com/cert/123"
        assert str(result["expiry_date"]) == "2027-03-15"

    async def test_create_minimal(self, db: AsyncSession, employee, tenant, user):
        data = CourseCreate(title="Internal Workshop", completed_date=date(2024, 1, 1))
        result = await service.create_course(db, tenant.id, employee.id, data, user)
        assert result["title"] == "Internal Workshop"
        assert result["provider"] is None
        assert result["expiry_date"] is None

    async def test_list(self, db: AsyncSession, employee, tenant, user):
        for title in ["Course A", "Course B"]:
            await service.create_course(
                db,
                tenant.id,
                employee.id,
                CourseCreate(title=title, completed_date=date(2024, 1, 1)),
                user,
            )
        items = await service.list_courses(db, tenant.id, employee.id)
        assert len(items) >= 2

    async def test_update(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_course(
            db,
            tenant.id,
            employee.id,
            CourseCreate(title="Old Course", completed_date=date(2024, 1, 1)),
            user,
        )
        updated = await service.update_course(
            db,
            tenant.id,
            created["id"],
            CourseUpdate(
                title="Renamed Course",
                expiry_date=date(2026, 12, 31),
            ),
            user,
        )
        assert updated["title"] == "Renamed Course"
        assert str(updated["expiry_date"]) == "2026-12-31"

    async def test_delete(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_course(
            db,
            tenant.id,
            employee.id,
            CourseCreate(title="To Remove", completed_date=date(2024, 1, 1)),
            user,
        )
        await service.delete_course(db, tenant.id, created["id"], user)
        items = await service.list_courses(db, tenant.id, employee.id)
        assert all(item["id"] != created["id"] for item in items)

    async def test_tenant_isolation(self, db: AsyncSession, employee, tenant, user):
        """Items from one tenant should not be accessible by another tenant."""
        created = await service.create_course(
            db,
            tenant.id,
            employee.id,
            CourseCreate(title="Isolated", completed_date=date(2024, 1, 1)),
            user,
        )
        other_tenant_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.delete_course(db, other_tenant_id, created["id"], user)
        assert exc.value.status_code == 404

    # HRP-220 validations -----------------------------------------------

    def test_create_requires_title(self):
        with pytest.raises(ValueError):
            CourseCreate(title="", completed_date=date(2024, 1, 1))

    def test_create_requires_completed_date(self):
        with pytest.raises(ValueError):
            CourseCreate(title="Cert")  # type: ignore[call-arg]

    def test_create_rejects_future_completed_date(self):
        from datetime import timedelta

        future = date.today() + timedelta(days=5)
        with pytest.raises(ValueError):
            CourseCreate(title="Cert", completed_date=future)

    def test_create_rejects_today_completed_date(self):
        with pytest.raises(ValueError):
            CourseCreate(title="Cert", completed_date=date.today())

    def test_create_rejects_completed_after_expiry(self):
        with pytest.raises(ValueError):
            CourseCreate(
                title="Cert",
                completed_date=date(2024, 6, 1),
                expiry_date=date(2024, 1, 1),
            )

    def test_update_rejects_future_completed_date(self):
        from datetime import timedelta

        future = date.today() + timedelta(days=5)
        with pytest.raises(ValueError):
            CourseUpdate(completed_date=future)

    def test_update_rejects_completed_after_expiry(self):
        with pytest.raises(ValueError):
            CourseUpdate(
                completed_date=date(2024, 6, 1),
                expiry_date=date(2024, 1, 1),
            )

    async def test_update_preserves_competence_link(
        self, db: AsyncSession, employee, tenant, user
    ):
        """HRP-141: editing a course with the same competence in
        Competences developed must not fail on the uq_course_competence
        UNIQUE constraint. The previous implementation deleted then re-
        inserted the same (course_id, competence_id) pair, which raises
        IntegrityError because the INSERT lands before the DELETE flushes."""
        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(title="Engineering", tenant_id=tenant.id)
        db.add(group)
        await db.flush()
        comp = Competence(title="Python", group_id=group.id, tenant_id=tenant.id)
        db.add(comp)
        await db.flush()

        created = await service.create_course(
            db,
            tenant.id,
            employee.id,
            CourseCreate(title="Cert", completed_date=date(2024, 1, 1), competence_ids=[comp.id]),
            user,
        )
        assert [c["id"] for c in created["competences"]] == [comp.id]

        updated = await service.update_course(
            db,
            tenant.id,
            created["id"],
            CourseUpdate(title="Cert (renamed)", competence_ids=[comp.id]),
            user,
        )
        assert updated["title"] == "Cert (renamed)"
        assert [c["id"] for c in updated["competences"]] == [comp.id]

    async def test_update_swaps_competence_links(
        self, db: AsyncSession, employee, tenant, user
    ):
        """Edits that change the set of competences keep the unchanged ones
        and add/drop only the diff — guards the diff-based sync against
        regressing to a destructive delete-then-insert."""
        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(title="Engineering", tenant_id=tenant.id)
        db.add(group)
        await db.flush()
        c_keep = Competence(title="Keep", group_id=group.id, tenant_id=tenant.id)
        c_drop = Competence(title="Drop", group_id=group.id, tenant_id=tenant.id)
        c_add = Competence(title="Add", group_id=group.id, tenant_id=tenant.id)
        db.add_all([c_keep, c_drop, c_add])
        await db.flush()

        created = await service.create_course(
            db,
            tenant.id,
            employee.id,
            CourseCreate(title="C", completed_date=date(2024, 1, 1), competence_ids=[c_keep.id, c_drop.id]),
            user,
        )
        assert {c["id"] for c in created["competences"]} == {c_keep.id, c_drop.id}

        updated = await service.update_course(
            db,
            tenant.id,
            created["id"],
            CourseUpdate(competence_ids=[c_keep.id, c_add.id]),
            user,
        )
        assert {c["id"] for c in updated["competences"]} == {c_keep.id, c_add.id}
