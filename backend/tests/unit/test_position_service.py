import uuid

import pytest
from app.modules.position import service
from app.modules.position.models import Position
from app.modules.position.schemas import (
    PositionBulkAction,
    PositionCreate,
    PositionUpdate,
)
from fastapi import HTTPException


class TestPositionCRUD:
    async def test_create_position(self, db, tenant):
        data = PositionCreate(title="Backend Developer")
        result = await service.create_position(db, tenant.id, data)
        assert result["title"] == "Backend Developer"
        assert result["source"] == "manual"
        assert result["is_active"] is True
        assert result["employee_count"] == 0

    async def test_create_duplicate_title(self, db, tenant):
        data = PositionCreate(title="QA Engineer")
        await service.create_position(db, tenant.id, data)
        with pytest.raises(HTTPException) as exc:
            await service.create_position(db, tenant.id, data)
        assert exc.value.status_code == 409

    async def test_list_positions(self, db, tenant):
        await service.create_position(db, tenant.id, PositionCreate(title="Dev A"))
        await service.create_position(db, tenant.id, PositionCreate(title="Dev B"))
        items, total = await service.list_positions(db, tenant.id)
        assert total >= 2
        titles = [p["title"] for p in items]
        assert "Dev A" in titles
        assert "Dev B" in titles

    async def test_list_positions_search(self, db, tenant):
        await service.create_position(
            db, tenant.id, PositionCreate(title="Frontend Developer")
        )
        await service.create_position(
            db, tenant.id, PositionCreate(title="Office Manager")
        )
        items, total = await service.list_positions(db, tenant.id, search="front")
        assert total == 1
        assert items[0]["title"] == "Frontend Developer"

    async def test_get_position(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="CTO")
        )
        result = await service.get_position(db, tenant.id, created["id"])
        assert result["title"] == "CTO"

    async def test_get_position_not_found(self, db, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_position(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_update_position(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Old Title")
        )
        result = await service.update_position(
            db,
            tenant.id,
            created["id"],
            PositionUpdate(title="New Title"),
        )
        assert result["title"] == "New Title"

    async def test_update_title_cascades_to_employee_snapshot(
        self, db, tenant, employee
    ):
        # HRP-332: employees carry a denormalized position_title; a rename
        # must refresh every assigned employee, otherwise the old title
        # keeps showing across the system.
        assert employee.position_title != "Renamed Position"
        await service.update_position(
            db,
            tenant.id,
            employee.position_id,
            PositionUpdate(title="Renamed Position"),
        )
        await db.refresh(employee)
        assert employee.position_title == "Renamed Position"

    async def test_update_title_leaves_other_positions_employees_alone(
        self, db, tenant, employee
    ):
        # The cascade must be scoped to the renamed position only.
        other = await service.create_position(
            db, tenant.id, PositionCreate(title="Untouched Position")
        )
        await service.update_position(
            db, tenant.id, other["id"], PositionUpdate(title="Untouched Renamed")
        )
        await db.refresh(employee)
        assert employee.position_title != "Untouched Renamed"

    async def test_update_without_title_keeps_employee_snapshot(
        self, db, tenant, employee
    ):
        original = employee.position_title
        await service.update_position(
            db,
            tenant.id,
            employee.position_id,
            PositionUpdate(headcount=7),
        )
        await db.refresh(employee)
        assert employee.position_title == original

    async def test_update_duplicate_title(self, db, tenant):
        await service.create_position(db, tenant.id, PositionCreate(title="Position A"))
        b = await service.create_position(
            db, tenant.id, PositionCreate(title="Position B")
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_position(
                db, tenant.id, b["id"], PositionUpdate(title="Position A")
            )
        assert exc.value.status_code == 409

    async def test_delete_position(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Temp")
        )
        await service.delete_position(db, tenant.id, created["id"])
        with pytest.raises(HTTPException) as exc:
            await service.get_position(db, tenant.id, created["id"])
        assert exc.value.status_code == 404

    async def test_delete_position_with_employees(self, db, tenant, employee):
        # employee fixture has position_id set
        with pytest.raises(HTTPException) as exc:
            await service.delete_position(db, tenant.id, employee.position_id)
        assert exc.value.status_code == 409

    async def test_deactivate_position(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Active Pos")
        )
        result = await service.deactivate_position(db, tenant.id, created["id"])
        assert result["is_active"] is False
        assert result["lifecycle_status"] == "frozen"


class TestPositionLifecycle:
    async def test_default_lifecycle_status_is_active(self, db, tenant):
        result = await service.create_position(
            db, tenant.id, PositionCreate(title="Lifecycle Default")
        )
        assert result["lifecycle_status"] == "active"
        assert result["is_active"] is True

    async def test_lifecycle_status_via_update(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Lifecycle Update")
        )
        result = await service.update_position(
            db,
            tenant.id,
            created["id"],
            PositionUpdate(lifecycle_status="on_hold"),
        )
        assert result["lifecycle_status"] == "on_hold"
        assert result["is_active"] is False

    async def test_setting_active_lifecycle_reactivates(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Reactivate")
        )
        await service.update_position(
            db,
            tenant.id,
            created["id"],
            PositionUpdate(lifecycle_status="frozen"),
        )
        result = await service.update_position(
            db,
            tenant.id,
            created["id"],
            PositionUpdate(lifecycle_status="active"),
        )
        assert result["lifecycle_status"] == "active"
        assert result["is_active"] is True

    async def test_is_active_false_sets_frozen(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Legacy Deactivate")
        )
        result = await service.update_position(
            db,
            tenant.id,
            created["id"],
            PositionUpdate(is_active=False),
        )
        assert result["lifecycle_status"] == "frozen"
        assert result["is_active"] is False


class TestPositionRelationships:
    async def test_create_with_specialization_and_grade(self, db, tenant):
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(
            type="specialization", title="Backend", tenant_id=tenant.id
        )
        grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        data = PositionCreate(
            title="Senior Backend Dev",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        result = await service.create_position(db, tenant.id, data)
        assert result["specialization_title"] == "Backend"
        assert result["grade_title"] == "Senior"

    async def test_create_with_division(self, db, tenant):
        from app.modules.company.models import Division

        div = Division(name="Engineering", tenant_id=tenant.id)
        db.add(div)
        await db.commit()
        await db.refresh(div)

        data = PositionCreate(title="Eng Lead", division_id=div.id)
        result = await service.create_position(db, tenant.id, data)
        assert result["division_name"] == "Engineering"

    async def test_invalid_specialization_type(self, db, tenant):
        from app.modules.dictionary.models import DictionaryItem

        grade_item = DictionaryItem(type="grade", title="Junior", tenant_id=tenant.id)
        db.add(grade_item)
        await db.commit()
        await db.refresh(grade_item)

        # Try to use a grade as specialization_id
        data = PositionCreate(title="Bad Pos", specialization_id=grade_item.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_position(db, tenant.id, data)
        assert exc.value.status_code == 400

    async def test_invalid_grade_type(self, db, tenant):
        from app.modules.dictionary.models import DictionaryItem

        spec_item = DictionaryItem(
            type="specialization", title="Frontend", tenant_id=tenant.id
        )
        db.add(spec_item)
        await db.commit()
        await db.refresh(spec_item)

        data = PositionCreate(title="Bad Pos 2", grade_id=spec_item.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_position(db, tenant.id, data)
        assert exc.value.status_code == 400


class TestPositionFilters:
    async def test_filter_by_source(self, db, tenant):
        await service.create_position(db, tenant.id, PositionCreate(title="Manual Pos"))
        draft = Position(tenant_id=tenant.id, title="Draft Pos", source="ai_draft")
        db.add(draft)
        await db.commit()

        items, total = await service.list_positions(db, tenant.id, source="ai_draft")
        assert total == 1
        assert items[0]["title"] == "Draft Pos"

    async def test_filter_by_is_active(self, db, tenant):
        pos = await service.create_position(
            db, tenant.id, PositionCreate(title="To Deactivate")
        )
        await service.deactivate_position(db, tenant.id, pos["id"])

        items, total = await service.list_positions(db, tenant.id, is_active=False)
        assert total == 1
        assert items[0]["title"] == "To Deactivate"

        active_items, active_total = await service.list_positions(
            db, tenant.id, is_active=True
        )
        titles = [p["title"] for p in active_items]
        assert "To Deactivate" not in titles

    async def test_filter_by_specialization(self, db, tenant):
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(type="specialization", title="QA", tenant_id=tenant.id)
        db.add(spec)
        await db.commit()
        await db.refresh(spec)

        await service.create_position(
            db,
            tenant.id,
            PositionCreate(title="QA Lead", specialization_id=spec.id),
        )
        await service.create_position(
            db, tenant.id, PositionCreate(title="Office Admin")
        )

        items, total = await service.list_positions(
            db, tenant.id, specialization_id=spec.id
        )
        assert total == 1
        assert items[0]["title"] == "QA Lead"

    async def test_employee_count_accuracy(self, db, tenant, employee):
        # employee fixture is linked to the position fixture
        result = await service.get_position(db, tenant.id, employee.position_id)
        assert result["employee_count"] == 1


class TestPositionFiltersHRP72:
    """HRP-57 § 7.3 (E6): lifecycle / has_vacancies / matrix_unconfigured."""

    async def test_filter_by_lifecycle_status(self, db, tenant):
        active = await service.create_position(
            db, tenant.id, PositionCreate(title="LC Active")
        )
        held = await service.create_position(
            db, tenant.id, PositionCreate(title="LC Hold")
        )
        await service.set_position_status(db, tenant.id, held["id"], "on_hold")

        active_items, active_total = await service.list_positions(
            db, tenant.id, lifecycle_status="active"
        )
        assert active_total == 1
        assert active_items[0]["id"] == active["id"]

        hold_items, hold_total = await service.list_positions(
            db, tenant.id, lifecycle_status="on_hold"
        )
        assert hold_total == 1
        assert hold_items[0]["id"] == held["id"]

    async def test_filter_by_lifecycle_status_rejects_unknown(self, db, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.list_positions(
                db, tenant.id, lifecycle_status="banana"
            )
        assert exc.value.status_code == 400

    async def test_has_vacancies_true_returns_only_open_slots(
        self, db, tenant, employee
    ):
        # `employee` fixture is on a Position with no headcount cap, so it
        # never registers as "has vacancies" — create three explicit cases.
        from datetime import date

        from app.modules.auth.models import User
        from app.modules.employee.models import Employee

        # Open: cap 3, no employees
        open_pos = await service.create_position(
            db, tenant.id, PositionCreate(title="Open", headcount=3)
        )
        # Full: cap 1, one employee
        full_pos = await service.create_position(
            db, tenant.id, PositionCreate(title="Full", headcount=1)
        )
        u = User(
            email=f"v-{uuid.uuid4().hex[:6]}@test.com",
            password_hash="x",
            first_name="V",
            last_name="A",
            tenant_id=tenant.id,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(
            Employee(
                tenant_id=tenant.id,
                user_id=u.id,
                position_id=full_pos["id"],
                hire_date=date.today(),
            )
        )
        await db.commit()

        items, total = await service.list_positions(
            db, tenant.id, has_vacancies=True
        )
        ids = [p["id"] for p in items]
        assert open_pos["id"] in ids
        assert full_pos["id"] not in ids
        assert total == len(ids)

        items_no_vacancies, _ = await service.list_positions(
            db, tenant.id, has_vacancies=False
        )
        no_vac_ids = [p["id"] for p in items_no_vacancies]
        assert full_pos["id"] in no_vac_ids
        assert open_pos["id"] not in no_vac_ids

    async def test_has_vacancies_excludes_null_headcount(self, db, tenant):
        # Position with no headcount cap is "no plan defined", so it cannot
        # register as having vacancies — has_vacancies=True excludes it,
        # has_vacancies=False includes it.
        pos = await service.create_position(
            db, tenant.id, PositionCreate(title="Uncapped"),
        )
        assert pos["headcount"] is None

        with_vac, _ = await service.list_positions(
            db, tenant.id, has_vacancies=True
        )
        assert pos["id"] not in [p["id"] for p in with_vac]

        without_vac, _ = await service.list_positions(
            db, tenant.id, has_vacancies=False
        )
        assert pos["id"] in [p["id"] for p in without_vac]

    async def test_matrix_unconfigured_filter(self, db, tenant):
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            SkillLevel,
        )
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        spec = DictionaryItem(type="specialization", title="X", tenant_id=tenant.id)
        grade = DictionaryItem(type="grade", title="J", tenant_id=tenant.id)
        skill = SkillLevel(tenant_id=tenant.id, title="A", sort_index=1)
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add_all([spec, grade, skill, group])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)
        await db.refresh(skill)
        await db.refresh(group)
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="C")
        gs = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
        )
        db.add_all([comp, gs])
        await db.commit()
        await db.refresh(comp)
        await db.refresh(gs)
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=skill.id,
            )
        )
        await db.commit()

        configured = await service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="Configured",
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        unconfigured = await service.create_position(
            db,
            tenant.id,
            PositionCreate(title="Unconfigured"),
        )

        unconf_items, _ = await service.list_positions(
            db, tenant.id, matrix_unconfigured=True
        )
        unconf_ids = [p["id"] for p in unconf_items]
        assert unconfigured["id"] in unconf_ids
        assert configured["id"] not in unconf_ids

        conf_items, _ = await service.list_positions(
            db, tenant.id, matrix_unconfigured=False
        )
        conf_ids = [p["id"] for p in conf_items]
        assert configured["id"] in conf_ids
        assert unconfigured["id"] not in conf_ids


class TestPositionBulkAction:
    async def test_approve_drafts(self, db, tenant):
        pos = Position(tenant_id=tenant.id, title="AI Pos 1", source="ai_draft")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.bulk_action_positions(
            db,
            tenant.id,
            PositionBulkAction(ids=[pos.id], action="approve"),
        )
        assert result["approved"] == 1

        updated = await service.get_position(db, tenant.id, pos.id)
        assert updated["source"] == "ai_approved"

    async def test_reject_drafts(self, db, tenant):
        pos = Position(tenant_id=tenant.id, title="AI Pos 2", source="ai_draft")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.bulk_action_positions(
            db,
            tenant.id,
            PositionBulkAction(ids=[pos.id], action="reject"),
        )
        assert result["rejected"] == 1

        with pytest.raises(HTTPException) as exc:
            await service.get_position(db, tenant.id, pos.id)
        assert exc.value.status_code == 404

    async def test_bulk_action_ignores_non_drafts(self, db, tenant):
        pos = Position(tenant_id=tenant.id, title="Manual Pos", source="manual")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        with pytest.raises(HTTPException) as exc:
            await service.bulk_action_positions(
                db,
                tenant.id,
                PositionBulkAction(ids=[pos.id], action="approve"),
            )
        assert exc.value.status_code == 404


class TestPositionDrilldown:
    async def test_list_position_employees_empty(self, db, tenant):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="Empty Pos")
        )
        items = await service.list_position_employees(db, tenant.id, created["id"])
        assert items == []

    async def test_list_position_employees_returns_assigned(self, db, tenant, employee):
        # employee fixture has position_id set
        items = await service.list_position_employees(
            db, tenant.id, employee.position_id
        )
        assert len(items) == 1
        assert items[0]["id"] == employee.id
        assert items[0]["user_email"] == employee.user.email

    async def test_list_position_employees_not_found(self, db, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.list_position_employees(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_list_position_employees_tenant_isolation(self, db, tenant, employee):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug="other-tenant")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        with pytest.raises(HTTPException) as exc:
            await service.list_position_employees(db, other.id, employee.position_id)
        assert exc.value.status_code == 404

    async def test_list_position_employees_includes_division_and_spec(
        self, db, tenant, employee
    ):
        """HRP-32: drilldown rows must carry division/specialization/grade
        for the unified employees-list display."""
        from app.modules.company.models import Division
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.position.models import Position

        spec = DictionaryItem(
            tenant_id=tenant.id, type="specialization", title="QA"
        )
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Junior")
        div = Division(tenant_id=tenant.id, name="Engineering")
        db.add_all([spec, grade, div])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)
        await db.refresh(div)

        pos = await db.get(Position, employee.position_id)
        pos.specialization_id = spec.id
        pos.grade_id = grade.id
        pos.division_id = div.id
        employee.division_id = div.id
        await db.commit()
        db.expunge_all()

        items = await service.list_position_employees(
            db, tenant.id, employee.position_id
        )
        assert len(items) == 1
        row = items[0]
        assert row["specialization_title"] == "QA"
        assert row["grade_title"] == "Junior"
        assert row["division_name"] == "Engineering"
        # HRP-175: division_id surfaces so the unified EmployeeList can
        # turn the Division cell into a deep-link.
        assert row["division_id"] == div.id


class TestPositionCompetenceMatrix:
    async def test_returns_empty_when_position_has_no_grade_or_spec(
        self, db, tenant
    ):
        created = await service.create_position(
            db, tenant.id, PositionCreate(title="No matrix")
        )
        result = await service.get_position_competence_matrix(
            db, tenant.id, created["id"]
        )
        assert result["configured"] is False
        assert result["competences"] == []

    async def test_returns_competences_with_indicators(self, db, tenant):
        """HRP-32: position page must list competences and indicators
        attached to the (specialization, grade) pair."""
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            Indicator,
            SkillLevel,
        )
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )
        from app.modules.position.models import Position

        spec = DictionaryItem(
            tenant_id=tenant.id, type="specialization", title="Backend"
        )
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Middle")
        skill = SkillLevel(tenant_id=tenant.id, title="Intermediate", sort_index=1)
        group = CompetenceGroup(tenant_id=tenant.id, title="Tech")
        db.add_all([spec, grade, skill, group])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)
        await db.refresh(skill)
        await db.refresh(group)

        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="Python")
        db.add(comp)
        await db.commit()
        await db.refresh(comp)

        ind = Indicator(
            tenant_id=tenant.id,
            competence_id=comp.id,
            skill_level_id=skill.id,
            title="Writes idiomatic code",
            weight=1,
            sort_index=0,
        )
        db.add(ind)

        gs = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
        )
        db.add(gs)
        await db.commit()
        await db.refresh(gs)

        link = GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=skill.id,
        )
        db.add(link)

        pos = Position(
            tenant_id=tenant.id,
            title="Backend Middle",
            specialization_id=spec.id,
            grade_id=grade.id,
            source="manual",
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.get_position_competence_matrix(
            db, tenant.id, pos.id
        )
        assert result["configured"] is True
        assert result["grade_specialization_id"] == gs.id
        assert len(result["competences"]) == 1
        c = result["competences"][0]
        assert c["title"] == "Python"
        assert c["group_title"] == "Tech"
        assert c["skill_level_title"] == "Intermediate"
        assert len(c["indicators"]) == 1
        assert c["indicators"][0]["title"] == "Writes idiomatic code"


class TestPositionProfileExtrasHRP74:
    """HRP-57 E8: PositionRead must surface salary inheritance + matrix flag.

    Inheritance source = GradeSpecialization for the (spec, grade) pair.
    No new column on Position; computed on every read.
    """

    async def test_no_spec_or_grade_returns_null_extras(self, db, tenant):
        pos = await service.create_position(
            db, tenant.id, PositionCreate(title="Bare", headcount=3)
        )
        assert pos["salary_min"] is None
        assert pos["salary_max"] is None
        assert pos["salary_currency"] is None
        assert pos["matrix_configured"] is False
        # vacancy_count derives from headcount alone
        assert pos["vacancy_count"] == 3

    async def test_pair_without_grade_specialization_row(self, db, tenant):
        # Position points at spec/grade but the GradeSpecialization profile
        # has not been created yet — read must not crash, just return nulls.
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(
            tenant_id=tenant.id, type="specialization", title="Backend"
        )
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Senior")
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        pos = await service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="Profile-less",
                specialization_id=spec.id,
                grade_id=grade.id,
                headcount=2,
            ),
        )
        assert pos["salary_min"] is None
        assert pos["salary_currency"] is None
        assert pos["matrix_configured"] is False

    async def test_inherits_salary_and_matrix_flag(self, db, tenant):
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            SkillLevel,
        )
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        spec = DictionaryItem(
            tenant_id=tenant.id, type="specialization", title="Frontend"
        )
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Middle")
        skill = SkillLevel(tenant_id=tenant.id, title="Intermediate", sort_index=1)
        group = CompetenceGroup(tenant_id=tenant.id, title="Tech")
        db.add_all([spec, grade, skill, group])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)
        await db.refresh(skill)
        await db.refresh(group)

        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="React")
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=spec.id,
            salary_min=180_000,
            salary_max=220_000,
            salary_currency="RUB",
        )
        db.add_all([comp, gs])
        await db.commit()
        await db.refresh(comp)
        await db.refresh(gs)
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=skill.id,
            )
        )
        await db.commit()

        pos = await service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="React Middle",
                specialization_id=spec.id,
                grade_id=grade.id,
                headcount=4,
            ),
        )
        assert pos["salary_min"] == 180_000
        assert pos["salary_max"] == 220_000
        assert pos["salary_currency"] == "RUB"
        assert pos["matrix_configured"] is True
        assert pos["vacancy_count"] == 4

        # list_positions runs the bulk path; same fields must appear there too.
        items, _ = await service.list_positions(db, tenant.id)
        target = next(p for p in items if p["id"] == pos["id"])
        assert target["salary_min"] == 180_000
        assert target["matrix_configured"] is True

    async def test_matrix_configured_false_without_links(self, db, tenant):
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import GradeSpecialization

        spec = DictionaryItem(tenant_id=tenant.id, type="specialization", title="QA")
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Junior")
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        gs = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=spec.id,
            salary_min=100_000,
            salary_max=130_000,
        )
        db.add(gs)
        await db.commit()

        pos = await service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="QA Junior",
                specialization_id=spec.id,
                grade_id=grade.id,
                headcount=1,
            ),
        )
        # Profile exists, salary inherits, but no competence links.
        assert pos["salary_min"] == 100_000
        assert pos["matrix_configured"] is False

    async def test_vacancy_count_clipped_to_zero_when_overstaffed(self, db, tenant):
        # If somehow assigned > headcount (HR data error, race), vacancy
        # must not go negative.
        from datetime import date

        from app.modules.auth.models import User
        from app.modules.employee.models import Employee

        pos_dict = await service.create_position(
            db, tenant.id, PositionCreate(title="Overstaffed", headcount=1)
        )
        for i in range(2):
            u = User(
                email=f"overstaff-{i}@test.com",
                password_hash="x",
                first_name="O",
                last_name="S",
                tenant_id=tenant.id,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
            db.add(
                Employee(
                    tenant_id=tenant.id,
                    user_id=u.id,
                    position_id=pos_dict["id"],
                    hire_date=date.today(),
                )
            )
        await db.commit()

        result = await service.get_position(db, tenant.id, pos_dict["id"])
        assert result["employee_count"] == 2
        assert result["vacancy_count"] == 0

    async def test_unset_headcount_yields_null_vacancy(self, db, tenant):
        # When headcount is unset there is no plan, so "vacancy" has no
        # meaning — the field must be None, not 0.
        pos = await service.create_position(
            db, tenant.id, PositionCreate(title="Headless")
        )
        assert pos["headcount"] is None
        assert pos["vacancy_count"] is None

    async def test_cross_tenant_grade_specialization_is_isolated(
        self, db, tenant
    ):
        # If two tenants happen to use the same shared (origin) spec/grade
        # ids, each must see only its own GS row — no salary cross-talk.
        from app.modules.company.models import Tenant
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import GradeSpecialization

        # Origin (shared) spec + grade. tenant_id=NULL means visible to all.
        spec = DictionaryItem(
            tenant_id=None, type="specialization", title="SharedSpec"
        )
        grade = DictionaryItem(tenant_id=None, type="grade", title="SharedGrade")
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        # Other tenant's profile row carries different salary.
        other_tenant = Tenant(name="Other Co", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)
        db.add(
            GradeSpecialization(
                tenant_id=other_tenant.id,
                grade_id=grade.id,
                specialization_id=spec.id,
                salary_min=999_999,
            )
        )
        # Our tenant's own profile row.
        db.add(
            GradeSpecialization(
                tenant_id=tenant.id,
                grade_id=grade.id,
                specialization_id=spec.id,
                salary_min=150_000,
            )
        )
        await db.commit()

        pos = await service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="X-tenant",
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        # Must reflect our row, not the other tenant's.
        assert pos["salary_min"] == 150_000
