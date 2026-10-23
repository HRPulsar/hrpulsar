"""HRP-1048 / HRP-1049: one rule for an employee's line manager.

The head of their division; a head of their own division (or an empty
seat) passes the question up the ``parent`` chain to the nearest assigned
head. The plan reviewer and the 180/360 ``manager`` participant both ask it.

Org used throughout::

    Root      (head: boss)
    └─ Child  (head: head)
       └─ Leaf (Not assigned) — worker
"""

import uuid
from datetime import date

import pytest_asyncio
from app.core.security import hash_password
from app.modules.assessment import pdp_service, service
from app.modules.assessment.models import Assessment, AssessmentParticipant
from app.modules.assessment.schemas import (
    AssessmentCreate,
    MassAssessmentCreate,
    PDPCreate,
)
from app.modules.auth.models import User
from app.modules.company.line_manager import resolve_line_manager
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee
from sqlalchemy import select


async def _person(db, tenant_id, name: str, division_id=None) -> Employee:
    u = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=name.capitalize(),
        last_name="Lm",
        tenant_id=tenant_id,
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        tenant_id=tenant_id,
        user_id=u.id,
        division_id=division_id,
        hire_date=date(2024, 1, 1),
        status="active",
    )
    db.add(emp)
    await db.flush()
    return emp


async def _division(db, tenant_id, name, *, parent=None, manager=None) -> Division:
    d = Division(
        tenant_id=tenant_id,
        name=name,
        parent_id=parent.id if parent else None,
        manager_id=manager.id if manager else None,
    )
    db.add(d)
    await db.flush()
    if manager is not None:
        manager.division_id = d.id
    return d


@pytest_asyncio.fixture
async def org(db, tenant):
    boss = await _person(db, tenant.id, "boss")
    head = await _person(db, tenant.id, "head")
    root = await _division(db, tenant.id, "Root", manager=boss)
    child = await _division(db, tenant.id, "Child", parent=root, manager=head)
    leaf = await _division(db, tenant.id, "Leaf", parent=child)
    worker = await _person(db, tenant.id, "worker", leaf.id)
    await db.commit()
    return {"boss": boss, "head": head, "worker": worker, "root": root}


async def _manager_participants(db, assessment_id) -> list[uuid.UUID]:
    rows = await db.execute(
        select(AssessmentParticipant.user_id).where(
            AssessmentParticipant.assessment_id == assessment_id,
            AssessmentParticipant.role == "manager",
        )
    )
    return list(rows.scalars())


class TestRule:
    async def test_head_of_own_division_gets_the_head_above(self, db, org):
        assert await resolve_line_manager(db, org["head"]) is org["boss"]

    async def test_not_assigned_seat_passes_up(self, db, org):
        assert await resolve_line_manager(db, org["worker"]) is org["head"]

    async def test_nobody_up_to_the_root(self, db, org):
        assert await resolve_line_manager(db, org["boss"]) is None

    async def test_no_division(self, db, tenant):
        loner = await _person(db, tenant.id, "loner")
        assert await resolve_line_manager(db, loner) is None

    async def test_a_cycle_in_the_hierarchy_ends(self, db, tenant):
        emp = await _person(db, tenant.id, "loop")
        a = await _division(db, tenant.id, "A", manager=emp)
        b = await _division(db, tenant.id, "B", parent=a)
        a.parent_id = b.id
        await db.flush()
        assert await resolve_line_manager(db, emp) is None

    async def test_never_crosses_into_another_tenant(self, db, tenant):
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.flush()
        stranger = await _person(db, other.id, "stranger")
        foreign = await _division(db, other.id, "Foreign", manager=stranger)
        emp = await _person(db, tenant.id, "local")
        await _division(db, tenant.id, "Local", parent=foreign, manager=emp)
        assert await resolve_line_manager(db, emp) is None


class TestPlanReviewer:
    async def test_head_gets_the_head_above_as_reviewer(self, db, tenant, user, org):
        pdp = await pdp_service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="P", employee_id=org["head"].id)
        )
        assert pdp["reviewer_name"] == "Boss Lm"

    async def test_root_head_stays_their_own_reviewer(self, db, tenant, user, org):
        pdp = await pdp_service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="P", employee_id=org["boss"].id)
        )
        assert pdp["reviewer_name"] == "Boss Lm"

    async def test_empty_seat_passes_the_review_up(self, db, tenant, user, org):
        pdp = await pdp_service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="P", employee_id=org["worker"].id)
        )
        assert pdp["reviewer_name"] == "Head Lm"


class TestAssessmentManager:
    async def test_head_gets_the_head_above(
        self, db, tenant, user, org, assessment_types, assessment_statuses
    ):
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="A", employee_id=org["head"].id, type_code="180"),
        )
        assert await _manager_participants(db, a["id"]) == [org["boss"].user_id]

    async def test_nobody_up_to_the_root_means_no_manager(
        self, db, tenant, user, org, assessment_types, assessment_statuses
    ):
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="A", employee_id=org["boss"].id, type_code="360"),
        )
        assert await _manager_participants(db, a["id"]) == []

    async def test_mass_creation_asks_the_same_rule(
        self, db, tenant, user, org, assessment_types, assessment_statuses
    ):
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="M",
                employee_ids=[org["head"].id, org["worker"].id],
                type_code="360",
            ),
        )
        rows = await db.execute(
            select(AssessmentParticipant.user_id, Employee.id)
            .join(
                Assessment,
                Assessment.id == AssessmentParticipant.assessment_id,
            )
            .join(Employee, Employee.id == Assessment.employee_id)
            .where(
                Assessment.group_id == group["id"],
                AssessmentParticipant.role == "manager",
            )
        )
        got = {emp_id: user_id for user_id, emp_id in rows.all()}
        assert got == {
            org["head"].id: org["boss"].user_id,
            org["worker"].id: org["head"].user_id,
        }
