"""HRP-255 (D7) — cross-tenant isolation sweep.

Pins the regression contract that every tenant-scoped read function in
the core read paths refuses to return data from another tenant. The
existing ``test_demo_analytics_isolation.py`` pins the same invariant
just for ``analytics_service.assessment_stats`` — this file widens the
sweep to recruitment, assessment, employee, dictionary, competence,
position, grade-system and talent-market.

Shape:

* Two complete tenants are built once per test module: tenant A is a
  normal paying tenant, tenant B is flagged ``is_demo=True``. Each
  carries one row of every entity we read so a leaking query has
  something visible to return.
* Each test calls a single service-level read function with tenant A's
  id and asserts the row it gets back is A's, not B's. The symmetric
  call (tenant B sees only B) is exercised on the same fixture to keep
  the suite short — one assertion per direction would double the row
  count without adding regression coverage.
* Service-level calls (not HTTP) because the leak we're guarding
  against lives in the SQL WHERE clauses; routing layer scoping is
  covered by the existing auth tests.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.analytics import service as analytics_service
from app.modules.assessment import service as assessment_service
from app.modules.assessment.models import (
    Assessment,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.competence import service as competence_service
from app.modules.competence.models import Competence, CompetenceGroup
from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from app.modules.grade_system import service as grade_service
from app.modules.grade_system.models import GradeSpecialization
from app.modules.position import service as position_service
from app.modules.position.models import Position
from app.modules.recruitment import service as recruitment_service
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
)
from app.modules.talent_market import service as talent_market_service
from app.modules.talent_market.models import TalentCard
from app.modules.talent_market.schemas import SearchRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


async def _ensure_admin_role(db: AsyncSession) -> Role:
    existing = (
        await db.execute(
            select(Role).where(Role.code == "admin", Role.is_system.is_(True))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    role = Role(name="Admin", code="admin", is_system=True)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


async def _ensure_assessment_status(db: AsyncSession, code: str) -> AssessmentStatus:
    existing = (
        await db.execute(select(AssessmentStatus).where(AssessmentStatus.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    s = AssessmentStatus(code=code, title=code.title(), sequence=0)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _ensure_assessment_type(db: AsyncSession, code: str) -> AssessmentType:
    existing = (
        await db.execute(select(AssessmentType).where(AssessmentType.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    t = AssessmentType(code=code, title=code.title())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


class TenantWorld:
    """Container for one tenant's data, populated by ``_make_world``."""

    def __init__(self) -> None:
        self.tenant: Tenant | None = None
        self.user: User | None = None
        self.employee: Employee | None = None
        self.position: Position | None = None
        self.spec_item: DictionaryItem | None = None
        self.grade_item: DictionaryItem | None = None
        self.competence_group: CompetenceGroup | None = None
        self.competence: Competence | None = None
        self.dictionary_item: DictionaryItem | None = None
        self.vacancy: Vacancy | None = None
        self.candidate: Candidate | None = None
        self.candidate_vacancy: CandidateVacancy | None = None
        self.interview: Interview | None = None
        self.grade_specialization: GradeSpecialization | None = None
        self.talent_card: TalentCard | None = None
        self.assessment: Assessment | None = None


async def _make_world(
    db: AsyncSession,
    *,
    is_demo: bool,
    role: Role,
    status: AssessmentStatus,
    a_type: AssessmentType,
) -> TenantWorld:
    """Spin up a fully-populated tenant: one row of every entity used
    by the sweep. Uses ``uuid.uuid4().hex[:6]`` suffixes so two side-by-
    side tenants don't collide on uniqueness constraints (slug,
    position title, candidate email).
    """
    w = TenantWorld()
    suffix = uuid.uuid4().hex[:6]
    label = "demo" if is_demo else "paid"

    # Tenant + admin user
    w.tenant = Tenant(
        id=uuid.uuid4(),
        name=f"{label}-{suffix}",
        slug=f"{label}-{suffix}",
        is_demo=is_demo,
    )
    db.add(w.tenant)
    await db.flush()

    w.user = User(
        id=uuid.uuid4(),
        email=f"{label}-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name=label.title(),
        last_name="Owner",
        tenant_id=w.tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(w.user)
    await db.flush()
    await db.execute(
        user_roles.insert().values(user_id=w.user.id, role_id=role.id)
    )

    # Dictionary items: spec + grade (drive Position FKs) + a custom one
    # used directly by the dictionary list endpoint.
    w.spec_item = DictionaryItem(
        type="specialization",
        tenant_id=w.tenant.id,
        title=f"{label}-spec-{suffix}",
        sort_index=0,
    )
    w.grade_item = DictionaryItem(
        type="grade",
        tenant_id=w.tenant.id,
        title=f"{label}-grade-{suffix}",
        sort_index=0,
    )
    w.dictionary_item = DictionaryItem(
        type="role",
        tenant_id=w.tenant.id,
        title=f"{label}-role-{suffix}",
        sort_index=0,
    )
    db.add_all([w.spec_item, w.grade_item, w.dictionary_item])
    await db.flush()

    # Position
    w.position = Position(
        tenant_id=w.tenant.id,
        title=f"{label}-position-{suffix}",
        source="manual",
        specialization_id=w.spec_item.id,
        grade_id=w.grade_item.id,
    )
    db.add(w.position)
    await db.flush()

    # Employee (linked to the admin user + position)
    w.employee = Employee(
        user_id=w.user.id,
        tenant_id=w.tenant.id,
        position_id=w.position.id,
        position_title=w.position.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(w.employee)
    await db.flush()

    # Tenant-scoped competence group + competence (custom, not origin)
    w.competence_group = CompetenceGroup(
        title=f"{label}-cg-{suffix}",
        tenant_id=w.tenant.id,
    )
    db.add(w.competence_group)
    await db.flush()
    w.competence = Competence(
        title=f"{label}-comp-{suffix}",
        group_id=w.competence_group.id,
        tenant_id=w.tenant.id,
    )
    db.add(w.competence)
    await db.flush()

    # Grade-spec chain (tenant-scoped)
    w.grade_specialization = GradeSpecialization(
        tenant_id=w.tenant.id,
        grade_id=w.grade_item.id,
        specialization_id=w.spec_item.id,
        sort_index=0,
    )
    db.add(w.grade_specialization)
    await db.flush()

    # Vacancy + Candidate + CandidateVacancy + Interview
    w.vacancy = Vacancy(
        tenant_id=w.tenant.id,
        title=f"{label}-vac-{suffix}",
        status="open",
    )
    db.add(w.vacancy)
    await db.flush()

    w.candidate = Candidate(
        tenant_id=w.tenant.id,
        full_name=f"{label.title()} Candidate {suffix}",
        email=f"cand-{label}-{suffix}@example.com",
        source="manual",
    )
    db.add(w.candidate)
    await db.flush()

    w.candidate_vacancy = CandidateVacancy(
        tenant_id=w.tenant.id,
        candidate_id=w.candidate.id,
        vacancy_id=w.vacancy.id,
        status="new",
    )
    db.add(w.candidate_vacancy)
    await db.flush()

    w.interview = Interview(
        tenant_id=w.tenant.id,
        candidate_vacancy_id=w.candidate_vacancy.id,
        type="initial",
        status="scheduled",
        analysis_status="pending",
    )
    db.add(w.interview)
    await db.flush()

    # Talent-market card
    w.talent_card = TalentCard(
        tenant_id=w.tenant.id,
        title=f"{label}-tc-{suffix}",
        card_type="vacancy",
        author_id=w.user.id,
        start_date=date(2024, 1, 15),
    )
    db.add(w.talent_card)
    await db.flush()

    # Assessment (also pinned by the analytics test, included so the
    # assessment service-level read funcs can be sweeped here too).
    w.assessment = Assessment(
        tenant_id=w.tenant.id,
        title=f"{label}-assess-{suffix}",
        employee_id=w.employee.id,
        type_id=a_type.id,
        status_id=status.id,
        initiator_id=w.user.id,
    )
    db.add(w.assessment)
    await db.commit()

    return w


@pytest_asyncio.fixture
async def worlds(db: AsyncSession):
    """Build tenant A (paid) and tenant B (demo) side-by-side."""
    role = await _ensure_admin_role(db)
    status = await _ensure_assessment_status(db, "done")
    a_type = await _ensure_assessment_type(db, "self")
    a = await _make_world(
        db, is_demo=False, role=role, status=status, a_type=a_type
    )
    b = await _make_world(
        db, is_demo=True, role=role, status=status, a_type=a_type
    )
    return a, b


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_assessment_stats_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    stats_paid = await analytics_service.assessment_stats(db, paid.tenant.id)
    stats_demo = await analytics_service.assessment_stats(db, demo.tenant.id)
    # Each tenant has exactly its own one assessment, regardless of which
    # bucket the other tenant lives in.
    assert stats_paid["total"] == 1
    assert stats_demo["total"] == 1


# ---------------------------------------------------------------------------
# Recruitment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recruitment_list_vacancies_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    items, total = await recruitment_service.list_vacancies(db, paid.tenant.id)
    assert total == 1
    assert {row["id"] for row in items} == {paid.vacancy.id}

    items_b, total_b = await recruitment_service.list_vacancies(
        db, demo.tenant.id
    )
    assert total_b == 1
    assert {row["id"] for row in items_b} == {demo.vacancy.id}


@pytest.mark.asyncio
async def test_recruitment_list_candidates_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    items, total = await recruitment_service.list_candidates(db, paid.tenant.id)
    assert total == 1
    assert {row["id"] for row in items} == {paid.candidate.id}

    items_b, total_b = await recruitment_service.list_candidates(
        db, demo.tenant.id
    )
    assert total_b == 1
    assert {row["id"] for row in items_b} == {demo.candidate.id}


@pytest.mark.asyncio
async def test_recruitment_get_vacancy_404_across_tenants(
    db: AsyncSession, worlds
):
    """Fetching tenant B's vacancy id while scoped to tenant A must 404
    rather than expose the row — proves ``get_vacancy`` joins on
    ``tenant_id`` as well as ``id``."""
    from fastapi import HTTPException

    paid, demo = worlds
    with pytest.raises(HTTPException) as exc:
        await recruitment_service.get_vacancy(
            db, paid.tenant.id, demo.vacancy.id
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assessment_list_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    items, total = await assessment_service.list_assessments(db, paid.tenant.id)
    assert total == 1
    assert {row["id"] for row in items} == {paid.assessment.id}

    items_b, total_b = await assessment_service.list_assessments(
        db, demo.tenant.id
    )
    assert total_b == 1
    assert {row["id"] for row in items_b} == {demo.assessment.id}


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_employee_list_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    items, total = await employee_service.list_employees(db, paid.tenant.id)
    assert total == 1
    assert {row["id"] for row in items} == {paid.employee.id}

    items_b, total_b = await employee_service.list_employees(
        db, demo.tenant.id
    )
    assert total_b == 1
    assert {row["id"] for row in items_b} == {demo.employee.id}


# ---------------------------------------------------------------------------
# Competence (custom = tenant-scoped subset of the tree)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_competence_tree_only_returns_own_tenant_custom_groups(
    db: AsyncSession, worlds
):
    """``get_competence_tree`` ORs ``tenant_id == X`` with
    ``tenant_id IS NULL`` (origin). Tenant A must not see tenant B's
    custom group; both must see whatever origin rows exist (none in
    this fixture)."""
    paid, demo = worlds
    tree_paid = await competence_service.get_competence_tree(db, paid.tenant.id)
    tree_demo = await competence_service.get_competence_tree(db, demo.tenant.id)
    # ``get_competence_tree`` returns a list of ``CompetenceGroupTree``
    # Pydantic models, not dicts — attribute access, not subscript.
    group_ids_paid = {g.id for g in tree_paid}
    group_ids_demo = {g.id for g in tree_demo}
    assert paid.competence_group.id in group_ids_paid
    assert demo.competence_group.id not in group_ids_paid
    assert demo.competence_group.id in group_ids_demo
    assert paid.competence_group.id not in group_ids_demo


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dictionary_list_items_excludes_other_tenant(
    db: AsyncSession, worlds
):
    """``list_items`` ORs ``tenant_id == X`` with ``tenant_id IS NULL``
    (origin). Tenant A must never see tenant B's custom role."""
    paid, demo = worlds
    items_paid = await dictionary_service.list_items(db, paid.tenant.id, "role")
    items_demo = await dictionary_service.list_items(db, demo.tenant.id, "role")
    ids_paid = {item["id"] for item in items_paid}
    ids_demo = {item["id"] for item in items_demo}
    assert paid.dictionary_item.id in ids_paid
    assert demo.dictionary_item.id not in ids_paid
    assert demo.dictionary_item.id in ids_demo
    assert paid.dictionary_item.id not in ids_demo


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_position_list_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    items, total = await position_service.list_positions(db, paid.tenant.id)
    assert total == 1
    assert {row["id"] for row in items} == {paid.position.id}

    items_b, total_b = await position_service.list_positions(
        db, demo.tenant.id
    )
    assert total_b == 1
    assert {row["id"] for row in items_b} == {demo.position.id}


# ---------------------------------------------------------------------------
# Grade-system
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_system_list_by_specialization_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    chains_paid = await grade_service.list_by_specialization(
        db, paid.tenant.id, paid.spec_item.id
    )
    # Tenant A scoped to A's specialization sees A's chain only.
    assert {row["id"] for row in chains_paid} == {paid.grade_specialization.id}

    # Tenant A asking for tenant B's specialization id finds no rows —
    # the tenant_id predicate would already be enough, but the dedicated
    # specialization_id filter doubles the safety net.
    chains_cross = await grade_service.list_by_specialization(
        db, paid.tenant.id, demo.spec_item.id
    )
    assert chains_cross == []

    chains_demo = await grade_service.list_by_specialization(
        db, demo.tenant.id, demo.spec_item.id
    )
    assert {row["id"] for row in chains_demo} == {demo.grade_specialization.id}


# ---------------------------------------------------------------------------
# Talent market
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talent_market_search_cards_excludes_other_tenant(
    db: AsyncSession, worlds
):
    paid, demo = worlds
    req = SearchRequest()
    items_paid, total_paid = await talent_market_service.search_cards(
        db, paid.tenant.id, req
    )
    assert total_paid == 1
    assert {row["id"] for row in items_paid} == {paid.talent_card.id}

    items_demo, total_demo = await talent_market_service.search_cards(
        db, demo.tenant.id, req
    )
    assert total_demo == 1
    assert {row["id"] for row in items_demo} == {demo.talent_card.id}
