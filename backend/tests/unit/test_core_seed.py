"""Characterization net for ``app.core.seed.populate_tenant`` (review [30]).

``populate_tenant`` is the shared tenant-population orchestration used by
``scripts/seed_demo.py`` (self-hosted) and ``ee/seed_saas.py`` (SaaS).
These tests pin its observable behaviour — per-table row counts and key
cross-references — so the step-by-step decomposition can be verified
against them. Counts mirror the static data blocks in ``app.core.seed``;
if you change the demo data on purpose, update the expected numbers here.

``ref_data`` is assembled from fixtures rather than ``fetch_ref_data`` on
purpose: ``populate_tenant`` only ever reads the passed-in maps, so a
curated ``ref_data`` keeps every count deterministic even when the shared
test DB carries origin rows left behind by other suites.

Nothing here commits — the seeded tenant rolls back with the session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import bcrypt
import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.core.seed import DIVISIONS_L1, DIVISIONS_L2, PEOPLE, populate_tenant
from app.modules.assessment.models import (
    PDP,
    AnswerOption,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
    AssessmentResult,
    PDPComment,
    PDPItem,
    PDPItemMaterial,
)
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division, SpecializationDivision, Tenant
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import (
    Compensation,
    Course,
    Education,
    Employee,
    EmployeeEvent,
    PreviousEmployment,
    WorkExperience,
)
from app.modules.exam.models import (
    Exam,
    ExamAnswer,
    ExamPassMark,
    ExamQuestion,
    MassExam,
    QuestionOption,
)
from app.modules.position.models import Position
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardCompetence,
    TalentCardRequirement,
    TalentCardSpecialization,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    """Drop bcrypt cost for the ~50 demo users the seed hashes."""
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda: real_gensalt(rounds=4))


@pytest_asyncio.fixture
async def system_roles(db: AsyncSession):
    """Get-or-create the three system roles the seed assigns.

    ``.first()`` for the same shared-test-DB reason as ``admin_role`` in
    conftest — other suites accumulate duplicate system roles.
    """
    roles = {}
    for code, name in (
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("employee", "Employee"),
    ):
        result = await db.execute(
            select(Role).where(Role.code == code, Role.is_system == True)  # noqa: E712
        )
        role = result.scalars().first()
        if not role:
            role = Role(name=name, code=code, is_system=True)
            db.add(role)
            await db.flush()
        roles[code] = role
    await db.commit()
    return roles


@pytest_asyncio.fixture
async def origin_specializations(db: AsyncSession):
    """Origin specializations the default demo data references by name."""
    titles = [
        "Backend Developer",
        "Frontend Developer",
        "QA Engineer",
        "DevOps Engineer",
    ]
    items = {}
    for i, title in enumerate(titles):
        result = await db.execute(
            select(DictionaryItem).where(
                DictionaryItem.tenant_id.is_(None),
                DictionaryItem.type == "specialization",
                DictionaryItem.title == title,
            )
        )
        item = result.scalars().first()
        if not item:
            item = DictionaryItem(
                tenant_id=None,
                type="specialization",
                title=title,
                sort_index=i,
                is_active=True,
            )
            db.add(item)
        items[title] = item
    await db.commit()
    return items


@pytest_asyncio.fixture
async def origin_comp_types(db: AsyncSession):
    items = {}
    for i, title in enumerate(["Hard skill", "Soft skill"]):
        result = await db.execute(
            select(DictionaryItem).where(
                DictionaryItem.tenant_id.is_(None),
                DictionaryItem.type == "competence_type",
                DictionaryItem.title == title,
            )
        )
        item = result.scalars().first()
        if not item:
            item = DictionaryItem(
                tenant_id=None,
                type="competence_type",
                title=title,
                sort_index=i,
                is_active=True,
            )
            db.add(item)
        items[title] = item
    await db.commit()
    return items


@pytest_asyncio.fixture
async def seed_scale(db: AsyncSession):
    """Dedicated (non-default) answer scale with the production 6 options.

    NOT the conftest ``default_answer_scale``: other suites
    (test_answer_scales) commit their own global default with a different
    option set, and there can be only one global default — so in a full run
    that fixture returns a scale whose shape this file can't rely on.
    ``populate_tenant`` only reads the scale passed via ``ref_data``, so a
    private flush-only scale keeps the counts deterministic. No commit —
    rolls back with the session.
    """
    from app.modules.assessment.models import AnswerScale

    scale = AnswerScale(
        title=f"Seed scale {uuid.uuid4().hex[:6]}",
        tenant_id=None,
        is_default=False,
    )
    db.add(scale)
    await db.flush()
    options = [
        ("not_observed", "Not observed", None, 0, True),
        ("never", "Never", 0, 1, False),
        ("rarely", "Rarely", 1, 2, False),
        ("sometimes", "Sometimes", 2, 3, False),
        ("often", "Often", 3, 4, False),
        ("always", "Always", 4, 5, False),
    ]
    for code, title, weight, sort_index, is_neutral in options:
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=title,
                code=code,
                weight=weight,
                sort_index=sort_index,
                is_neutral=is_neutral,
            )
        )
    await db.flush()
    return scale


@pytest_asyncio.fixture
async def ref_data(
    db: AsyncSession,
    system_roles,
    assessment_statuses,
    assessment_types,
    seed_scale,
    skill_levels,
    origin_grades,
    origin_specializations,
    origin_comp_types,
):
    """Curated equivalent of ``fetch_ref_data`` built from fixtures."""
    scale_options = (
        (
            await db.execute(
                select(AnswerOption)
                .where(AnswerOption.scale_id == seed_scale.id)
                .order_by(AnswerOption.sort_index)
            )
        )
        .scalars()
        .all()
    )
    assert len(scale_options) == 6
    return {
        "role_map": system_roles,
        "status_map": assessment_statuses,
        "type_map": assessment_types,
        "default_scale": seed_scale,
        "scale_options": scale_options,
        "grades": origin_grades,
        "specializations": origin_specializations,
        "comp_types": origin_comp_types,
        "skill_levels": skill_levels,
    }


async def _make_tenant_admin(db: AsyncSession, system_roles) -> tuple[Tenant, User]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"Seed Corp {uuid.uuid4().hex[:6]}",
        slug=f"seed-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add(tenant)
    await db.flush()
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"admin-{uuid.uuid4().hex[:8]}@seed.test",
        password_hash=hash_password("demo1234"),
        first_name="Seed",
        last_name="Admin",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    await db.flush()
    await db.execute(
        user_roles.insert().values(user_id=admin.id, role_id=system_roles["admin"].id)
    )
    return tenant, admin


async def _count(db: AsyncSession, model, *where) -> int:
    return (
        await db.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


@pytest.mark.asyncio
async def test_populate_tenant_full_demo_counts(
    db: AsyncSession, ref_data, system_roles
):
    tenant, admin = await _make_tenant_admin(db, system_roles)
    T = tenant.id

    result = await populate_tenant(db, tenant_id=T, admin_user=admin, ref_data=ref_data)

    # --- returned handles ---
    assert len(result["employees"]) == len(PEOPLE) == 50
    assert len(result["users"]) == 50
    assert len(result["divisions"]) == len(DIVISIONS_L1) + len(DIVISIONS_L2) == 18
    assert len(result["competences"]) == 12
    assert len(result["positions"]) == len({p[2] for p in PEOPLE}) == 42

    # --- step 1: division tree ---
    assert await _count(db, Division, Division.tenant_id == T) == 18
    assert await _count(
        db, Division, Division.tenant_id == T, Division.parent_id.is_(None)
    ) == len(DIVISIONS_L1)

    # --- step 2: users, employees, events ---
    assert await _count(db, User, User.tenant_id == T) == 51  # 50 + admin
    assert await _count(db, Employee, Employee.tenant_id == T) == 50
    emp_ids = select(Employee.id).where(Employee.tenant_id == T)
    assert (
        await _count(db, EmployeeEvent, EmployeeEvent.employee_id.in_(emp_ids)) == 55
    )  # 50 hire + 5 position_change
    expected_managers = sum(
        1 for p in PEOPLE if any(t in p[2] for t in ("Lead", "VP", "Head", "Manager"))
    )
    manager_users = (
        await db.execute(
            select(func.count())
            .select_from(user_roles)
            .join(User, User.id == user_roles.c.user_id)
            .where(
                User.tenant_id == T,
                user_roles.c.role_id == system_roles["manager"].id,
            )
        )
    ).scalar_one()
    assert manager_users == expected_managers == 18

    # every employee is linked to a division and a position
    assert (
        await _count(
            db, Employee, Employee.tenant_id == T, Employee.division_id.is_(None)
        )
        == 0
    )
    assert (
        await _count(
            db, Employee, Employee.tenant_id == T, Employee.position_id.is_(None)
        )
        == 0
    )

    # --- steps 2b–2f: career history ---
    assert await _count(db, PreviousEmployment, PreviousEmployment.tenant_id == T) == 15
    assert await _count(db, WorkExperience, WorkExperience.tenant_id == T) == 13
    assert await _count(db, Education, Education.tenant_id == T) == 18
    assert await _count(db, Course, Course.tenant_id == T) == 20
    assert await _count(db, Compensation, Compensation.tenant_id == T) == 21

    # --- step 2g: division managers ---
    assert (
        await _count(
            db, Division, Division.tenant_id == T, Division.manager_id.isnot(None)
        )
        == 18
    )
    assert (
        await _count(
            db,
            Division,
            Division.tenant_id == T,
            Division.deputy_manager_id.isnot(None),
        )
        == 3
    )
    backend_div = (
        await db.execute(
            select(Division).where(Division.tenant_id == T, Division.name == "Backend")
        )
    ).scalar_one()
    assert backend_div.manager_id == result["employees"][1].id  # Bob Martinez
    assert backend_div.deputy_manager_id == result["employees"][2].id  # Carol Johnson

    # --- step 3: custom dictionary items ---
    assert (
        await _count(
            db,
            DictionaryItem,
            DictionaryItem.tenant_id == T,
            DictionaryItem.type == "grade",
        )
        == 4
    )
    assert (
        await _count(
            db,
            DictionaryItem,
            DictionaryItem.tenant_id == T,
            DictionaryItem.type == "specialization",
        )
        == 4
    )

    # --- step 3b: specialization-division mappings ---
    # 5 hits from SPEC_DIV_MAPPINGS (Backend/Frontend/QA/DevOps + Backend→devops
    # — only these titles are present in the curated ref_data) + all 5
    # CUSTOM_SPEC_DIV rows (the 4 custom specs are created by the seed itself).
    assert (
        await _count(db, SpecializationDivision, SpecializationDivision.tenant_id == T)
        == 10
    )

    # --- step 3c: positions ---
    assert await _count(db, Position, Position.tenant_id == T) == 42
    headcount_total = (
        await db.execute(
            select(func.coalesce(func.sum(Position.headcount), 0)).where(
                Position.tenant_id == T
            )
        )
    ).scalar_one()
    assert headcount_total == 50

    # --- step 4: competences ---
    assert await _count(db, CompetenceGroup, CompetenceGroup.tenant_id == T) == 6
    assert await _count(db, Competence, Competence.tenant_id == T) == 12
    assert await _count(db, Indicator, Indicator.tenant_id == T) == 37
    assert await _count(db, Material, Material.tenant_id == T) == 5

    # --- step 5: assessments ---
    assert await _count(db, Assessment, Assessment.tenant_id == T) == 3
    assessment_ids = select(Assessment.id).where(Assessment.tenant_id == T)
    assert (
        await _count(
            db,
            AssessmentCompetence,
            AssessmentCompetence.assessment_id.in_(assessment_ids),
        )
        == 15
    )
    assert (
        await _count(
            db,
            AssessmentParticipant,
            AssessmentParticipant.assessment_id.in_(assessment_ids),
        )
        == 8
    )  # 1 self + (self+manager) + (self+manager+3 peers)
    assert (
        await _count(
            db, AssessmentAnswer, AssessmentAnswer.assessment_id.in_(assessment_ids)
        )
        == 32
    )  # 16 (a1 self) + 16 (a2 self)
    assert (
        await _count(
            db, AssessmentResult, AssessmentResult.assessment_id.in_(assessment_ids)
        )
        == 5
    )

    # --- step 6: PDPs ---
    assert await _count(db, PDP, PDP.tenant_id == T) == 3
    pdp_ids = select(PDP.id).where(PDP.tenant_id == T)
    assert await _count(db, PDPItem, PDPItem.pdp_id.in_(pdp_ids)) == 8  # 3 + 3 + 2
    item_ids = select(PDPItem.id).where(PDPItem.pdp_id.in_(pdp_ids))
    assert await _count(db, PDPItemMaterial, PDPItemMaterial.item_id.in_(item_ids)) == 5
    assert await _count(db, PDPComment, PDPComment.pdp_id.in_(pdp_ids)) == 2

    # --- step 7: mass exam ---
    assert await _count(db, MassExam, MassExam.tenant_id == T) == 1
    mass_exam = (
        await db.execute(select(MassExam).where(MassExam.tenant_id == T))
    ).scalar_one()
    assert (
        await _count(db, ExamQuestion, ExamQuestion.mass_exam_id == mass_exam.id) == 8
    )
    question_ids = select(ExamQuestion.id).where(
        ExamQuestion.mass_exam_id == mass_exam.id
    )
    assert (
        await _count(db, QuestionOption, QuestionOption.question_id.in_(question_ids))
        == 26
    )
    assert (
        await _count(db, ExamPassMark, ExamPassMark.mass_exam_id == mass_exam.id) == 3
    )
    exams = (await db.execute(select(Exam).where(Exam.tenant_id == T))).scalars().all()
    assert len(exams) == 10
    for exam in exams:
        assert exam.max_score == 10
        n_answers = await _count(db, ExamAnswer, ExamAnswer.exam_id == exam.id)
        if exam.status == "completed":
            assert n_answers == 8
            assert exam.score is not None and 5 <= exam.score <= 10
        elif exam.status == "in_progress":
            assert n_answers == 4
        else:
            assert exam.status == "assigned"
            assert n_answers == 0

    # --- step 8: talent market ---
    cards = (
        (await db.execute(select(TalentCard).where(TalentCard.tenant_id == T)))
        .scalars()
        .all()
    )
    assert {(c.card_type, c.status) for c in cards} == {
        ("vacancy", "published"),
        ("talent", "draft"),
        ("project", "published"),
    }
    card_ids = select(TalentCard.id).where(TalentCard.tenant_id == T)
    assert (
        await _count(
            db, TalentCardSpecialization, TalentCardSpecialization.card_id.in_(card_ids)
        )
        == 1
    )
    assert (
        await _count(
            db, TalentCardCompetence, TalentCardCompetence.card_id.in_(card_ids)
        )
        == 4
    )
    assert (
        await _count(
            db, TalentCardRequirement, TalentCardRequirement.card_id.in_(card_ids)
        )
        == 4
    )
    by_type = {c.card_type: c for c in cards}
    assert (
        await _count(
            db, TalentCandidate, TalentCandidate.card_id == by_type["vacancy"].id
        )
        == 2
    )
    assert (
        await _count(
            db, TalentCandidate, TalentCandidate.card_id == by_type["project"].id
        )
        == 4
    )
    assert (
        await _count(
            db, TalentCandidate, TalentCandidate.card_id == by_type["talent"].id
        )
        == 0
    )


SECONDARY_PEOPLE = [
    ("James", "Harper", "Managing Director", "leadership", "james.harper"),
    ("Sofia", "Reyes", "Partner, Strategy", "strategy", "sofia.reyes"),
    ("Oliver", "Grant", "Senior Consultant", "strategy", "oliver.grant"),
    ("Isabella", "Ward", "HR Manager", "operations", "isabella.ward"),
]
SECONDARY_L1 = [
    ("Leadership", "leadership"),
    ("Consulting", "consulting"),
    ("Operations", "operations"),
]
SECONDARY_L2 = [("Strategy Consulting", "strategy", "consulting")]
SECONDARY_GRADES = [("Partner", "Partner level", 10)]
SECONDARY_SPECS = [("Strategy Consultant", 10)]


@pytest.mark.asyncio
async def test_populate_tenant_secondary_stops_after_competences(
    db: AsyncSession, ref_data, system_roles
):
    """full_demo=False (the seed_saas secondary-tenant path) creates the org
    catalogue only — no assessments / PDPs / exams / talent cards."""
    tenant, admin = await _make_tenant_admin(db, system_roles)
    T = tenant.id

    result = await populate_tenant(
        db,
        tenant_id=T,
        admin_user=admin,
        ref_data=ref_data,
        people=SECONDARY_PEOPLE,
        divisions_l1=SECONDARY_L1,
        divisions_l2=SECONDARY_L2,
        custom_grades=SECONDARY_GRADES,
        custom_specs=SECONDARY_SPECS,
        email_domain="secondary.test",
        full_demo=False,
    )

    assert len(result["employees"]) == 4
    assert len(result["divisions"]) == 4
    assert len(result["competences"]) == 12
    assert set(result) == {
        "employees",
        "users",
        "divisions",
        "competences",
        "positions",
    }

    assert await _count(db, Division, Division.tenant_id == T) == 4
    assert await _count(db, User, User.tenant_id == T) == 5  # 4 + admin
    assert await _count(db, Employee, Employee.tenant_id == T) == 4
    users = (
        (await db.execute(select(User).where(User.tenant_id == T, User.id != admin.id)))
        .scalars()
        .all()
    )
    assert all(u.email.endswith("@secondary.test") for u in users)
    assert (
        await _count(
            db,
            DictionaryItem,
            DictionaryItem.tenant_id == T,
            DictionaryItem.type == "grade",
        )
        == 1
    )
    assert (
        await _count(
            db,
            DictionaryItem,
            DictionaryItem.tenant_id == T,
            DictionaryItem.type == "specialization",
        )
        == 1
    )
    assert await _count(db, Competence, Competence.tenant_id == T) == 12
    assert await _count(db, Material, Material.tenant_id == T) == 5

    # full-demo-only steps did not run
    assert await _count(db, Assessment, Assessment.tenant_id == T) == 0
    assert await _count(db, PDP, PDP.tenant_id == T) == 0
    assert await _count(db, MassExam, MassExam.tenant_id == T) == 0
    assert await _count(db, TalentCard, TalentCard.tenant_id == T) == 0
