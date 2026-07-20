"""Unit tests for the Specialization domain service (POS2)."""

import uuid

import pytest
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary import service as dict_service
from app.modules.dictionary.schemas import DictionaryItemCreate
from app.modules.grade_system import service as grade_service
from app.modules.grade_system.schemas import GradeSpecializationCreate
from app.modules.position import service as position_service
from app.modules.position.schemas import PositionCreate
from app.modules.specialization import service
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _make_spec(db, tenant_id, title="Backend"):
    return await dict_service.create_item(
        db, tenant_id, "specialization", DictionaryItemCreate(title=title)
    )


async def _make_grade(db, tenant_id, title="Junior", sort_index: int = 0):
    return await dict_service.create_item(
        db,
        tenant_id,
        "grade",
        DictionaryItemCreate(title=title, sort_index=sort_index),
    )


async def _make_pair(db, tenant_id, spec_id, grade_id, **kwargs):
    return await grade_service.create_chain(
        db,
        tenant_id,
        GradeSpecializationCreate(
            grade_id=grade_id, specialization_id=spec_id, **kwargs
        ),
    )


async def _make_competence(db, tenant_id, title="SQL"):
    group = CompetenceGroup(title=f"Group {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(title=title, group_id=group.id, tenant_id=tenant_id)
    db.add(comp)
    await db.commit()
    await db.refresh(comp)
    return comp


async def _make_level(db, title="Basic", sort_index: int = 0):
    level = SkillLevel(title=title, sort_index=sort_index)
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


# ---------------------------------------------------------------------------
# list / detail
# ---------------------------------------------------------------------------


class TestListSpecializations:
    async def test_returns_specs_with_zero_stats(self, db, tenant):
        await _make_spec(db, tenant.id, "Backend")
        await _make_spec(db, tenant.id, "Frontend")
        items = await service.list_specializations(db, tenant.id)
        titles = [s["title"] for s in items]
        assert "Backend" in titles
        assert "Frontend" in titles
        backend = next(s for s in items if s["title"] == "Backend")
        assert backend["grade_count"] == 0
        assert backend["position_count"] == 0
        assert backend["assigned_count"] == 0
        assert backend["headcount_total"] == 0

    async def test_counts_grades_and_positions(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "Data")
        grade = await _make_grade(db, tenant.id, "Senior")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="Senior Data Engineer",
                specialization_id=spec["id"],
                grade_id=grade["id"],
                headcount=5,
            ),
        )
        items = await service.list_specializations(db, tenant.id)
        data = next(s for s in items if s["title"] == "Data")
        assert data["grade_count"] == 1
        assert data["position_count"] == 1
        assert data["headcount_total"] == 5
        assert data["assigned_count"] == 0

    async def test_tenant_isolation(self, db, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        await _make_spec(db, tenant.id, "Tenant A Spec")

        items = await service.list_specializations(db, other.id)
        titles = [s["title"] for s in items]
        assert "Tenant A Spec" not in titles


class TestSpecializationDetail:
    async def test_404_on_unknown(self, db, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_specialization_detail(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_404_on_grade_id(self, db, tenant):
        # Passing a grade_id (different `type`) must not leak details.
        grade = await _make_grade(db, tenant.id, "Lead")
        with pytest.raises(HTTPException) as exc:
            await service.get_specialization_detail(db, tenant.id, grade["id"])
        assert exc.value.status_code == 404

    async def test_detail_includes_grades(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "QA")
        grade = await _make_grade(db, tenant.id, "Mid")
        await _make_pair(
            db,
            tenant.id,
            spec["id"],
            grade["id"],
            description="Mid QA",
            requirements="3y experience",
            salary_min=100_000,
            salary_max=150_000,
        )
        detail = await service.get_specialization_detail(db, tenant.id, spec["id"])
        assert detail["title"] == "QA"
        assert len(detail["grades"]) == 1
        gd = detail["grades"][0]
        assert gd["description"] == "Mid QA"
        assert gd["requirements"] == "3y experience"
        assert gd["salary_min"] == 100_000
        assert gd["matrix_status"] == "empty"
        assert gd["competence_count"] == 0


class TestPositionsSummary:
    async def test_empty_when_no_positions(self, db, tenant):
        spec = await _make_spec(db, tenant.id)
        result = await service.get_positions_summary(db, tenant.id, spec["id"])
        assert result == []

    async def test_groups_by_division(self, db, tenant):
        from app.modules.company.models import Division

        spec = await _make_spec(db, tenant.id, "DevOps")
        grade = await _make_grade(db, tenant.id, "Mid DevOps")
        div_a = Division(name="Platform", tenant_id=tenant.id)
        div_b = Division(name="Apps", tenant_id=tenant.id)
        db.add_all([div_a, div_b])
        await db.commit()
        await db.refresh(div_a)
        await db.refresh(div_b)

        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="DevOps Platform Engineer",
                specialization_id=spec["id"],
                grade_id=grade["id"],
                division_id=div_a.id,
                headcount=2,
            ),
        )
        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="DevOps Apps Engineer",
                specialization_id=spec["id"],
                grade_id=grade["id"],
                division_id=div_b.id,
                headcount=1,
            ),
        )

        result = await service.get_positions_summary(db, tenant.id, spec["id"])
        assert len(result) == 2
        names = [b["division_name"] for b in result]
        assert names == ["Apps", "Platform"]
        platform = next(b for b in result if b["division_name"] == "Platform")
        assert platform["positions"][0]["headcount"] == 2
        assert platform["positions"][0]["assigned"] == 0
        assert platform["positions"][0]["vacant"] == 2


class TestSpecializationEmployeesHRP70:
    """HRP-57 §3.1 (E4): Employees tab on the Specialization detail page.

    Lists employees in any Position attached to this specialization. The row
    shape mirrors `/positions/{id}/employees` so the same UI component
    renders. Edge cases worth covering: spec with no positions, spec with
    multiple positions across grades, employee on a position with a different
    specialization (must not appear).
    """

    async def test_empty_when_spec_has_no_positions(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "Lonely")
        result = await service.list_employees(db, tenant.id, spec["id"])
        assert result == []

    async def test_returns_only_employees_of_this_spec(
        self, db, tenant, user
    ):
        from datetime import date

        from app.modules.auth.models import User
        from app.modules.employee.models import Employee

        spec_a = await _make_spec(db, tenant.id, "SpecA")
        spec_b = await _make_spec(db, tenant.id, "SpecB")
        grade = await _make_grade(db, tenant.id, "Junior")

        pos_a = await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="A1",
                specialization_id=spec_a["id"],
                grade_id=grade["id"],
                headcount=2,
            ),
        )
        pos_b = await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="B1",
                specialization_id=spec_b["id"],
                grade_id=grade["id"],
                headcount=2,
            ),
        )

        # Two employees on spec A, one on spec B — only the first two count.
        for i, pos_id in enumerate([pos_a["id"], pos_a["id"], pos_b["id"]]):
            u = User(
                email=f"emp-{i}-{uuid.uuid4().hex[:6]}@test.com",
                password_hash="x",
                first_name=f"Emp{i}",
                last_name="X",
                tenant_id=tenant.id,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
            db.add(
                Employee(
                    tenant_id=tenant.id,
                    user_id=u.id,
                    position_id=pos_id,
                    hire_date=date.today(),
                )
            )
        await db.commit()

        result = await service.list_employees(db, tenant.id, spec_a["id"])
        assert len(result) == 2
        for row in result:
            assert row["specialization_title"] == "SpecA"
            assert row["position_title"] == "A1"

    async def test_404_on_unknown_specialization(self, db, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.list_employees(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_cross_tenant_isolation(self, db, tenant):
        # Specialization in tenant A must be invisible from tenant B's
        # context (returns 404, not its employees).
        from app.modules.company.models import Tenant

        spec_a = await _make_spec(db, tenant.id, "OnlyInA")
        tenant_b = Tenant(
            name=f"Other {uuid.uuid4().hex[:6]}",
            slug=f"other-{uuid.uuid4().hex[:8]}",
        )
        db.add(tenant_b)
        await db.commit()
        await db.refresh(tenant_b)

        with pytest.raises(HTTPException) as exc:
            await service.list_employees(db, tenant_b.id, spec_a["id"])
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# matrix get / upsert
# ---------------------------------------------------------------------------


class TestMatrix:
    async def test_get_404_on_missing_pair(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "ML")
        grade = await _make_grade(db, tenant.id, "Junior ML")
        with pytest.raises(HTTPException) as exc:
            await service.get_matrix(db, tenant.id, spec["id"], grade["id"])
        assert exc.value.status_code == 404

    async def test_get_returns_empty_for_empty_pair(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "Mobile")
        grade = await _make_grade(db, tenant.id, "Mid Mobile")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        result = await service.get_matrix(db, tenant.id, spec["id"], grade["id"])
        assert result == []

    async def test_upsert_writes_links(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Backend Up")
        grade = await _make_grade(db, tenant.id, "Senior Up")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        comp = await _make_competence(db, tenant.id, "Python")
        level = await _make_level(db, "Basic")

        result = await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            grade["id"],
            [{"competence_id": comp.id, "skill_level_id": level.id}],
        )
        assert len(result) == 1
        assert result[0]["competence_id"] == comp.id
        assert result[0]["skill_level_id"] == level.id

    async def test_upsert_replaces_existing_links(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Architect")
        grade = await _make_grade(db, tenant.id, "Lead Architect")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        comp_a = await _make_competence(db, tenant.id, "Design")
        comp_b = await _make_competence(db, tenant.id, "Comms")
        level = await _make_level(db, "Adv")

        await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            grade["id"],
            [{"competence_id": comp_a.id, "skill_level_id": level.id}],
        )
        result = await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            grade["id"],
            [{"competence_id": comp_b.id, "skill_level_id": level.id}],
        )
        comp_ids = [r["competence_id"] for r in result]
        assert comp_a.id not in comp_ids
        assert comp_b.id in comp_ids

    async def test_upsert_collapses_duplicate_competence(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Dup")
        grade = await _make_grade(db, tenant.id, "Mid Dup")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        comp = await _make_competence(db, tenant.id, "DupComp")
        level_a = await _make_level(db, "L1")
        level_b = await _make_level(db, "L2")

        result = await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            grade["id"],
            [
                {"competence_id": comp.id, "skill_level_id": level_a.id},
                {"competence_id": comp.id, "skill_level_id": level_b.id},
            ],
        )
        assert len(result) == 1
        assert result[0]["skill_level_id"] == level_b.id

    async def test_upsert_rejects_foreign_competence(self, db, tenant, user):
        from app.modules.company.models import Tenant

        other = Tenant(name="Foreign", slug=f"foreign-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        spec = await _make_spec(db, tenant.id, "Iso")
        grade = await _make_grade(db, tenant.id, "Mid Iso")
        await _make_pair(db, tenant.id, spec["id"], grade["id"])
        foreign_comp = await _make_competence(db, other.id, "Foreign")
        level = await _make_level(db, "L")

        with pytest.raises(HTTPException) as exc:
            await service.upsert_matrix(
                db,
                tenant.id,
                user.id,
                spec["id"],
                grade["id"],
                [
                    {
                        "competence_id": foreign_comp.id,
                        "skill_level_id": level.id,
                    }
                ],
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# POS4 — cascade normalization on bulk upsert
# ---------------------------------------------------------------------------


class TestMatrixCascade:
    async def test_promotion_propagates_up_via_single_grade(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Casc-A")
        junior = await _make_grade(db, tenant.id, "Junior A", sort_index=10)
        middle = await _make_grade(db, tenant.id, "Middle A", sort_index=20)
        senior = await _make_grade(db, tenant.id, "Senior A", sort_index=30)
        await _make_pair(db, tenant.id, spec["id"], junior["id"])
        await _make_pair(db, tenant.id, spec["id"], middle["id"])
        await _make_pair(db, tenant.id, spec["id"], senior["id"])

        comp = await _make_competence(db, tenant.id, "Python A")
        basic = await _make_level(db, "Basic A", sort_index=10)

        await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            junior["id"],
            [{"competence_id": comp.id, "skill_level_id": basic.id}],
        )

        bulk = await service.get_matrix_bulk(db, tenant.id, spec["id"])
        per_grade = {
            block["grade_id"]: {
                link["competence_id"]: link["skill_level_id"] for link in block["links"]
            }
            for block in bulk["grades"]
        }
        assert per_grade[junior["id"]][comp.id] == basic.id
        assert per_grade[middle["id"]][comp.id] == basic.id
        assert per_grade[senior["id"]][comp.id] == basic.id

    async def test_higher_explicit_level_is_kept_and_lower_inherits(
        self, db, tenant, user
    ):
        spec = await _make_spec(db, tenant.id, "Casc-B")
        junior = await _make_grade(db, tenant.id, "Junior B", sort_index=10)
        senior = await _make_grade(db, tenant.id, "Senior B", sort_index=30)
        await _make_pair(db, tenant.id, spec["id"], junior["id"])
        await _make_pair(db, tenant.id, spec["id"], senior["id"])

        comp = await _make_competence(db, tenant.id, "Comp B")
        basic = await _make_level(db, "Basic B", sort_index=10)
        advanced = await _make_level(db, "Advanced B", sort_index=30)

        await service.upsert_matrix_bulk(
            db,
            tenant.id,
            user.id,
            spec["id"],
            [
                {
                    "grade_id": junior["id"],
                    "links": [{"competence_id": comp.id, "skill_level_id": basic.id}],
                },
                {
                    "grade_id": senior["id"],
                    "links": [
                        {
                            "competence_id": comp.id,
                            "skill_level_id": advanced.id,
                        }
                    ],
                },
            ],
        )

        bulk = await service.get_matrix_bulk(db, tenant.id, spec["id"])
        per_grade = {
            block["grade_id"]: {
                link["competence_id"]: link["skill_level_id"] for link in block["links"]
            }
            for block in bulk["grades"]
        }
        assert per_grade[junior["id"]][comp.id] == basic.id
        assert per_grade[senior["id"]][comp.id] == advanced.id

    async def test_inversion_is_normalized_higher_grade_upgraded(
        self, db, tenant, user
    ):
        """Direct API call with senior < junior → server upgrades senior."""
        spec = await _make_spec(db, tenant.id, "Casc-C")
        junior = await _make_grade(db, tenant.id, "Junior C", sort_index=10)
        senior = await _make_grade(db, tenant.id, "Senior C", sort_index=30)
        await _make_pair(db, tenant.id, spec["id"], junior["id"])
        await _make_pair(db, tenant.id, spec["id"], senior["id"])

        comp = await _make_competence(db, tenant.id, "Comp C")
        basic = await _make_level(db, "Basic C", sort_index=10)
        advanced = await _make_level(db, "Advanced C", sort_index=30)

        await service.upsert_matrix_bulk(
            db,
            tenant.id,
            user.id,
            spec["id"],
            [
                {
                    "grade_id": junior["id"],
                    "links": [
                        {
                            "competence_id": comp.id,
                            "skill_level_id": advanced.id,
                        }
                    ],
                },
                {
                    "grade_id": senior["id"],
                    "links": [{"competence_id": comp.id, "skill_level_id": basic.id}],
                },
            ],
        )

        bulk = await service.get_matrix_bulk(db, tenant.id, spec["id"])
        per_grade = {
            block["grade_id"]: {
                link["competence_id"]: link["skill_level_id"] for link in block["links"]
            }
            for block in bulk["grades"]
        }
        # Junior keeps the explicit Advanced; Senior is normalized up to Advanced.
        assert per_grade[junior["id"]][comp.id] == advanced.id
        assert per_grade[senior["id"]][comp.id] == advanced.id

    async def test_partial_bulk_keeps_untouched_grade_state(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Casc-D")
        junior = await _make_grade(db, tenant.id, "Junior D", sort_index=10)
        middle = await _make_grade(db, tenant.id, "Middle D", sort_index=20)
        await _make_pair(db, tenant.id, spec["id"], junior["id"])
        await _make_pair(db, tenant.id, spec["id"], middle["id"])

        comp_a = await _make_competence(db, tenant.id, "Comp D-A")
        comp_b = await _make_competence(db, tenant.id, "Comp D-B")
        basic = await _make_level(db, "Basic D", sort_index=10)
        advanced = await _make_level(db, "Advanced D", sort_index=30)

        # Seed Middle with comp_b at advanced.
        await service.upsert_matrix(
            db,
            tenant.id,
            user.id,
            spec["id"],
            middle["id"],
            [{"competence_id": comp_b.id, "skill_level_id": advanced.id}],
        )

        # Now bulk-update only Junior — Middle's comp_b should stay.
        await service.upsert_matrix_bulk(
            db,
            tenant.id,
            user.id,
            spec["id"],
            [
                {
                    "grade_id": junior["id"],
                    "links": [
                        {
                            "competence_id": comp_a.id,
                            "skill_level_id": basic.id,
                        }
                    ],
                }
            ],
        )

        bulk = await service.get_matrix_bulk(db, tenant.id, spec["id"])
        per_grade = {
            block["grade_id"]: {
                link["competence_id"]: link["skill_level_id"] for link in block["links"]
            }
            for block in bulk["grades"]
        }
        # Junior gets comp_a=basic; comp_b cascades up from middle (no link
        # below middle exists for comp_b, so junior is left empty for comp_b).
        assert per_grade[junior["id"]] == {comp_a.id: basic.id}
        # Middle keeps comp_b=advanced; comp_a cascades up from junior=basic.
        assert per_grade[middle["id"]][comp_b.id] == advanced.id
        assert per_grade[middle["id"]][comp_a.id] == basic.id

    async def test_bulk_unknown_grade_returns_404(self, db, tenant, user):
        spec = await _make_spec(db, tenant.id, "Casc-E")
        with pytest.raises(HTTPException) as exc:
            await service.upsert_matrix_bulk(
                db,
                tenant.id,
                user.id,
                spec["id"],
                [{"grade_id": uuid.uuid4(), "links": []}],
            )
        assert exc.value.status_code == 404

    async def test_indicators_by_level_returns_sort_index(self, db, tenant):
        from app.modules.competence.models import Indicator

        comp = await _make_competence(db, tenant.id, "Comp Ind")
        basic = await _make_level(db, "Basic Ind", sort_index=10)
        advanced = await _make_level(db, "Advanced Ind", sort_index=30)
        db.add_all(
            [
                Indicator(
                    title="Knows basics",
                    competence_id=comp.id,
                    skill_level_id=basic.id,
                    tenant_id=tenant.id,
                ),
                Indicator(
                    title="Designs systems",
                    competence_id=comp.id,
                    skill_level_id=advanced.id,
                    tenant_id=tenant.id,
                ),
            ]
        )
        await db.commit()

        rows = await service.get_competence_indicators_by_level(db, tenant.id, comp.id)
        titles_by_level = {r["skill_level_title"]: r["title"] for r in rows}
        assert titles_by_level["Basic Ind"] == "Knows basics"
        assert titles_by_level["Advanced Ind"] == "Designs systems"
        sort_idx = {r["skill_level_title"]: r["skill_level_sort_index"] for r in rows}
        assert sort_idx["Basic Ind"] == 10
        assert sort_idx["Advanced Ind"] == 30


# ---------------------------------------------------------------------------
# Grades CRUD (HRP-57 P1)
# ---------------------------------------------------------------------------


class TestAddGrades:
    async def test_bulk_add_assigns_incremental_sort_index(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Bulk")
        g1 = await _make_grade(db, tenant.id, "P1 Junior")
        g2 = await _make_grade(db, tenant.id, "P1 Middle")
        g3 = await _make_grade(db, tenant.id, "P1 Senior")

        result = await service.add_grades(
            db, tenant.id, spec["id"], [g1["id"], g2["id"], g3["id"]]
        )
        sort_by_grade = {r["grade_id"]: r["sort_index"] for r in result}
        # Pairs appended in input order.
        assert sort_by_grade[g1["id"]] == 0
        assert sort_by_grade[g2["id"]] == 1
        assert sort_by_grade[g3["id"]] == 2

    async def test_bulk_add_is_idempotent(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Idem")
        g1 = await _make_grade(db, tenant.id, "P1 Junior")
        await service.add_grades(db, tenant.id, spec["id"], [g1["id"]])
        # Second call with the same grade — no-op, still one pair.
        result = await service.add_grades(db, tenant.id, spec["id"], [g1["id"]])
        assert len(result) == 1

    async def test_bulk_add_appends_after_existing(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Append")
        g1 = await _make_grade(db, tenant.id, "P1 Junior")
        g2 = await _make_grade(db, tenant.id, "P1 Middle")
        await service.add_grades(db, tenant.id, spec["id"], [g1["id"]])
        # Second batch starts after existing max sort_index.
        result = await service.add_grades(db, tenant.id, spec["id"], [g2["id"]])
        by_grade = {r["grade_id"]: r["sort_index"] for r in result}
        assert by_grade[g1["id"]] == 0
        assert by_grade[g2["id"]] == 1

    async def test_404_when_grade_id_is_not_a_grade(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Wrong-Type")
        another_spec = await _make_spec(db, tenant.id, "P1-Other-Spec")
        with pytest.raises(HTTPException) as exc:
            await service.add_grades(
                db, tenant.id, spec["id"], [another_spec["id"]]
            )
        assert exc.value.status_code == 404


class TestReorderGrades:
    async def test_reorder_persists_new_indices(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Reorder")
        g1 = await _make_grade(db, tenant.id, "P1 G1")
        g2 = await _make_grade(db, tenant.id, "P1 G2")
        g3 = await _make_grade(db, tenant.id, "P1 G3")
        await service.add_grades(
            db, tenant.id, spec["id"], [g1["id"], g2["id"], g3["id"]]
        )

        await service.reorder_grades(
            db,
            tenant.id,
            spec["id"],
            [
                {"grade_id": g1["id"], "sort_index": 2},
                {"grade_id": g2["id"], "sort_index": 0},
                {"grade_id": g3["id"], "sort_index": 1},
            ],
        )
        out = await service.get_grades_with_attrs(db, tenant.id, spec["id"])
        order = [g["grade_id"] for g in out]
        assert order == [g2["id"], g3["id"], g1["id"]]

    async def test_reorder_unknown_grade_returns_404(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Reorder-404")
        with pytest.raises(HTTPException) as exc:
            await service.reorder_grades(
                db,
                tenant.id,
                spec["id"],
                [{"grade_id": uuid.uuid4(), "sort_index": 0}],
            )
        assert exc.value.status_code == 404


class TestPatchGrade:
    async def test_patch_updates_salary_and_description(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Patch")
        grade = await _make_grade(db, tenant.id, "P1 Patch Grade")
        await service.add_grades(db, tenant.id, spec["id"], [grade["id"]])

        out = await service.patch_grade(
            db,
            tenant.id,
            spec["id"],
            grade["id"],
            {
                "description": "Sets the bar",
                "salary_min": 200_000,
                "salary_max": 300_000,
            },
        )
        assert out["description"] == "Sets the bar"
        assert out["salary_min"] == 200_000
        assert out["salary_max"] == 300_000

    async def test_patch_rejects_inverted_salary_range(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Patch-Range")
        grade = await _make_grade(db, tenant.id, "P1 Patch Range Grade")
        await service.add_grades(db, tenant.id, spec["id"], [grade["id"]])

        with pytest.raises(HTTPException) as exc:
            await service.patch_grade(
                db,
                tenant.id,
                spec["id"],
                grade["id"],
                {"salary_min": 300_000, "salary_max": 100_000},
            )
        assert exc.value.status_code == 400


class TestDeleteGrade:
    async def test_delete_removes_pair(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Delete")
        grade = await _make_grade(db, tenant.id, "P1 Delete Grade")
        await service.add_grades(db, tenant.id, spec["id"], [grade["id"]])

        await service.delete_grade(db, tenant.id, spec["id"], grade["id"])
        out = await service.get_grades_with_attrs(db, tenant.id, spec["id"])
        assert out == []

    async def test_add_remove_diff_round_trip(self, db, tenant):
        """HRP-158: Manage-grades dialog drives an additive batch + an
        explicit delete on the same spec. The service must accept the two
        calls back-to-back and finish with only the still-checked grade."""
        spec = await _make_spec(db, tenant.id, "P1-Diff")
        g1 = await _make_grade(db, tenant.id, "P1 Diff Junior")
        g2 = await _make_grade(db, tenant.id, "P1 Diff Middle")
        g3 = await _make_grade(db, tenant.id, "P1 Diff Senior")

        # Dialog opens, operator picks two grades.
        await service.add_grades(db, tenant.id, spec["id"], [g1["id"], g2["id"]])
        # On a follow-up open the user keeps g2, unticks g1, adds g3.
        await service.delete_grade(db, tenant.id, spec["id"], g1["id"])
        await service.add_grades(db, tenant.id, spec["id"], [g3["id"]])

        rows = await service.get_grades_with_attrs(db, tenant.id, spec["id"])
        remaining = sorted(r["grade_id"] for r in rows)
        assert remaining == sorted([g2["id"], g3["id"]])

    async def test_delete_blocks_when_position_uses_pair(self, db, tenant):
        spec = await _make_spec(db, tenant.id, "P1-Delete-Used")
        grade = await _make_grade(db, tenant.id, "P1 Delete-Used Grade")
        await service.add_grades(db, tenant.id, spec["id"], [grade["id"]])

        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="P1 Live Position",
                specialization_id=spec["id"],
                grade_id=grade["id"],
                headcount=1,
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_grade(db, tenant.id, spec["id"], grade["id"])
        assert exc.value.status_code == 409

    async def test_delete_ignores_positions_in_other_specs(self, db, tenant):
        # The 409 guard must scope to (spec, grade), not just grade — a
        # Position in *another* spec sharing the same dictionary grade
        # must not block deletion here (HRP-57 P2 review feedback).
        spec_a = await _make_spec(db, tenant.id, "P1-Delete-Spec-A")
        spec_b = await _make_spec(db, tenant.id, "P1-Delete-Spec-B")
        grade = await _make_grade(db, tenant.id, "P1 Delete Shared Grade")
        await service.add_grades(db, tenant.id, spec_a["id"], [grade["id"]])
        await service.add_grades(db, tenant.id, spec_b["id"], [grade["id"]])

        # Position attached to spec_b only.
        await position_service.create_position(
            db,
            tenant.id,
            PositionCreate(
                title="P1 Sibling Position",
                specialization_id=spec_b["id"],
                grade_id=grade["id"],
                headcount=1,
            ),
        )

        # Removing the grade from spec_a must succeed despite spec_b's
        # position.
        await service.delete_grade(db, tenant.id, spec_a["id"], grade["id"])
        spec_a_pairs = await service.get_grades_with_attrs(
            db, tenant.id, spec_a["id"]
        )
        assert spec_a_pairs == []
        spec_b_pairs = await service.get_grades_with_attrs(
            db, tenant.id, spec_b["id"]
        )
        assert len(spec_b_pairs) == 1
