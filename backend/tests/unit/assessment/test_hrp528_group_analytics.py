"""HRP-528: aggregation behind the mass-assessment Analytics block.

Two layers are covered:

* the pure aggregation helpers (competence averages, growth/top split,
  display rounding) — cheap tests that pin the spec's edge cases;
* ``get_group_analytics`` against the database — status filtering (only
  ``done`` children count), the empty-group contract and tenant/404
  fencing.

The per-competence percents themselves are not recomputed here: they come
from the ``AssessmentResult`` rows that HRP-62 already covers.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.assessment.group_analytics import (
    _competence_averages,
    _round_half_up,
    _split_highlights,
    get_group_analytics,
)
from app.modules.assessment.models import (
    Assessment,
    AssessmentGroup,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User as AuthUser
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


# --- helpers ---------------------------------------------------------------


def _employee_row(*competences: tuple[uuid.UUID, int | None]) -> dict:
    """Minimal employee payload shape the aggregation helpers consume."""
    return {
        "competences": [
            {"competence_id": cid, "percent": percent} for cid, percent in competences
        ]
    }


def _average(averages: list[dict], competence_id: uuid.UUID) -> int | None:
    for row in averages:
        if row["competence_id"] == competence_id:
            return row["percent"]
    return None


async def _make_employee(db: AsyncSession, tenant, suffix: str) -> Employee:
    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.flush()

    user = AuthUser(
        email=f"hrp528-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"First{suffix}",
        last_name=f"Last{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _make_competence(db: AsyncSession, tenant, title: str) -> uuid.UUID:
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"Grp-{uuid.uuid4().hex[:6]}")
    )
    comp = await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=title, group_id=group.id)
    )
    return comp.id


async def _make_group(
    db: AsyncSession, tenant, user, *, criteria_type: str = "current_positions"
) -> AssessmentGroup:
    group = AssessmentGroup(
        tenant_id=tenant.id,
        title=f"Wave-{uuid.uuid4().hex[:6]}",
        initiator_id=user.id,
        criteria_type=criteria_type,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def _add_child(
    db: AsyncSession,
    tenant,
    user,
    group: AssessmentGroup,
    employee: Employee,
    status_code: str,
    results: list[tuple[uuid.UUID, int | None]],
) -> Assessment:
    status_id = (
        await db.execute(
            select(AssessmentStatus.id).where(AssessmentStatus.code == status_code)
        )
    ).scalar_one()
    type_id = (
        await db.execute(select(AssessmentType.id).where(AssessmentType.code == "self"))
    ).scalar_one()

    assessment = Assessment(
        tenant_id=tenant.id,
        title=f"Child-{uuid.uuid4().hex[:6]}",
        employee_id=employee.id,
        type_id=type_id,
        status_id=status_id,
        initiator_id=user.id,
        group_id=group.id,
        criteria_type=group.criteria_type,
    )
    db.add(assessment)
    await db.flush()
    for competence_id, percent in results:
        db.add(
            AssessmentResult(
                assessment_id=assessment.id,
                competence_id=competence_id,
                avg_score=0.0 if percent is None else percent / 100,
                percent=percent,
            )
        )
    await db.commit()
    await db.refresh(assessment)
    return assessment


async def _add_participant(
    db: AsyncSession, assessment: Assessment, user_id: uuid.UUID, role: str
) -> None:
    """Attach a respondent — the second arm of the HRP-40 scope predicate."""
    db.add(
        AssessmentParticipant(
            assessment_id=assessment.id,
            user_id=user_id,
            role=role,
            is_completed=True,
        )
    )
    await db.commit()


# --- pure aggregation ------------------------------------------------------


class TestDisplayRounding:
    async def test_rounds_half_away_from_zero(self):
        # Python's round() is banker's: round(74.5) == 74. The spec asks for
        # school rules, so .5 must climb.
        assert _round_half_up(74.5) == 75
        assert _round_half_up(74.4) == 74
        assert _round_half_up(0.5) == 1
        assert _round_half_up(99.99) == 100


class TestCompetenceAverages:
    async def test_repeated_competence_is_averaged_ignoring_skill_levels(self):
        # Straight out of the spec: employee 1 at 100% (Basic), employee 2 at
        # 50% (Intermediate) => the competence reads 75%.
        comp = uuid.uuid4()
        averages = _competence_averages(
            [_employee_row((comp, 100)), _employee_row((comp, 50))],
            {comp: "Competence A"},
        )
        assert _average(averages, comp) == 75

    async def test_competence_held_by_one_employee_keeps_that_value(self):
        comp = uuid.uuid4()
        averages = _competence_averages(
            [_employee_row((comp, 42))], {comp: "Competence A"}
        )
        assert _average(averages, comp) == 42

    async def test_dont_know_employees_leave_the_divisor_alone(self):
        # A None percent means "all Don't know" — it must not be read as 0,
        # which would drag the average from 100 down to 50.
        comp = uuid.uuid4()
        averages = _competence_averages(
            [_employee_row((comp, 100)), _employee_row((comp, None))],
            {comp: "Competence A"},
        )
        assert _average(averages, comp) == 100

    async def test_competence_without_any_value_is_dropped(self):
        comp = uuid.uuid4()
        averages = _competence_averages(
            [_employee_row((comp, None))], {comp: "Competence A"}
        )
        assert averages == []

    async def test_no_employees_yields_no_averages(self):
        assert _competence_averages([], {}) == []

    async def test_average_is_math_rounded(self):
        comp = uuid.uuid4()
        # mean(74, 75) == 74.5 -> 75 by school rules
        averages = _competence_averages(
            [_employee_row((comp, 74)), _employee_row((comp, 75))],
            {comp: "Competence A"},
        )
        assert _average(averages, comp) == 75

    async def test_titles_are_attached(self):
        comp = uuid.uuid4()
        averages = _competence_averages(
            [_employee_row((comp, 80))], {comp: "Working with software"}
        )
        assert averages[0]["competence_title"] == "Working with software"


class TestGrowthAndTopSplit:
    def _avg(self, percent: int, title: str = "C") -> dict:
        return {
            "competence_id": uuid.uuid4(),
            "competence_title": title,
            "percent": percent,
        }

    async def test_seventy_five_is_a_growth_zone_not_a_top_competence(self):
        # "below 75 inclusive" on one side, "above 75" on the other — 75
        # itself belongs to growth zones and the two lists never overlap.
        growth, top = _split_highlights([self._avg(75), self._avg(76)])
        assert [g["percent"] for g in growth] == [75]
        assert [t["percent"] for t in top] == [76]

    async def test_growth_zones_are_worst_first(self):
        growth, _ = _split_highlights([self._avg(70), self._avg(20), self._avg(50)])
        assert [g["percent"] for g in growth] == [20, 50, 70]

    async def test_growth_zones_are_capped_at_ten(self):
        growth, _ = _split_highlights([self._avg(p) for p in range(1, 30)])
        assert len(growth) == 10
        assert [g["percent"] for g in growth] == list(range(1, 11))

    async def test_top_competences_are_best_first_and_uncapped(self):
        _, top = _split_highlights([self._avg(80), self._avg(100), self._avg(90)])
        assert [t["percent"] for t in top] == [100, 90, 80]

    async def test_ties_break_by_title(self):
        growth, _ = _split_highlights([self._avg(40, "Zebra"), self._avg(40, "Alpha")])
        assert [g["competence_title"] for g in growth] == ["Alpha", "Zebra"]

    async def test_empty_input_hides_both_blocks(self):
        growth, top = _split_highlights([])
        assert growth == []
        assert top == []


# --- endpoint-level aggregation -------------------------------------------


class TestGroupAnalytics:
    async def test_all_children_cancelled_yields_empty_analytics(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "cancel1")
        await _add_child(db, tenant, user, group, emp, "cancelled", [(comp, 90)])

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["done_count"] == 0
        assert data["excluded_count"] == 1
        assert data["employees"] == []
        assert data["growth_zones"] == []
        assert data["top_competences"] == []

    async def test_only_done_children_feed_the_numbers(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        done_emp = await _make_employee(db, tenant, "done1")
        cancelled_emp = await _make_employee(db, tenant, "cancelled1")
        inflight_emp = await _make_employee(db, tenant, "inflight1")

        await _add_child(db, tenant, user, group, done_emp, "done", [(comp, 40)])
        # A cancelled child at 100% would flip the competence into the top
        # block if it leaked into the aggregation.
        await _add_child(
            db, tenant, user, group, cancelled_emp, "cancelled", [(comp, 100)]
        )
        await _add_child(
            db, tenant, user, group, inflight_emp, "in_progress", [(comp, 100)]
        )

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["done_count"] == 1
        assert data["excluded_count"] == 2
        assert [e["employee_id"] for e in data["employees"]] == [done_emp.id]
        assert data["employees"][0]["percent"] == 40
        assert [g["percent"] for g in data["growth_zones"]] == [40]
        assert data["top_competences"] == []

    async def test_employee_overall_is_the_mean_of_competences(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp_a = await _make_competence(db, tenant, "Competence A")
        comp_b = await _make_competence(db, tenant, "Competence B")
        emp = await _make_employee(db, tenant, "mean1")
        await _add_child(
            db, tenant, user, group, emp, "done", [(comp_a, 80), (comp_b, 40)]
        )

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["employees"][0]["percent"] == 60
        assert data["employees"][0]["all_dont_know"] is False

    async def test_all_dont_know_employee_is_listed_but_not_averaged(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        scored = await _make_employee(db, tenant, "scored1")
        unknown = await _make_employee(db, tenant, "unknown1")
        await _add_child(db, tenant, user, group, scored, "done", [(comp, 90)])
        await _add_child(db, tenant, user, group, unknown, "done", [(comp, None)])

        data = await get_group_analytics(db, tenant.id, group.id)

        by_employee = {e["employee_id"]: e for e in data["employees"]}
        assert len(by_employee) == 2
        # Still visible in the matrix …
        assert by_employee[unknown.id]["percent"] is None
        assert by_employee[unknown.id]["all_dont_know"] is True
        # … but the competence average is the scored employee's value alone.
        assert [t["percent"] for t in data["top_competences"]] == [90]

    async def test_child_without_result_rows_is_not_called_all_dont_know(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        """No result rows is "no result", not "answered Don't know".

        Both collapse to ``percent is None``, but the matrix legend reads
        ``all_dont_know`` as a statement about the answers — a child that never
        got criteria (or had its results wiped) has no answers to describe.
        """
        group = await _make_group(db, tenant, user)
        emp = await _make_employee(db, tenant, "no-results")
        await _add_child(db, tenant, user, group, emp, "done", [])

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["done_count"] == 1
        assert data["employees"][0]["percent"] is None
        assert data["employees"][0]["all_dont_know"] is False
        assert data["employees"][0]["competences"] == []

    async def test_all_dont_know_employee_has_no_grade_percents(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
        monkeypatch,
    ):
        """An all-"Don't know" assessee must not report a 0% grade match.

        HRP-170 feeds a competence with no usable answers into the grade
        average as 0% and leaves the row non-excluded, so the raw matrix hands
        back ``percent=0.0, excluded=False`` for such an assessee. The
        analytics block has to null that out, otherwise the grade matrix shows
        a red 0% chip and every grade average is dragged down by someone who,
        by spec, is "displayed but not counted".
        """
        from app.modules.assessment import group_analytics as ga
        from app.modules.assessment.schemas import GradeRecommendationItem

        group = await _make_group(
            db, tenant, user, criteria_type="target_position"
        )
        assert group.grade_id is None  # "Target position: All grades"
        comp = await _make_competence(db, tenant, "Competence A")
        scored = await _make_employee(db, tenant, "grade-scored")
        unknown = await _make_employee(db, tenant, "grade-unknown")
        await _add_child(db, tenant, user, group, scored, "done", [(comp, 80)])
        await _add_child(db, tenant, user, group, unknown, "done", [(comp, None)])

        grade_id = uuid.uuid4()

        async def fake_grade_percents(db_, tenant_id_, assessment_, **kwargs):
            # What HRP-170 really returns for both assessees: a scored one and
            # an all-"Don't know" one collapse to the same non-excluded shape.
            percent = 80.0 if assessment_.employee_id == scored.id else 0.0
            return [
                GradeRecommendationItem(
                    grade_id=grade_id,
                    grade_title="Middle",
                    sort_index=1,
                    percent=percent,
                    passed=False,
                    missing_percent=None,
                    excluded=False,
                )
            ]

        monkeypatch.setattr(ga, "compute_grade_percents", fake_grade_percents)

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["is_all_grades"] is True
        by_employee = {e["employee_id"]: e for e in data["employees"]}
        # The scored assessee keeps their grade match …
        assert by_employee[scored.id]["grades"] == [
            {"grade_id": grade_id, "percent": 80}
        ]
        # … the all-"Don't know" one is listed with a blank, not a 0.
        assert by_employee[unknown.id]["all_dont_know"] is True
        assert by_employee[unknown.id]["grades"] == [
            {"grade_id": grade_id, "percent": None}
        ]

    async def test_repeated_competence_across_employees_is_averaged(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Shared competence")
        first = await _make_employee(db, tenant, "shared1")
        second = await _make_employee(db, tenant, "shared2")
        await _add_child(db, tenant, user, group, first, "done", [(comp, 100)])
        await _add_child(db, tenant, user, group, second, "done", [(comp, 50)])

        data = await get_group_analytics(db, tenant.id, group.id)

        assert [g["percent"] for g in data["growth_zones"]] == [75]
        assert data["top_competences"] == []
        assert data["competences"] == [
            {"competence_id": comp, "competence_title": "Shared competence"}
        ]

    async def test_current_positions_group_reports_no_grade_layout(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "layout1")
        await _add_child(db, tenant, user, group, emp, "done", [(comp, 60)])

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["is_all_grades"] is False
        assert data["criteria_type"] == "current_positions"
        assert data["grades"] == []
        assert data["employees"][0]["grades"] == []

    async def test_unknown_group_is_404(self, db: AsyncSession, tenant):
        with pytest.raises(AppError) as exc:
            await get_group_analytics(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_group_of_another_tenant_is_404(self, db: AsyncSession, tenant, user):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other tenant", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        group = await _make_group(db, tenant, user)

        with pytest.raises(AppError) as exc:
            await get_group_analytics(db, other.id, group.id)
        assert exc.value.status_code == 404

    async def test_scoped_caller_without_visible_children_is_404(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "scoped1")
        await _add_child(db, tenant, user, group, emp, "done", [(comp, 90)])

        # A manager whose subtree contains none of the assessees must not be
        # able to confirm the group exists.
        with pytest.raises(AppError) as exc:
            await get_group_analytics(
                db,
                tenant.id,
                group.id,
                visible_employee_ids=set(),
                participant_user_id=user.id,
            )
        assert exc.value.status_code == 404

    async def test_group_without_children_returns_empty_payload(
        self, db: AsyncSession, tenant, user
    ):
        group = await _make_group(db, tenant, user)

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["done_count"] == 0
        assert data["excluded_count"] == 0
        assert data["employees"] == []
        assert data["divisions"] == []
        assert data["specializations"] == []


# --- route-level access control -------------------------------------------
#
# The aggregation above is only as safe as the guard on the route that serves
# it: the payload carries every assessee's name, division and result, so an
# unscoped GET /assessment-groups/{id}/analytics would hand a regular employee
# the whole campaign even though GET /assessment-groups/{id} hides it. These
# tests pin the route to the same guard as the group-detail route
# (authentication + tenant + the HRP-40 scope predicate).


async def _token_for(db: AsyncSession, tenant, *, admin: bool) -> str:
    """Fresh user in ``tenant`` with or without the admin role, plus a token."""
    from app.core.security import create_access_token
    from app.modules.auth.models import Role, user_roles

    u = AuthUser(
        email=f"hrp528-acl-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Acl",
        last_name="Caller",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    if admin:
        role = (
            (
                await db.execute(
                    select(Role).where(
                        Role.code == "admin",
                        Role.is_system == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        assert role is not None
        await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
        await db.commit()

    return create_access_token(str(u.id), str(tenant.id))


class TestGroupAnalyticsRouteAccessControl:
    async def test_route_is_registered_under_the_group_prefix(self):
        from app.main import app

        paths = {
            getattr(route, "path", "")
            for route in app.routes
            if "GET" in (getattr(route, "methods", None) or set())
        }
        assert "/api/assessment-groups/{group_id}/analytics" in paths

    async def test_anonymous_caller_is_rejected(
        self, client, db: AsyncSession, tenant, user
    ):
        group = await _make_group(db, tenant, user)

        resp = await client.get(f"/api/assessment-groups/{group.id}/analytics")

        assert resp.status_code in (401, 403)

    async def test_admin_of_the_owning_tenant_gets_the_payload(
        self,
        client,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "acl-ok")
        await _add_child(db, tenant, user, group, emp, "done", [(comp, 80)])

        token = await _token_for(db, tenant, admin=True)
        resp = await client.get(
            f"/api/assessment-groups/{group.id}/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["done_count"] == 1
        assert len(body["employees"]) == 1

    async def test_admin_of_another_tenant_gets_404(
        self,
        client,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.company.models import Tenant

        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "acl-cross")
        await _add_child(db, tenant, user, group, emp, "done", [(comp, 80)])

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        token = await _token_for(db, other, admin=True)
        resp = await client.get(
            f"/api/assessment-groups/{group.id}/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Cross-tenant reads must not even confirm the group exists.
        assert resp.status_code == 404

    async def test_employee_outside_the_scope_gets_404(
        self,
        client,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        emp = await _make_employee(db, tenant, "acl-scoped")
        await _add_child(db, tenant, user, group, emp, "done", [(comp, 95)])

        # Same tenant, but no admin role and no Employee row: the scope helper
        # yields an empty visible set, so no child of the group is reachable.
        token = await _token_for(db, tenant, admin=False)
        resp = await client.get(
            f"/api/assessment-groups/{group.id}/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 404
        # The other assessee's result must not leak through the error body.
        assert "95" not in resp.text


# --- employee respondents (HRP-243 parity) ---------------------------------
#
# The scope predicate lets a child through on either arm: the assessee is in
# the caller's subtree, OR the caller is one of the respondents. The second arm
# is how a rank-and-file employee reaches a colleague's 360 questionnaire — and
# without the extra gate below it also handed them that colleague's name,
# avatar, division, overall percent and the full per-competence/per-grade
# breakdown, i.e. everything GET /assessments/{id}/results refuses to show them
# and more than GET /assessments/{id}/detailed-results even offers a non-admin.


class TestGroupAnalyticsRespondentVisibility:
    async def test_child_reached_only_as_a_respondent_is_dropped(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        viewer = await _make_employee(db, tenant, "respondent-self")
        colleague = await _make_employee(db, tenant, "respondent-peer")

        own_child = await _add_child(
            db, tenant, user, group, viewer, "done", [(comp, 40)]
        )
        colleague_child = await _add_child(
            db, tenant, user, group, colleague, "done", [(comp, 95)]
        )
        await _add_participant(db, own_child, viewer.user_id, "self")
        # The viewer answered the colleague's 360 — scope lets the child
        # through, the results must not follow it.
        await _add_participant(db, colleague_child, viewer.user_id, "peer")

        data = await get_group_analytics(
            db,
            tenant.id,
            group.id,
            visible_employee_ids={viewer.id},
            participant_user_id=viewer.user_id,
            restrict_to_active=True,
            hide_results_for_employee=True,
        )

        assert [e["employee_id"] for e in data["employees"]] == [viewer.id]
        assert data["employees"][0]["percent"] == 40
        # Counters must not confess to the hidden child either.
        assert data["done_count"] == 1
        assert data["excluded_count"] == 0
        # 95 would have flipped the competence into the top block.
        assert [g["percent"] for g in data["growth_zones"]] == [40]
        assert data["top_competences"] == []

    async def test_respondent_without_own_child_gets_an_empty_payload(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        """Reachable group, nothing to show: an empty payload, not a 404.

        The respondent legitimately sees the group itself (they answered one of
        its questionnaires), so the existence guard must stay silent — but the
        analytics have to come back blank.
        """
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        viewer = await _make_employee(db, tenant, "respondent-only")
        colleague = await _make_employee(db, tenant, "assessee-only")

        colleague_child = await _add_child(
            db, tenant, user, group, colleague, "done", [(comp, 95)]
        )
        await _add_participant(db, colleague_child, viewer.user_id, "peer")

        data = await get_group_analytics(
            db,
            tenant.id,
            group.id,
            visible_employee_ids={viewer.id},
            participant_user_id=viewer.user_id,
            restrict_to_active=True,
            hide_results_for_employee=True,
        )

        assert data["done_count"] == 0
        assert data["excluded_count"] == 0
        assert data["employees"] == []
        assert data["competences"] == []
        assert data["growth_zones"] == []
        assert data["top_competences"] == []

    async def test_manager_keeps_seeing_the_whole_wave(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        """The gate is off for admin/manager — HRP-528 aggregation intact."""
        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        first = await _make_employee(db, tenant, "mgr-scope1")
        second = await _make_employee(db, tenant, "mgr-scope2")
        await _add_child(db, tenant, user, group, first, "done", [(comp, 40)])
        await _add_child(db, tenant, user, group, second, "done", [(comp, 95)])

        data = await get_group_analytics(
            db,
            tenant.id,
            group.id,
            visible_employee_ids={first.id, second.id},
            participant_user_id=user.id,
            restrict_to_active=False,
            hide_results_for_employee=False,
        )

        assert data["done_count"] == 2
        assert {e["employee_id"] for e in data["employees"]} == {first.id, second.id}

    async def test_route_hides_colleague_results_from_an_employee_respondent(
        self,
        client,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        """End-to-end: the router has to pass the gate down, not just the scope."""
        from app.core.security import create_access_token

        group = await _make_group(db, tenant, user)
        comp = await _make_competence(db, tenant, "Competence A")
        viewer = await _make_employee(db, tenant, "routerespondent")
        colleague = await _make_employee(db, tenant, "routesecret")

        colleague_child = await _add_child(
            db, tenant, user, group, colleague, "done", [(comp, 95)]
        )
        await _add_participant(db, colleague_child, viewer.user_id, "peer")

        # Employee-only caller: an Employee row of their own, no admin role.
        token = create_access_token(str(viewer.user_id), str(tenant.id))
        resp = await client.get(
            f"/api/assessment-groups/{group.id}/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["done_count"] == 0
        assert body["excluded_count"] == 0
        assert body["employees"] == []
        assert body["competences"] == []
        # Neither the assessee's identity nor their score may appear anywhere.
        assert "Lastroutesecret" not in resp.text
        assert str(colleague.id) not in resp.text
        assert str(colleague_child.id) not in resp.text


# --- query budget ----------------------------------------------------------


class TestGroupAnalyticsGradeMatrixBatching:
    async def test_grade_scaffolding_is_loaded_once_per_wave(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
        monkeypatch,
    ):
        """The "All grades" matrix used to cost ~9 queries per child.

        compute_grade_percents re-read the whole grade/skill-level/indicator
        scaffolding for every assessee, so a 300-person wave issued ~2700
        queries. The lookups are now bulk-loaded once and handed to each call.
        """
        from app.modules.assessment import group_analytics as ga
        from app.modules.assessment.recommendation import GradeMatrixPrefetch

        group = await _make_group(db, tenant, user, criteria_type="target_position")
        comp = await _make_competence(db, tenant, "Competence A")
        for index in range(3):
            emp = await _make_employee(db, tenant, f"batch{index}")
            await _add_child(db, tenant, user, group, emp, "done", [(comp, 60)])

        loaded_batches: list[list] = []
        real_loader = ga.load_grade_matrix_prefetch

        async def counting_loader(db_, tenant_id_, assessments_):
            loaded_batches.append(list(assessments_))
            return await real_loader(db_, tenant_id_, assessments_)

        handed_prefetches: list[object] = []

        async def fake_grade_percents(db_, tenant_id_, assessment_, **kwargs):
            handed_prefetches.append(kwargs.get("prefetch"))
            return []

        monkeypatch.setattr(ga, "load_grade_matrix_prefetch", counting_loader)
        monkeypatch.setattr(ga, "compute_grade_percents", fake_grade_percents)

        data = await get_group_analytics(db, tenant.id, group.id)

        assert data["done_count"] == 3
        # One bulk load, covering every done child …
        assert len(loaded_batches) == 1
        assert len(loaded_batches[0]) == 3
        # … and the same instance reaches all three calls, so none of them
        # falls back to loading on its own.
        assert len(handed_prefetches) == 3
        assert all(isinstance(p, GradeMatrixPrefetch) for p in handed_prefetches)
        assert len({id(p) for p in handed_prefetches}) == 1
