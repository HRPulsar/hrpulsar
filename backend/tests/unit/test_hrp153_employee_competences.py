"""HRP-153 -- Employee competences tab selection + percent math.

The assessment math (``_compute_per_level_breakdowns_batch``) is exercised
in ``test_assessment_role_calc_and_review``; here we monkey-patch it so
the test surface is just the spec from HRP-153 + the reporter's
2026-05-26 REDO clarifications:

* Current block: one row per (competence, required_level), percent =
  ``avg(breakdown[..required])`` from the latest Done assessment whose
  target level >= required; lower-only assessments do not fill the slot.
* Other block: one row per competence whose highest assessed target
  exceeds Current's required level (or which Current does not list at
  all). Percent is averaged over the breakdown rows up to that highest
  assessed target.
* Both blocks expose ``level_breakdown`` so the (i) popup can render the
  Skill level / Percent table.
"""

from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from app.modules.assessment.models import Assessment, AssessmentStatus
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.competence_overview import compute_competence_overview
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.position.models import Position
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def done_status(db: AsyncSession):
    from sqlalchemy import select

    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "done")
    )
    status = result.scalar_one_or_none()
    if status is None:
        status = AssessmentStatus(code="done", title="Done", sequence=6)
        db.add(status)
        await db.commit()
        await db.refresh(status)
    return status


@pytest_asyncio.fixture
async def competence_setup(db: AsyncSession, tenant):
    """Two competences ('Comp A', 'Comp B') and three skill levels
    (Basic/Intermediate/Advanced) so the selection tests have enough
    variety to distinguish required vs lower vs higher.
    """
    group = CompetenceGroup(title="Group HRP-153", tenant_id=tenant.id)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    comp_a = Competence(title="Comp A", group_id=group.id, tenant_id=tenant.id)
    comp_b = Competence(title="Comp B", group_id=group.id, tenant_id=tenant.id)
    db.add_all([comp_a, comp_b])
    levels = [
        SkillLevel(title="Basic", sort_index=0, tenant_id=tenant.id),
        SkillLevel(title="Intermediate", sort_index=1, tenant_id=tenant.id),
        SkillLevel(title="Advanced", sort_index=2, tenant_id=tenant.id),
    ]
    db.add_all(levels)
    await db.commit()
    for x in (group, comp_a, comp_b, *levels):
        await db.refresh(x)
    return {
        "group": group,
        "comp_a": comp_a,
        "comp_b": comp_b,
        "basic": levels[0],
        "intermediate": levels[1],
        "advanced": levels[2],
    }


@pytest_asyncio.fixture
async def employee_with_position(
    db: AsyncSession,
    user,
    tenant,
    competence_setup,
):
    spec_item = DictionaryItem(
        type="specialization", title="Backend", tenant_id=tenant.id
    )
    grade_item = DictionaryItem(type="grade", title="Middle", tenant_id=tenant.id)
    db.add_all([spec_item, grade_item])
    await db.commit()
    await db.refresh(spec_item)
    await db.refresh(grade_item)

    position = Position(
        tenant_id=tenant.id,
        title="Backend Middle",
        source="manual",
        specialization_id=spec_item.id,
        grade_id=grade_item.id,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)

    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade_item.id,
        specialization_id=spec_item.id,
    )
    db.add(gs)
    await db.commit()
    await db.refresh(gs)

    # Required: Comp A @ Intermediate, Comp B @ Advanced
    db.add_all(
        [
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=competence_setup["comp_a"].id,
                skill_level_id=competence_setup["intermediate"].id,
            ),
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=competence_setup["comp_b"].id,
                skill_level_id=competence_setup["advanced"].id,
            ),
        ]
    )
    await db.commit()

    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        position_id=position.id,
        position_title=position.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _make_assessment(
    db: AsyncSession,
    tenant,
    employee: Employee,
    done_status,
    *,
    completed_at: datetime,
) -> Assessment:
    # Bootstrap minimal assessment_types row if missing.
    from app.modules.assessment.models import AssessmentType
    from sqlalchemy import select

    type_result = await db.execute(
        select(AssessmentType).where(AssessmentType.code == "self")
    )
    atype = type_result.scalar_one_or_none()
    if atype is None:
        atype = AssessmentType(code="self", title="Self assessment")
        db.add(atype)
        await db.commit()
        await db.refresh(atype)

    a = Assessment(
        tenant_id=tenant.id,
        employee_id=employee.id,
        type_id=atype.id,
        status_id=done_status.id,
        initiator_id=employee.user_id,
        finished_at=completed_at,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


def _stub_breakdown(*, per_assessment_rows):
    """Build a monkey-patchable replacement for
    ``_compute_per_level_breakdowns_batch`` that returns the rows we hand
    it, keyed by assessment id. Lets the tests focus on selection logic
    without setting up the answers/indicators graph.
    """

    async def _stub(_db, assessments):
        return {a.id: per_assessment_rows.get(a.id, {}) for a in assessments}

    return _stub


class TestCompetenceOverview:
    async def test_no_position_returns_empty(
        self, db: AsyncSession, tenant, user, done_status, monkeypatch
    ):
        # Employee with no position -> no required pairs and no assessments
        # -> both blocks empty.
        emp = Employee(
            user_id=user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows={}),
        )
        result = await compute_competence_overview(db, tenant.id, emp)
        assert result["current_position"] == []
        assert result["other"] == []

    async def test_required_without_assessments(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows={}),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        assert {row["competence_title"] for row in result["current_position"]} == {
            "Comp A",
            "Comp B",
        }
        assert all(row["percent"] is None for row in result["current_position"])
        assert all(row["level_breakdown"] == [] for row in result["current_position"])
        assert result["other"] == []

    async def test_required_level_exact_match(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Assessment targeted the required level (Intermediate). With
        # cascade trimming the breakdown contains Basic + Intermediate.
        # Reporter Q1: "overall % of the competence from this assessment"
        # => average over the cascade rows = (100 + 80) / 2 = 90.
        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 100,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 80,
                    },
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        rows = {r["competence_title"]: r for r in result["current_position"]}
        assert rows["Comp A"]["percent"] == 90
        # Breakdown rows feed the (i) popup, keep them aligned.
        assert [r["skill_level_title"] for r in rows["Comp A"]["level_breakdown"]] == [
            "Basic",
            "Intermediate",
        ]
        assert rows["Comp B"]["percent"] is None
        assert result["other"] == []

    async def test_required_basic_from_higher_assessment(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Reporter Q2: position requires Basic, assessment targeted
        # Advanced with breakdown Basic 100 / Intermediate 80 / Advanced
        # 30 -> result for Basic = 100 (only Basic level is averaged).
        from sqlalchemy import update

        await db.execute(
            update(GradeCompetenceLink)
            .where(
                GradeCompetenceLink.competence_id == competence_setup["comp_a"].id
            )
            .values(skill_level_id=competence_setup["basic"].id)
        )
        await db.commit()

        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 100,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 80,
                    },
                    {
                        "skill_level_id": competence_setup["advanced"].id,
                        "skill_level_title": "Advanced",
                        "sort_index": 2,
                        "percent": 30,
                    },
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_row = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp A"
        )
        assert comp_a_row["percent"] == 100
        # Higher-level overload spills into Other at Advanced (avg of
        # 100/80/30 = 70).
        other = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(other) == 1
        assert other[0]["skill_level_title"] == "Advanced"
        assert other[0]["percent"] == 70

    async def test_higher_level_assessment_averages_up_to_required(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Reporter Q2b: position requires Intermediate, assessment
        # targeted Advanced with breakdown Basic 100 / Intermediate 80 /
        # Advanced 30 -> result for Intermediate = (100 + 80) / 2 = 90.
        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 100,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 80,
                    },
                    {
                        "skill_level_id": competence_setup["advanced"].id,
                        "skill_level_title": "Advanced",
                        "sort_index": 2,
                        "percent": 30,
                    },
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_row = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp A"
        )
        assert comp_a_row["percent"] == 90
        # Other gets the Advanced overload, percent = avg(100, 80, 30) =
        # 70 (Reporter Q3).
        other = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(other) == 1
        assert other[0]["skill_level_title"] == "Advanced"
        assert other[0]["percent"] == 70

    async def test_only_lower_level_assessment_surfaces_in_other(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # HRP-217: assessment reached only Basic, required is
        # Intermediate. Current slot stays a dash, but Other now surfaces
        # the lower-level result the employee actually has -- otherwise
        # changing the position to a higher grade would silently erase
        # the existing evidence.
        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 95,
                    }
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_row = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp A"
        )
        assert comp_a_row["percent"] is None
        assert comp_a_row["level_breakdown"] == []
        other = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(other) == 1
        assert other[0]["skill_level_title"] == "Basic"
        assert other[0]["percent"] == 95
        assert other[0]["assessment_id"] == a.id

    async def test_other_keeps_lower_level_when_current_unfilled(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Comp B is required at Advanced. A Done assessment touched Comp B
        # at Intermediate. HRP-217: Current shows no result (no Advanced
        # assessment), but Other surfaces the Intermediate row so the
        # employee's existing evidence isn't hidden.
        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a.id: {
                competence_setup["comp_b"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 90,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 70,
                    },
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_b_row = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp B"
        )
        # No Intermediate-targeted assessment fills the Advanced
        # requirement -- Current stays empty.
        assert comp_b_row["percent"] is None
        # ...but Other now exposes the Intermediate result.
        other = [r for r in result["other"] if r["competence_title"] == "Comp B"]
        assert len(other) == 1
        assert other[0]["skill_level_title"] == "Intermediate"
        assert other[0]["percent"] == 80  # avg(90, 70)

    async def test_other_includes_higher_level_overload_from_current(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Comp A is required at Intermediate. Two Done assessments exist:
        # one targeted Intermediate (Current row), one targeted Advanced
        # (overload). Reporter Q4b: keep the Advanced row in Other.
        first = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        second = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            first.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 90,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 80,
                    },
                ]
            },
            second.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 60,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 50,
                    },
                    {
                        "skill_level_id": competence_setup["advanced"].id,
                        "skill_level_title": "Advanced",
                        "sort_index": 2,
                        "percent": 40,
                    },
                ]
            },
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_current = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp A"
        )
        # Current row picks the later (Advanced) assessment since its
        # target meets/exceeds the Intermediate requirement. Result =
        # avg(60, 50) = 55 (avg over rows up to Intermediate).
        assert comp_a_current["assessment_id"] == second.id
        assert comp_a_current["percent"] == 55
        # Other lists Comp A @ Advanced (highest assessed level) from the
        # same overloading assessment, percent = avg(60, 50, 40) = 50.
        other = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(other) == 1
        assert other[0]["skill_level_title"] == "Advanced"
        assert other[0]["percent"] == 50
        # Breakdown payload is the three-row cascade so the (i) popup
        # can render Skill level / Percent table rows.
        assert [r["skill_level_title"] for r in other[0]["level_breakdown"]] == [
            "Basic",
            "Intermediate",
            "Advanced",
        ]

    async def test_latest_done_wins_for_other_block(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # Two Done assessments target Comp A at Advanced (overload above
        # the Intermediate requirement). The later one scored worse but
        # is still the source of truth per Reporter Task 2.2.
        first = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        second = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        higher_breakdown_first = [
            {
                "skill_level_id": competence_setup["basic"].id,
                "skill_level_title": "Basic",
                "sort_index": 0,
                "percent": 95,
            },
            {
                "skill_level_id": competence_setup["intermediate"].id,
                "skill_level_title": "Intermediate",
                "sort_index": 1,
                "percent": 90,
            },
            {
                "skill_level_id": competence_setup["advanced"].id,
                "skill_level_title": "Advanced",
                "sort_index": 2,
                "percent": 85,
            },
        ]
        higher_breakdown_second = [
            {
                "skill_level_id": competence_setup["basic"].id,
                "skill_level_title": "Basic",
                "sort_index": 0,
                "percent": 50,
            },
            {
                "skill_level_id": competence_setup["intermediate"].id,
                "skill_level_title": "Intermediate",
                "sort_index": 1,
                "percent": 40,
            },
            {
                "skill_level_id": competence_setup["advanced"].id,
                "skill_level_title": "Advanced",
                "sort_index": 2,
                "percent": 30,
            },
        ]
        per_assessment_rows = {
            first.id: {competence_setup["comp_a"].id: higher_breakdown_first},
            second.id: {competence_setup["comp_a"].id: higher_breakdown_second},
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        other = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(other) == 1
        # Latest Done assessment wins -> avg(50, 40, 30) = 40.
        assert other[0]["assessment_id"] == second.id
        assert other[0]["percent"] == 40

    async def test_other_groups_to_one_row_per_competence(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # REDO 1.2.a: even with multiple Done assessments at different
        # levels for the same competence, Other shows exactly one row at
        # the highest assessed level not covered by Current.
        from sqlalchemy import delete

        await db.execute(
            delete(GradeCompetenceLink).where(
                GradeCompetenceLink.competence_id == competence_setup["comp_a"].id
            )
        )
        await db.commit()

        a1 = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
        a2 = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
        )
        per_assessment_rows = {
            a1.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 80,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 70,
                    },
                ]
            },
            a2.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 60,
                    }
                ]
            },
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_rows = [r for r in result["other"] if r["competence_title"] == "Comp A"]
        assert len(comp_a_rows) == 1
        # Highest assessed target is Intermediate from a1; row percent =
        # avg(80, 70) = 75.
        assert comp_a_rows[0]["skill_level_title"] == "Intermediate"
        assert comp_a_rows[0]["assessment_id"] == a1.id
        assert comp_a_rows[0]["percent"] == 75

    async def test_assessment_completion_fallback(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
        monkeypatch,
    ):
        # finished_at can be null on legacy rows -- the "latest" selection
        # falls back to ended_at then updated_at so the row still
        # populates deterministically.
        a = await _make_assessment(
            db,
            tenant,
            employee_with_position,
            done_status,
            completed_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
        )
        a.finished_at = None
        a.ended_at = None
        await db.commit()
        await db.refresh(a)
        assert a.updated_at is not None
        assert a.updated_at > datetime(2020, 1, 1, tzinfo=timezone.utc) - timedelta(
            days=1
        )

        per_assessment_rows = {
            a.id: {
                competence_setup["comp_a"].id: [
                    {
                        "skill_level_id": competence_setup["basic"].id,
                        "skill_level_title": "Basic",
                        "sort_index": 0,
                        "percent": 80,
                    },
                    {
                        "skill_level_id": competence_setup["intermediate"].id,
                        "skill_level_title": "Intermediate",
                        "sort_index": 1,
                        "percent": 60,
                    },
                ]
            }
        }
        monkeypatch.setattr(
            "app.modules.assessment.breakdown_service.compute_per_level_breakdowns_batch",
            _stub_breakdown(per_assessment_rows=per_assessment_rows),
        )
        result = await compute_competence_overview(
            db, tenant.id, employee_with_position
        )
        comp_a_row = next(
            r for r in result["current_position"] if r["competence_title"] == "Comp A"
        )
        # avg(80, 60) = 70
        assert comp_a_row["percent"] == 70
        assert comp_a_row["assessment_id"] == a.id


class TestQueryCounts:
    async def test_batched_overview_stays_constant_under_many_assessments(
        self,
        db: AsyncSession,
        tenant,
        employee_with_position,
        competence_setup,
        done_status,
    ):
        """HRP-153 review: previously ``compute_competence_overview`` issued
        ~5 SQL statements per Done assessment via the single-shot breakdown
        helper. 10 assessments -> 50+ statements just for the page render.
        The batched path collapses that into a bounded set regardless of
        input size."""
        from sqlalchemy import event

        for i in range(10):
            await _make_assessment(
                db,
                tenant,
                employee_with_position,
                done_status,
                completed_at=datetime(2024, 1 + i % 12, 1, tzinfo=timezone.utc),
            )

        bind = db.get_bind()
        sync_engine = getattr(bind, "sync_engine", bind)
        executed: list[str] = []

        def _on_exec(conn, cursor, statement, parameters, context, executemany):
            executed.append(statement)

        event.listen(sync_engine, "before_cursor_execute", _on_exec)
        try:
            await compute_competence_overview(
                db, tenant.id, employee_with_position
            )
        finally:
            event.remove(sync_engine, "before_cursor_execute", _on_exec)

        # Empirically the batched path executes ~10-12 statements for this
        # fixture; well under 25 leaves headroom for harmless future
        # additions while still failing if a per-assessment loop sneaks back.
        assert len(executed) < 25, (
            f"Competence Overview must batch SQL -- got {len(executed)} statements "
            f"for 10 assessments. Last few: {executed[-5:]}"
        )
