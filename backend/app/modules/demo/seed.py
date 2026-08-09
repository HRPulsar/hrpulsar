"""Reusable demo-tenant seeder (HRP-250 — D2).

Public entry point: :func:`clone_seed_into_demo_tenant`.

Both the hosted demo sandbox (``POST /api/demo/start`` in D3) and the
self-hosted CLI (``scripts/seed_demo_investor.py``) call this function
to lay down the same investor-grade dataset on top of a pre-existing
``Tenant``. The caller is responsible for creating the tenant + at
least one ``User`` (used as ``Vacancy.owner_id`` / ``CandidateVacancy
.attached_by`` / ``Interview.interviewer_id``); this module never
mutates the tenant row itself.

Idempotency is enforced by checking for any ``Candidate`` previously
tagged with ``INVESTOR_MARKER`` and short-circuiting if found. A
caller that wants a clean re-seed must delete those rows first
(``scripts/seed_demo_investor.py --reset`` does exactly that for the
self-hosted base tenant).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.assessment.models import (
    PDP,
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
    PDPItem,
)
from app.modules.auth.models import User
from app.modules.company.models import Division, Tenant
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
    SkillLevel,
)
from app.modules.demo.seed_data import (
    ELENA_INTERVIEW_ANALYSIS,
    INVESTOR_MARKER,
    TOMAS_INTERVIEW_ANALYSIS,
    VACANCIES,
    candidates,
    load_transcript,
)
from app.modules.demo.seed_data_assessments import (
    ASSESSMENTS,
    PDPS,
)
from app.modules.demo.seed_data_company import (
    DEMO_SEED_METADATA_MARKER,
    DIVISIONS,
    GRADE_SPECIALIZATIONS,
    GRADES,
    POSITIONS,
    SPECIALIZATIONS,
)
from app.modules.demo.seed_data_competences import (
    COMPETENCE_GROUPS,
    COMPETENCES,
    GRADE_COMPETENCE_LINKS,
    INDICATORS,
    MATERIALS,
    SKILL_LEVELS,
)
from app.modules.demo.seed_data_employees import (
    EMPLOYEE_ASSIGNMENTS,
    NAME_POOL,
    email_for,
    hire_days_back,
)
from app.modules.demo.seed_data_exams import MASS_EXAMS
from app.modules.demo.seed_data_misc import (
    CUSTOM_DICTIONARIES,
    NOTIFICATIONS,
)
from app.modules.demo.seed_data_recruitment_extras import (
    EXTRA_CANDIDATES,
    EXTRA_VACANCIES,
    INTERVIEW_SHAPES,
)
from app.modules.demo.seed_data_talent_market import TALENT_CARDS
from app.modules.demo.seed_i18n import localize, seed_locale, translate
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee
from app.modules.exam.models import (
    Exam,
    ExamAnswer,
    ExamPassMark,
    ExamQuestion,
    MassExam,
    QuestionOption,
)
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.notification.models import (
    Notification,
    NotificationTemplate,
)
from app.modules.position.models import Position
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardCompetence,
    TalentCardRequirement,
    TalentCardSpecialization,
)

# Stable, ASCII-only keys for the two completed-interview candidates,
# matching the ``email`` field in their seed_data specs. Using emails
# (not display names) means the cv lookup can't be broken by Unicode
# normalisation drift on names like "Tomás Becker".
_ELENA_KEY = "elena.volkov@example.com"
_TOMAS_KEY = "tomas.becker@example.com"
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
    VacancyProfile,
)

logger = logging.getLogger(__name__)


async def _pick_anchor_division(
    db: AsyncSession, tenant_id: uuid.UUID
) -> Division | None:
    """Prefer an Engineering-shaped division, fall back to any division,
    otherwise leave the vacancy unscoped.

    The fallback path orders by ``created_at, id`` so a tenant with
    multiple non-engineering divisions doesn't end up scoping the
    headline Senior Backend vacancy to whichever row Postgres happens
    to return first.
    """
    rows = (
        (
            await db.execute(
                select(Division)
                .where(Division.tenant_id == tenant_id)
                .order_by(Division.created_at, Division.id)
            )
        )
        .scalars()
        .all()
    )
    for d in rows:
        if any(token in d.name for token in ("Engineering", "Engineer", "Dev")):
            return d
    return rows[0] if rows else None


class CompanyContext:
    """Resolved company-structure rows the recruitment + employee seeders
    rely on.

    All maps are keyed by the stable ``key`` strings from
    ``seed_data_company`` (e.g. ``"engineering"`` for the Engineering
    division, ``"p-be-l3"`` for a Senior Backend Engineer position).
    Carries the engineering anchor division explicitly so the recruitment
    seeder doesn't need a second round-trip through
    ``_pick_anchor_division``.
    """

    __slots__ = (
        "divisions",
        "specializations",
        "grades",
        "positions",
        "grade_specializations",
        "anchor_division_id",
        "skill_levels",
        "competence_groups",
        "competences",
        "employees",
        "employee_users",
    )

    def __init__(self) -> None:
        self.divisions: dict[str, Division] = {}
        self.specializations: dict[str, DictionaryItem] = {}
        self.grades: dict[str, DictionaryItem] = {}
        self.positions: dict[str, Position] = {}
        self.grade_specializations: dict[tuple[str, str], GradeSpecialization] = {}
        self.anchor_division_id: uuid.UUID | None = None
        self.skill_levels: dict[str, SkillLevel] = {}
        self.competence_groups: dict[str, CompetenceGroup] = {}
        self.competences: dict[str, Competence] = {}
        self.employees: list[Employee] = []
        self.employee_users: list[User] = []


async def _upsert_dict_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    type_: str,
    title: str,
    description: str | None,
    sort_index: int,
) -> DictionaryItem:
    existing = (
        await db.execute(
            select(DictionaryItem).where(
                DictionaryItem.tenant_id == tenant_id,
                DictionaryItem.type == type_,
                DictionaryItem.title == title,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    item = DictionaryItem(
        tenant_id=tenant_id,
        type=type_,
        title=title,
        description=description,
        sort_index=sort_index,
        metadata_=DEMO_SEED_METADATA_MARKER,
    )
    db.add(item)
    await db.flush()
    return item


async def _seed_company_structure(
    db: AsyncSession, tenant_id: uuid.UUID
) -> CompanyContext:
    """Lay down divisions + dictionary-backed specs/grades + positions
    + grade-ladder cells. Idempotent per natural key.

    Order matters: dictionary items (specs + grades) → divisions
    (parent-before-child) → positions (need division + spec + grade)
    → grade-specializations (need grade + spec).
    """
    ctx = CompanyContext()

    # 1. Specializations
    for idx, spec in enumerate(localize(SPECIALIZATIONS)):
        ctx.specializations[spec["key"]] = await _upsert_dict_item(
            db,
            tenant_id,
            type_="specialization",
            title=spec["title"],
            description=spec.get("description"),
            sort_index=idx * 10,
        )

    # 2. Grades — HRP-302: bind to the origin (tenant_id IS NULL) grade
    # set shipped by migration aca1005a8e45 so the Dictionaries → Grades
    # page doesn't render System / Custom pairs of the same titles. Only
    # fall back to a tenant-scoped row if the origin row is absent
    # (e.g. a test DB that never ran the data migration). ``.first()``
    # tolerates duplicate origin rows that other CI tests may have
    # inserted without cleanup. NOT localized: the titles resolve origin
    # rows by name and must stay byte-identical to the migration seed.
    for spec in GRADES:
        origin = (
            (
                await db.execute(
                    select(DictionaryItem).where(
                        DictionaryItem.tenant_id.is_(None),
                        DictionaryItem.type == "grade",
                        DictionaryItem.title == spec["title"],
                    )
                )
            )
            .scalars()
            .first()
        )
        if origin is not None:
            ctx.grades[spec["key"]] = origin
            continue
        ctx.grades[spec["key"]] = await _upsert_dict_item(
            db,
            tenant_id,
            type_="grade",
            title=spec["title"],
            description=None,
            sort_index=spec["sort_index"],
        )

    # 3. Divisions — two passes so children resolve their parent.
    for spec in localize(DIVISIONS):
        existing = (
            await db.execute(
                select(Division).where(
                    Division.tenant_id == tenant_id,
                    Division.name == spec["name"],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            ctx.divisions[spec["key"]] = existing
            continue
        parent_id = None
        if spec["parent_key"] is not None:
            parent = ctx.divisions.get(spec["parent_key"])
            if parent is not None:
                parent_id = parent.id
        division = Division(
            tenant_id=tenant_id,
            name=spec["name"],
            description=spec.get("description"),
            parent_id=parent_id,
        )
        db.add(division)
        await db.flush()
        ctx.divisions[spec["key"]] = division

    anchor = ctx.divisions.get("engineering")
    if anchor is not None:
        ctx.anchor_division_id = anchor.id

    # 4. Positions
    for spec in localize(POSITIONS):
        existing_pos = (
            await db.execute(
                select(Position).where(
                    Position.tenant_id == tenant_id,
                    Position.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing_pos is not None:
            ctx.positions[spec["key"]] = existing_pos
            continue
        division = ctx.divisions[spec["division_key"]]
        specialization = ctx.specializations[spec["specialization_key"]]
        grade = ctx.grades[spec["grade_key"]]
        position = Position(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec.get("description"),
            specialization_id=specialization.id,
            grade_id=grade.id,
            division_id=division.id,
            headcount=spec.get("headcount"),
            is_active=True,
            lifecycle_status="active",
            source="manual",
        )
        db.add(position)
        await db.flush()
        ctx.positions[spec["key"]] = position

    # 5. Grade-specializations (ladder cells)
    for spec in localize(GRADE_SPECIALIZATIONS):
        grade = ctx.grades[spec["grade_key"]]
        specialization = ctx.specializations[spec["specialization_key"]]
        existing_gs = (
            await db.execute(
                select(GradeSpecialization).where(
                    GradeSpecialization.tenant_id == tenant_id,
                    GradeSpecialization.grade_id == grade.id,
                    GradeSpecialization.specialization_id == specialization.id,
                )
            )
        ).scalar_one_or_none()
        if existing_gs is not None:
            ctx.grade_specializations[
                (spec["grade_key"], spec["specialization_key"])
            ] = existing_gs
            continue
        gs = GradeSpecialization(
            tenant_id=tenant_id,
            grade_id=grade.id,
            specialization_id=specialization.id,
            description=spec.get("description"),
            salary_min=spec.get("salary_min"),
            salary_max=spec.get("salary_max"),
            salary_currency="EUR",
            passing_score=spec.get("passing_score"),
        )
        db.add(gs)
        await db.flush()
        ctx.grade_specializations[(spec["grade_key"], spec["specialization_key"])] = gs

    return ctx


async def _seed_competences(
    db: AsyncSession, tenant_id: uuid.UUID, ctx: CompanyContext
) -> None:
    """Lay down the tenant-scoped competence ladder (HRP-281 / S2).

    Mutates ``ctx`` in place: populates ``skill_levels``,
    ``competence_groups``, ``competences``, and creates
    ``GradeCompetenceLink`` rows on the ladder cells from S1.

    Idempotent per natural key on (tenant_id, title).
    """
    # 1. SkillLevels — bind to the origin (tenant_id IS NULL) Basic /
    # Intermediate / Advanced ladder seeded by migration aca1005a8e45.
    # HRP-299: don't create tenant-scoped custom levels — the UI would
    # show 3 origin + N custom and the ladder reads as inconsistent.
    # ``.first()`` instead of ``scalar_one_or_none()`` because the
    # shared CI test DB can accumulate duplicate origin rows when other
    # tests insert their own SkillLevel(tenant_id=None, title=...) and
    # never roll them back — picking any one of the duplicates is fine,
    # the seed only needs a foreign-key target.
    for spec in SKILL_LEVELS:
        sl = (
            (
                await db.execute(
                    select(SkillLevel).where(
                        SkillLevel.tenant_id.is_(None),
                        SkillLevel.title == spec["title"],
                    )
                )
            )
            .scalars()
            .first()
        )
        if sl is None:
            # Origin ladder absent (unlikely outside fresh test DBs without
            # the data migration). Skip rather than insert tenant clutter.
            continue
        ctx.skill_levels[spec["key"]] = sl
    # If NONE of the expected titles resolved, the data migration
    # (``aca1005a8e45``) hasn't run on this database. Continuing would
    # silently skip every indicator, material and grade-link spec and
    # leave the demo with empty /competences cards — fail loudly instead.
    if not ctx.skill_levels:
        raise RuntimeError(
            "demo seed: origin SkillLevel rows (Basic / Intermediate / "
            "Advanced) are missing — run migration aca1005a8e45 or the "
            "``skill_levels`` test fixture before seeding."
        )

    # 2. Competence groups
    for spec in localize(COMPETENCE_GROUPS):
        existing_group = (
            await db.execute(
                select(CompetenceGroup).where(
                    CompetenceGroup.tenant_id == tenant_id,
                    CompetenceGroup.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing_group is not None:
            ctx.competence_groups[spec["key"]] = existing_group
            continue
        group = CompetenceGroup(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec.get("description"),
            sort_index=spec["sort_index"],
            is_active=True,
            can_deactivate=True,
        )
        db.add(group)
        await db.flush()
        ctx.competence_groups[spec["key"]] = group

    # 3. Competences
    for spec in localize(COMPETENCES):
        existing_comp = (
            await db.execute(
                select(Competence).where(
                    Competence.tenant_id == tenant_id,
                    Competence.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing_comp is not None:
            ctx.competences[spec["key"]] = existing_comp
            continue
        comp = Competence(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec.get("description"),
            group_id=ctx.competence_groups[spec["group_key"]].id,
            is_active=True,
            is_published=True,
        )
        db.add(comp)
        await db.flush()
        ctx.competences[spec["key"]] = comp

    # 4. Indicators (one per skill level per competence).
    # Without these the /competences cards render empty and the
    # assessment scoring form has nothing to ask.
    #
    # HRP-299 collapsed the legacy 4-level ladder onto the 3-level
    # origin ladder by aliasing ``sl-l4`` → Advanced. The INDICATORS
    # fixture still carries one row per legacy level, so two distinct
    # titles can resolve to the same ``(competence, skill_level)`` pair.
    # We keep the first one we see (the lower-tier prose) — adding
    # both would render two indicators under the same Advanced cell.
    sort_by_competence: dict[uuid.UUID, int] = {}
    seen_indicator_cells: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for spec in localize(INDICATORS):
        competence = ctx.competences.get(spec["competence_key"])
        skill_level = ctx.skill_levels.get(spec["skill_level_key"])
        if competence is None or skill_level is None:
            continue
        cell = (competence.id, skill_level.id)
        if cell in seen_indicator_cells:
            continue
        existing_ind = (
            await db.execute(
                select(Indicator).where(
                    Indicator.tenant_id == tenant_id,
                    Indicator.competence_id == competence.id,
                    Indicator.skill_level_id == skill_level.id,
                )
            )
        ).scalar_one_or_none()
        if existing_ind is not None:
            seen_indicator_cells.add(cell)
            continue
        sort_index = sort_by_competence.get(competence.id, 0)
        db.add(
            Indicator(
                tenant_id=tenant_id,
                title=spec["title"],
                weight=spec.get("weight", 1),
                sort_index=sort_index,
                skill_level_id=skill_level.id,
                competence_id=competence.id,
                is_active=True,
            )
        )
        sort_by_competence[competence.id] = sort_index + 1
        seen_indicator_cells.add(cell)
    await db.flush()

    # 4b. Materials (HRP-298). One per (competence × level) so the
    # /competences "Materials" tab renders a non-empty list. Same
    # sl-l3/sl-l4 collapse rule as Indicators above — keep the first
    # row that lands on each ladder cell, drop the rest.
    materials_sort_by_competence: dict[uuid.UUID, int] = {}
    seen_material_cells: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for spec in localize(MATERIALS):
        competence = ctx.competences.get(spec["competence_key"])
        skill_level = ctx.skill_levels.get(spec["skill_level_key"])
        if competence is None or skill_level is None:
            continue
        cell = (competence.id, skill_level.id)
        if cell in seen_material_cells:
            continue
        existing_material = (
            await db.execute(
                select(Material).where(
                    Material.tenant_id == tenant_id,
                    Material.competence_id == competence.id,
                    Material.skill_level_id == skill_level.id,
                )
            )
        ).scalar_one_or_none()
        if existing_material is not None:
            seen_material_cells.add(cell)
            continue
        sort_index = materials_sort_by_competence.get(competence.id, 0)
        db.add(
            Material(
                tenant_id=tenant_id,
                title=spec["title"],
                format=spec.get("format"),
                link=spec.get("link"),
                study_time=spec.get("study_time"),
                comment=spec.get("comment"),
                material_type=spec.get("material_type"),
                sort_index=sort_index,
                skill_level_id=skill_level.id,
                competence_id=competence.id,
                is_active=True,
            )
        )
        materials_sort_by_competence[competence.id] = sort_index + 1
        seen_material_cells.add(cell)
    await db.flush()

    # 5. Grade × Competence × SkillLevel links
    for spec in GRADE_COMPETENCE_LINKS:
        ladder_key = (spec["grade_key"], spec["specialization_key"])
        ladder = ctx.grade_specializations.get(ladder_key)
        if ladder is None:
            # Ladder cell not seeded (e.g. Sales spec). Skip the link.
            continue
        competence = ctx.competences[spec["competence_key"]]
        skill_level = ctx.skill_levels.get(spec["skill_level_key"])
        if skill_level is None:
            # Origin skill levels missing (test DB without the data
            # migration). Without them we'd KeyError on the lookup above
            # — skip the link so the rest of the seed continues to run.
            continue
        existing_link = (
            await db.execute(
                select(GradeCompetenceLink).where(
                    GradeCompetenceLink.grade_specialization_id == ladder.id,
                    GradeCompetenceLink.competence_id == competence.id,
                )
            )
        ).scalar_one_or_none()
        if existing_link is not None:
            continue
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=ladder.id,
                competence_id=competence.id,
                skill_level_id=skill_level.id,
            )
        )
    await db.flush()


async def _seed_employees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    now: datetime,
) -> None:
    """Materialise 40 employee cards + their backing User rows
    (HRP-281 / S3).

    Two passes:

    1. Create Users + Employees from ``EMPLOYEE_ASSIGNMENTS``. Status
       enum: active / onboarding / inactive / on_leave.
    2. Wire ``Division.manager_id`` (and ``deputy_manager_id``) from
       employees flagged ``manager_role=division_head|division_deputy``
       — divisions need to exist first, which S1 already guarantees.

    Idempotent per natural key on ``(email, tenant_id)`` — re-running
    the seed is a no-op for any user/employee already present.
    """
    today = now.date()

    # bcrypt hashing is the dominant cost on /demo/start when we mint
    # 40 demo Users — hash one throwaway secret up front and reuse it.
    # None of these credentials are ever used (demo users log in via the
    # JWT pair minted by ``create_demo_session``); the single shared
    # hash is purely there to satisfy the NOT NULL column.
    shared_demo_password_hash = hash_password(secrets.token_urlsafe(32))

    for idx, (assignment, (first, last)) in enumerate(
        zip(EMPLOYEE_ASSIGNMENTS, NAME_POOL, strict=True)
    ):
        email = email_for(first, last)
        existing_user = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.email == email,
                )
            )
        ).scalar_one_or_none()
        if existing_user is not None:
            user = existing_user
        else:
            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                email=email,
                password_hash=shared_demo_password_hash,
                first_name=first,
                last_name=last,
                email_verified_at=now,
                is_active=assignment["status"] != "inactive",
            )
            db.add(user)
            await db.flush()
        ctx.employee_users.append(user)

        existing_emp = (
            await db.execute(
                select(Employee).where(
                    Employee.tenant_id == tenant_id,
                    Employee.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing_emp is not None:
            ctx.employees.append(existing_emp)
            continue

        division = ctx.divisions[assignment["division_key"]]
        position = ctx.positions[assignment["position_key"]]
        hire_date_value: date = today - timedelta(
            days=hire_days_back(
                idx,
                assignment["status"],
                recent_hire=assignment.get("recent_hire", False),
            )
        )
        status_value = assignment["status"]
        employee = Employee(
            tenant_id=tenant_id,
            user_id=user.id,
            division_id=division.id,
            position_id=position.id,
            position_title=position.title,
            hire_date=hire_date_value,
            status=status_value,
            status_changed_at=now if status_value != "active" else None,
        )
        db.add(employee)
        await db.flush()
        ctx.employees.append(employee)

    # ── Wire division leadership ────────────────────────────────────────
    for assignment, employee in zip(EMPLOYEE_ASSIGNMENTS, ctx.employees, strict=True):
        role = assignment["manager_role"]
        if role is None:
            continue
        division = ctx.divisions[assignment["division_key"]]
        if role == "division_head" and division.manager_id is None:
            division.manager_id = employee.id
        elif role == "division_deputy" and division.deputy_manager_id is None:
            division.deputy_manager_id = employee.id

    # HRP-303: the Engineering parent division has no direct headcount
    # (sub-divisions hold all eng employees), so the sub-division heads
    # above leave Engineering.manager_id / deputy_manager_id NULL. Without
    # leadership wired up, any employee landed under ``engineering`` (or a
    # new hire dragged there in the UI) breaks downstream flows that need
    # a Division Manager — assessment Participants, PDP routing, the
    # 180/360 rubric. Borrow the Backend EM as Engineering head and the
    # Frontend EM as deputy: they already exist, already manage engineers,
    # and only their division-parent leadership pointers need a value.
    engineering = ctx.divisions.get("engineering")
    if engineering is not None:
        eng_backend = ctx.divisions.get("eng-backend")
        eng_frontend = ctx.divisions.get("eng-frontend")
        if engineering.manager_id is None and eng_backend is not None:
            engineering.manager_id = eng_backend.manager_id
        if engineering.deputy_manager_id is None and eng_frontend is not None:
            engineering.deputy_manager_id = eng_frontend.manager_id
    await db.flush()


async def _seed_assessments_and_pdps(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    owner_user_id: uuid.UUID,
    now: datetime,
) -> tuple[int, int]:
    """Materialise the demo assessment cycles and PDPs (HRP-281 / S4).

    Returns ``(assessment_count, pdp_count)`` for the seed-summary
    payload. Idempotent: looks up each assessment by ``(tenant_id,
    title)`` before inserting; PDPs by ``(tenant_id, employee_id,
    title)``.
    """
    # Look up the origin reference rows shipped by migration
    # ``c3fc300775f8``. If any of them are missing (e.g. a stripped-
    # down test database that didn't run those migrations) bail out —
    # the seed still produces a useful tenant without assessments.
    status_rows = (await db.execute(select(AssessmentStatus))).scalars().all()
    statuses_by_code = {s.code: s for s in status_rows}
    type_rows = (await db.execute(select(AssessmentType))).scalars().all()
    types_by_code = {t.code: t for t in type_rows}
    default_scale = (
        await db.execute(
            select(AnswerScale).where(
                AnswerScale.is_default.is_(True),
                AnswerScale.tenant_id.is_(None),
                AnswerScale.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    scoring_options: list[AnswerOption] = []
    if default_scale is not None:
        scoring_options = list(
            (
                await db.execute(
                    select(AnswerOption)
                    .where(
                        AnswerOption.scale_id == default_scale.id,
                        AnswerOption.is_neutral.is_(False),
                        AnswerOption.weight.is_not(None),
                    )
                    .order_by(AnswerOption.weight.asc())
                )
            ).scalars()
        )
    # HRP-314: assessments are back in the demo tenant. The previous
    # seed (HRP-281) created cycles without an Evaluation criterion and
    # without a real Division Manager as a 180/360 participant, which
    # made the Draft → Sent transition fail (service.py requires
    # ``criteria_type IS NOT NULL``) and rendered broken cards. Each
    # spec now declares an explicit ``criteria_type`` and the loop
    # mirrors ``service.py::_auto_assign_manager`` for 180/360.
    assessment_count = 0
    # Only ``done`` assessments are referenced from the PDP linker
    # below — linking a review-stage PDP back to a draft assessment
    # would render a "derived from <draft, no results>" pointer on the
    # PDP detail page, which contradicts the demo narrative.
    done_assessment_by_employee: dict[int, Assessment] = {}
    supported_type_codes = {"180", "360", "self"}
    supported_status_codes = {"draft", "in_progress", "done", "cancelled"}
    for spec in localize(ASSESSMENTS):
        # Fail-loud on specs the seed does not know how to materialise —
        # silent fall-through used to leave half-shaped Assessment rows.
        if spec["type_code"] not in supported_type_codes:
            raise RuntimeError(
                f"demo seed: spec {spec['title']!r} uses unsupported "
                f"type_code {spec['type_code']!r} (expected one of "
                f"{sorted(supported_type_codes)})"
            )
        if spec["status_code"] not in supported_status_codes:
            raise RuntimeError(
                f"demo seed: spec {spec['title']!r} uses unsupported "
                f"status_code {spec['status_code']!r} (expected one of "
                f"{sorted(supported_status_codes)})"
            )
        employee = ctx.employees[spec["employee_index"]]
        employee_user = ctx.employee_users[spec["employee_index"]]
        title = spec["title"]
        existing = (
            await db.execute(
                select(Assessment).where(
                    Assessment.tenant_id == tenant_id,
                    Assessment.title == title,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if spec["status_code"] == "done":
                done_assessment_by_employee[spec["employee_index"]] = existing
            continue
        status = statuses_by_code.get(spec["status_code"])
        type_ = types_by_code.get(spec["type_code"])
        if status is None or type_ is None:
            continue

        started_at = ended_at = finished_at = None
        if spec["status_code"] in {"in_progress", "done", "cancelled"}:
            started_at = now - timedelta(days=21)
            ended_at = now + timedelta(days=14)
        if spec["status_code"] == "done":
            finished_at = now - timedelta(days=3)
        if spec["status_code"] == "cancelled":
            finished_at = now - timedelta(days=5)

        # Mirror ``service.py::_apply_criteria_to_assessment`` +
        # ``_resolve_passing_score``: ``competences`` mode forces
        # specialization_id, grade_id and passing_score to NULL on the
        # Assessment row. Without this, the first Edit-criteria click
        # in the UI silently strips the visible spec/grade chips.
        criteria_type = spec.get("criteria_type", "competences")
        if criteria_type == "competences":
            assessment_specialization_id = None
            assessment_grade_id = None
            assessment_passing_score = None
        else:
            assessment_specialization_id = ctx.specializations[
                spec["specialization_key"]
            ].id
            assessment_grade_id = ctx.grades[spec["grade_key"]].id
            assessment_passing_score = 75
        assessment = Assessment(
            tenant_id=tenant_id,
            title=title,
            employee_id=employee.id,
            type_id=type_.id,
            status_id=status.id,
            specialization_id=assessment_specialization_id,
            grade_id=assessment_grade_id,
            scale_id=default_scale.id if default_scale else None,
            criteria_type=criteria_type,
            initiator_id=owner_user_id,
            started_at=started_at,
            ended_at=ended_at,
            finished_at=finished_at,
            passing_score=assessment_passing_score,
        )
        db.add(assessment)
        await db.flush()
        if spec["status_code"] == "done":
            done_assessment_by_employee[spec["employee_index"]] = assessment
        assessment_count += 1

        for comp_key in spec["competence_keys"]:
            competence = ctx.competences.get(comp_key)
            if competence is None:
                continue
            db.add(
                AssessmentCompetence(
                    assessment_id=assessment.id,
                    competence_id=competence.id,
                    skill_level_id=None,
                )
            )

        # Participants: the assessee is always added as self (mirrors
        # service.py::_auto_assign_self). For 180/360 we resolve the
        # Division Manager from the employee's division chain and add
        # them as ``manager`` (mirrors service.py::_auto_assign_manager).
        # The check fails loud if a 180/360 spec lands on an employee
        # who is themselves the division_head — that produces an empty
        # scoring matrix and contradicts the cycle type.
        self_participant = AssessmentParticipant(
            assessment_id=assessment.id,
            user_id=employee_user.id,
            role="self",
            is_completed=spec["status_code"] == "done",
        )
        db.add(self_participant)

        manager_participant: AssessmentParticipant | None = None
        if spec["type_code"] in {"180", "360"}:
            division = (
                await db.get(Division, employee.division_id)
                if employee.division_id is not None
                else None
            )
            manager_employee = None
            if (
                division is not None
                and division.manager_id is not None
                and division.manager_id != employee.id
            ):
                manager_employee = await db.get(Employee, division.manager_id)
            if manager_employee is None:
                raise RuntimeError(
                    f"demo seed: 180/360 spec {spec['title']!r} cannot "
                    f"resolve a Division Manager for employee_index="
                    f"{spec['employee_index']} — pick a sub-division "
                    f"employee whose Division.manager_id is wired and "
                    f"distinct from the assessee."
                )
            manager_participant = AssessmentParticipant(
                assessment_id=assessment.id,
                user_id=manager_employee.user_id,
                role="manager",
                is_completed=spec["status_code"] == "done",
            )
            db.add(manager_participant)

        # Scoring matrix: self cycles get answers from the assessee; 180/360
        # get them from the Division Manager (and, when finished, from the
        # assessee as well so the comparison view has both columns).
        scoring_participants: list[AssessmentParticipant] = []
        if spec["status_code"] in {"in_progress", "done"}:
            if spec["type_code"] == "self":
                scoring_participants.append(self_participant)
            else:
                assert manager_participant is not None  # enforced above for 180/360
                scoring_participants.append(manager_participant)
                if spec["status_code"] == "done":
                    scoring_participants.append(self_participant)
        await db.flush()

        for comp_key, avg_score, percent in spec.get("result_overrides", []):
            competence = ctx.competences.get(comp_key)
            if competence is None:
                continue
            db.add(
                AssessmentResult(
                    assessment_id=assessment.id,
                    competence_id=competence.id,
                    avg_score=avg_score,
                    percent=percent,
                )
            )

        if scoring_participants and scoring_options:
            avg_by_competence = {
                comp_key: avg for comp_key, avg, _ in spec.get("result_overrides", [])
            }
            for comp_key in spec["competence_keys"]:
                competence = ctx.competences.get(comp_key)
                if competence is None:
                    continue
                indicators = list(
                    (
                        await db.execute(
                            select(Indicator)
                            .where(Indicator.competence_id == competence.id)
                            .order_by(Indicator.sort_index.asc())
                        )
                    ).scalars()
                )
                if not indicators:
                    continue
                target_avg = avg_by_competence.get(comp_key)
                for ind_idx, indicator in enumerate(indicators):
                    # in_progress: leave the top indicator unanswered so
                    # the form still looks partially completed.
                    if (
                        spec["status_code"] == "in_progress"
                        and ind_idx == len(indicators) - 1
                    ):
                        continue
                    for part_idx, participant in enumerate(scoring_participants):
                        if target_avg is not None:
                            # done assessments: anchor on the recorded
                            # avg so results widget numbers match the
                            # underlying answers. Nudge ±1 across
                            # indicators for spread without breaking the
                            # average.
                            base = int(round(target_avg))
                            offset = (ind_idx + part_idx) % 3 - 1
                            target_weight = base + offset
                        else:
                            # in_progress / no override: deterministic
                            # spread across the scale's actual weights
                            # (0..len-1 since options are 0-indexed by
                            # sort_index in the default 5-point scale),
                            # keyed on indicator + participant index so
                            # re-runs stay stable.
                            target_weight = (ind_idx + part_idx * 2) % max(
                                1, len(scoring_options)
                            )

                        def _option_key(
                            o: AnswerOption, t: int = target_weight
                        ) -> tuple[int, int]:
                            return (abs((o.weight or 0) - t), o.sort_index)

                        option = min(scoring_options, key=_option_key)
                        db.add(
                            AssessmentAnswer(
                                assessment_id=assessment.id,
                                participant_id=participant.id,
                                indicator_id=indicator.id,
                                answer_option_id=option.id,
                                score=option.weight,
                            )
                        )

        await db.flush()

    pdp_count = 0
    for spec in localize(PDPS):
        employee = ctx.employees[spec["employee_index"]]
        title = spec["title"]
        existing_pdp = (
            await db.execute(
                select(PDP).where(
                    PDP.tenant_id == tenant_id,
                    PDP.employee_id == employee.id,
                    PDP.title == title,
                )
            )
        ).scalar_one_or_none()
        if existing_pdp is not None:
            continue

        started_at = finished_at = None
        if spec["status"] in {"in_progress", "review", "returned"}:
            started_at = now - timedelta(days=30)
        if spec["status"] in {"done", "cancelled"}:
            started_at = now - timedelta(days=90)
            finished_at = now - timedelta(days=7)

        deadline = (
            now + timedelta(days=60)
            if spec["status"] not in {"done", "cancelled"}
            else None
        )

        items = spec.get("items", [])
        passed = sum(1 for it in items if it.get("is_passed"))
        total = max(1, len(items))
        total_progress = int(round(passed / total * 100)) if items else 0

        # Only link the PDP back to an assessment that has actually
        # produced results (status='done'). Linking a review-stage PDP
        # to a draft assessment, as the earlier code did, surfaces a
        # broken "derived from <draft, no results>" chip on the PDP
        # detail page.
        linked_assessment = done_assessment_by_employee.get(spec["employee_index"])
        pdp = PDP(
            tenant_id=tenant_id,
            title=title,
            employee_id=employee.id,
            assessment_id=linked_assessment.id if linked_assessment else None,
            author_id=owner_user_id,
            reviewer_id=owner_user_id,
            status=spec["status"],
            specialization_id=ctx.specializations[spec["specialization_key"]].id,
            grade_id=ctx.grades[spec["grade_key"]].id,
            total_progress=total_progress,
            deadline=deadline,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(pdp)
        await db.flush()
        pdp_count += 1

        for idx, item_spec in enumerate(items):
            competence = ctx.competences.get(item_spec["competence_key"])
            db.add(
                PDPItem(
                    pdp_id=pdp.id,
                    competence_id=competence.id if competence is not None else None,
                    title=item_spec["title"],
                    sort_index=idx * 10,
                    is_passed=item_spec.get("is_passed", False),
                    entity_type="competence" if competence is not None else "custom",
                )
            )
        await db.flush()

    return (assessment_count, pdp_count)


async def _seed_exams(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    owner_user_id: uuid.UUID,
    now: datetime,
) -> int:
    """Materialise MassExams + Questions + Options + PassMarks + Exam
    assignments (HRP-281 / S5).

    Returns the number of MassExam rows seeded for the summary
    payload. Idempotent on ``(tenant_id, title)`` for MassExam.
    """
    seeded = 0
    for spec in localize(MASS_EXAMS):
        existing = (
            await db.execute(
                select(MassExam).where(
                    MassExam.tenant_id == tenant_id,
                    MassExam.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        started_at = ended_at = finished_at = None
        status = spec["status"]
        if status in {"sent", "in_progress", "done", "cancelled"}:
            started_at = now - timedelta(days=14)
            ended_at = now + timedelta(days=14)
        if status in {"done", "cancelled"}:
            finished_at = now - timedelta(days=2)

        mass_exam = MassExam(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec.get("description"),
            initiator_id=owner_user_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            finished_at=finished_at,
        )
        db.add(mass_exam)
        await db.flush()
        seeded += 1

        question_objs: list[ExamQuestion] = []
        for q_idx, q_spec in enumerate(spec["questions"]):
            question = ExamQuestion(
                mass_exam_id=mass_exam.id,
                title=q_spec["title"],
                question_type=q_spec["type"],
                sort_index=q_idx * 10,
                weight=1,
                is_active=True,
            )
            db.add(question)
            await db.flush()
            question_objs.append(question)

            for o_idx, opt_spec in enumerate(q_spec["options"]):
                db.add(
                    QuestionOption(
                        question_id=question.id,
                        title=opt_spec["title"],
                        sort_index=o_idx,
                        is_correct=opt_spec["is_correct"],
                    )
                )

        db.add(
            ExamPassMark(
                mass_exam_id=mass_exam.id,
                grade_id=None,
                specialization_id=None,
                min_score_percent=spec["pass_mark_percent"],
                min_score_points=None,
            )
        )
        await db.flush()

        total_questions = len(question_objs)
        for emp_idx, assignment_status, score_percent in spec["employee_indices"]:
            employee = ctx.employees[emp_idx]
            exam_started_at = exam_finished_at = None
            if assignment_status in {"in_progress", "done"}:
                exam_started_at = now - timedelta(days=5)
            if assignment_status == "done":
                exam_finished_at = now - timedelta(days=1)

            exam_score = None
            if score_percent is not None and total_questions:
                exam_score = int(round(score_percent * total_questions / 100))
            exam = Exam(
                tenant_id=tenant_id,
                mass_exam_id=mass_exam.id,
                employee_id=employee.id,
                status=assignment_status,
                score=exam_score,
                max_score=total_questions if total_questions else None,
                started_at=exam_started_at,
                finished_at=exam_finished_at,
            )
            db.add(exam)
            await db.flush()

            if assignment_status != "done":
                continue

            # For done assignments seed one ExamAnswer per question — pick
            # the first option (deterministically) and mark it correct
            # only when ``score_percent`` says we should hit it.
            target_correct = exam_score or 0
            for idx, question in enumerate(question_objs):
                # Re-fetch the question's first option via the existing
                # session — avoids a cross-relationship round-trip from
                # the seed.
                first_option = (
                    await db.execute(
                        select(QuestionOption)
                        .where(QuestionOption.question_id == question.id)
                        .order_by(QuestionOption.sort_index)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                is_correct = idx < target_correct
                db.add(
                    ExamAnswer(
                        exam_id=exam.id,
                        question_id=question.id,
                        selected_option_ids=(
                            [str(first_option.id)] if first_option else []
                        ),
                        is_correct=is_correct,
                        score=1 if is_correct else 0,
                    )
                )
            await db.flush()

    return seeded


async def _seed_talent_market(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    owner_user_id: uuid.UUID,
    now: datetime,
) -> int:
    """Materialise the Talent Market cards + relations (HRP-281 / S6).

    Returns the number of TalentCard rows seeded. Idempotent on
    ``(tenant_id, title)``.
    """
    today = now.date()
    seeded = 0
    for spec in localize(TALENT_CARDS):
        existing = (
            await db.execute(
                select(TalentCard).where(
                    TalentCard.tenant_id == tenant_id,
                    TalentCard.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        status = spec["status"]
        is_published = status in {"published", "completed"}
        published_at = now - timedelta(days=21) if is_published else None
        completed_at = now - timedelta(days=4) if status == "completed" else None
        cancelled_at = now - timedelta(days=10) if status == "cancelled" else None
        last_matched_at = (
            now - timedelta(days=2) if status in {"published", "completed"} else None
        )

        card = TalentCard(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec.get("description"),
            card_type=spec["card_type"],
            status=status,
            author_id=owner_user_id,
            division_id=ctx.divisions[spec["division_key"]].id,
            is_published=is_published,
            published_at=published_at,
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            start_date=today - timedelta(days=30),
            end_date=(
                today + timedelta(days=90)
                if status != "cancelled"
                else today - timedelta(days=5)
            ),
            match_percent=spec["match_percent"],
            last_matched_at=last_matched_at,
        )
        db.add(card)
        await db.flush()
        seeded += 1

        for s_spec in spec.get("specializations", []):
            db.add(
                TalentCardSpecialization(
                    card_id=card.id,
                    specialization_id=ctx.specializations[
                        s_spec["specialization_key"]
                    ].id,
                    grade_id=(
                        ctx.grades[s_spec["grade_key"]].id
                        if s_spec.get("grade_key")
                        else None
                    ),
                    min_experience_years=s_spec.get("min_years"),
                )
            )

        for c_spec in spec.get("competences", []):
            competence = ctx.competences.get(c_spec["competence_key"])
            skill_level = ctx.skill_levels.get(c_spec["skill_level_key"])
            if competence is None or skill_level is None:
                continue
            db.add(
                TalentCardCompetence(
                    card_id=card.id,
                    competence_id=competence.id,
                    skill_level_id=skill_level.id,
                    match_percent=c_spec.get("match_percent"),
                )
            )

        for r_spec in spec.get("requirements", []):
            db.add(
                TalentCardRequirement(
                    card_id=card.id,
                    description=r_spec["description"],
                    min_experience_years=r_spec.get("min_years"),
                )
            )

        for cand_spec in spec.get("candidates", []):
            employee = ctx.employees[cand_spec["employee_index"]]
            cand_status = cand_spec["status"]
            response_at = (
                now - timedelta(days=7)
                if cand_status in {"matched", "appointed"}
                else None
            )
            appointed_at = (
                now - timedelta(days=3) if cand_status == "appointed" else None
            )
            db.add(
                TalentCandidate(
                    card_id=card.id,
                    employee_id=employee.id,
                    status=cand_status,
                    match_score=cand_spec.get("match_score"),
                    response_at=response_at,
                    appointed_at=appointed_at,
                )
            )
        await db.flush()

    return seeded


async def _seed_recruitment_extras(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    owner_user_id: uuid.UUID,
    legacy_vacancies: dict[str, Vacancy],
    now: datetime,
    with_interviews: bool = True,
) -> tuple[int, int, int]:
    """Layer additional recruitment fixtures onto the base seed (S7).

    Returns ``(extra_vacancy_count, extra_candidate_count,
    extra_interview_count)``. Idempotent: vacancies are looked up by
    ``(tenant_id, title)``, candidates by ``(tenant_id, email,
    archived_at IS NULL)`` (which matches the partial unique index
    shipped by the recruitment migration).
    """
    extra_vacancies: dict[str, Vacancy] = dict(legacy_vacancies)
    vacancy_count = candidate_count = interview_count = 0

    for spec in localize(EXTRA_VACANCIES):
        existing_vac = (
            await db.execute(
                select(Vacancy).where(
                    Vacancy.tenant_id == tenant_id,
                    Vacancy.title == spec["title"],
                )
            )
        ).scalar_one_or_none()
        if existing_vac is not None:
            extra_vacancies[spec["key"]] = existing_vac
            continue
        anchor_division = ctx.divisions.get(spec.get("anchor_division_key", ""))
        vacancy = Vacancy(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec["description"],
            status=spec["status"],
            owner_id=owner_user_id,
            language=spec["language"],
            location=spec["location"],
            employment_type=spec["employment_type"],
            salary_min=spec["salary_min"],
            salary_max=spec["salary_max"],
            salary_currency=spec["salary_currency"],
            division_id=anchor_division.id if anchor_division is not None else None,
            tasks_main={"demo_investor": True, "key": spec["key"]},
        )
        db.add(vacancy)
        await db.flush()
        extra_vacancies[spec["key"]] = vacancy
        vacancy_count += 1

        db.add(
            VacancyProfile(
                tenant_id=tenant_id,
                vacancy_id=vacancy.id,
                profile_data=spec["profile"],
                version=1,
                language=spec["language"],
                generated_by="ai",
            )
        )
        await db.flush()

    # Keyed by candidate email → ``(CandidateVacancy, spec)`` so the
    # interview-creation pass below can pull the original spec without a
    # second lookup. The legacy ``_create_candidates`` helper at line
    # 1409 stores bare ``CandidateVacancy`` values under the same local
    # name; the shapes are intentionally different so don't unify the
    # two locals without rewriting both call sites.
    cv_for_interview: dict[str, tuple[CandidateVacancy, dict]] = {}
    for spec in localize(EXTRA_CANDIDATES):
        extra_vac = extra_vacancies.get(spec["vacancy_key"])
        if extra_vac is None:
            # Legacy vacancy key the base seed didn't carry — skip
            # rather than fan out a misleading orphan candidate.
            continue
        existing_cand = (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.email == spec["email"],
                    Candidate.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_cand is not None:
            continue
        candidate = Candidate(
            tenant_id=tenant_id,
            person_id=None,
            full_name=f"{spec['first_name']} {spec['last_name']}",
            email=spec["email"],
            location=spec.get("location"),
            current_position=spec.get("current_position"),
            years_of_experience=spec.get("years"),
            source=INVESTOR_MARKER,
            notes=translate("Investor demo candidate ({key}).").format(
                key=spec["vacancy_key"]
            ),
        )
        db.add(candidate)
        await db.flush()
        candidate_count += 1

        # ai_readiness is the funnel's signal that a transcript is
        # attached. When ``with_interviews=False`` the seed never
        # materialises the Interview row, so the badge must stay at
        # ``resume_only`` regardless of the spec's interview_kind —
        # otherwise the recruiter clicks through to a CV with no
        # corresponding Interview.
        if spec["interview_kind"] is not None and with_interviews:
            ai_readiness_value = "resume_and_transcript"
        else:
            ai_readiness_value = "resume_only"
        cv = CandidateVacancy(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            vacancy_id=extra_vac.id,
            status=spec["status"],
            attached_by=owner_user_id,
            ai_score=spec["ai_score"],
            # HRP-274: identity rebase — demo tenants carry no active
            # ScaleConfig, so normalized equals the raw 0..1 score.
            ai_score_normalized=spec["ai_score"],
            ai_readiness=ai_readiness_value,
            ai_verdict=spec["ai_verdict"],
            ai_verdict_summary=spec["ai_summary"],
            ai_key_strength=spec["ai_strength"],
            ai_key_risk=spec["ai_risk"],
            ai_risk_mitigation=spec["ai_mitigation"],
        )
        db.add(cv)
        await db.flush()

        if spec["interview_kind"] is not None:
            cv_for_interview[spec["email"]] = (cv, spec)

    if not with_interviews:
        return (vacancy_count, candidate_count, 0)

    localized_shapes = localize(INTERVIEW_SHAPES)
    for cv, spec in cv_for_interview.values():
        shape = localized_shapes[spec["interview_kind"]]
        interview_date = now - timedelta(days=shape["days_ago"])
        duration_minutes = shape["duration_minutes"]
        duration_seconds = duration_minutes * 60 if duration_minutes else None
        title = f"{shape['title_prefix']}{spec['first_name']} {spec['last_name']}"
        # interview_service filters archived rows by archived_at IS NULL
        # (not by status), so a seeded 'archived' row needs both columns
        # set to stay out of normal list/detail responses.
        archived_at = interview_date if shape["status"] == "archived" else None
        archived_by = owner_user_id if shape["status"] == "archived" else None
        db.add(
            Interview(
                tenant_id=tenant_id,
                candidate_vacancy_id=cv.id,
                interviewer_id=owner_user_id,
                interview_date=interview_date,
                duration_minutes=duration_minutes,
                duration_seconds=duration_seconds,
                title=title,
                type=shape["type"],
                status=shape["status"],
                transcript=shape["transcript"],
                transcription_status=shape["transcription_status"],
                transcription_provider=(
                    "seeded" if shape["transcription_status"] == "completed" else None
                ),
                analysis_status=shape["analysis_status"],
                analysis_data=None,
                archived_at=archived_at,
                archived_by=archived_by,
                notes=translate("Investor demo interview (S7 extras)."),
            )
        )
        interview_count += 1
    await db.flush()

    return (vacancy_count, candidate_count, interview_count)


async def _seed_misc(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    ctx: CompanyContext,
    *,
    owner_user_id: uuid.UUID,
    now: datetime,
) -> tuple[int, int]:
    """Drop in the small dictionary + notification fixtures (S8).

    Returns ``(dictionary_item_count, notification_count)``.

    Idempotent: dictionary items are upserted by
    ``(tenant_id, type, title)``; notifications by ``(tenant_id,
    recipient_id, template_id, context.subject_data)`` — the seed
    re-runs as a no-op for any row already present.
    """
    dict_count = 0
    for bucket in localize(CUSTOM_DICTIONARIES):
        for spec in bucket["items"]:
            existing = (
                await db.execute(
                    select(DictionaryItem).where(
                        DictionaryItem.tenant_id == tenant_id,
                        DictionaryItem.type == bucket["type"],
                        DictionaryItem.title == spec["title"],
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            db.add(
                DictionaryItem(
                    tenant_id=tenant_id,
                    type=bucket["type"],
                    title=spec["title"],
                    description=None,
                    sort_index=spec["sort_index"],
                    metadata_=DEMO_SEED_METADATA_MARKER,
                )
            )
            dict_count += 1
    await db.flush()

    # Cache template lookups so the loop doesn't do 10 round-trips.
    # Templates are pinned per locale (i18n F4); prefer the seed-locale
    # row per code and fall back to the English one so a template
    # missing its localized variant still produces a notification.
    template_codes = {n["template_code"] for n in NOTIFICATIONS}
    locale = seed_locale()
    template_rows = (
        (
            await db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.code.in_(template_codes),
                    NotificationTemplate.locale.in_({locale, "en"}),
                )
            )
        )
        .scalars()
        .all()
    )
    templates_by_code: dict[str, NotificationTemplate] = {}
    for t in template_rows:
        current = templates_by_code.get(t.code)
        if current is None or (t.locale == locale and current.locale != locale):
            templates_by_code[t.code] = t

    notification_count = 0
    for spec in localize(NOTIFICATIONS):
        template = templates_by_code.get(spec["template_code"])
        if template is None:
            continue
        sent_at = (
            now - timedelta(days=spec["days_ago"]) if spec["status"] == "sent" else None
        )
        # ``recipient_index`` lets a future NOTIFICATIONS entry target a
        # non-owner recipient (e.g. an employee user) without making the
        # dedup check miss and grow duplicate rows on every reseed. The
        # default points at the demo owner.
        recipient_index = spec.get("recipient_index")
        if recipient_index is None or not (
            0 <= recipient_index < len(ctx.employee_users)
        ):
            recipient_id = owner_user_id
        else:
            recipient_id = ctx.employee_users[recipient_index].id
        # Idempotency check: same tenant + recipient + template +
        # subject_data already in the table = skip. The recipient_id
        # comes from spec, not a hard-coded owner_user_id, so future
        # employee-recipient rows stay dedup-correct.
        existing_row: Any = (
            await db.execute(
                select(Notification.id).where(
                    Notification.tenant_id == tenant_id,
                    Notification.recipient_id == recipient_id,
                    Notification.template_id == template.id,
                    Notification.context["subject_data"].astext == spec["subject_data"],
                )
            )
        ).first()
        if existing_row is not None:
            continue
        db.add(
            Notification(
                tenant_id=tenant_id,
                template_id=template.id,
                recipient_id=recipient_id,
                status=spec["status"],
                context={"subject_data": spec["subject_data"]},
                is_read=spec["is_read"],
                sent_at=sent_at,
            )
        )
        notification_count += 1
    await db.flush()

    return (dict_count, notification_count)


async def _already_seeded(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    found = (
        await db.execute(
            select(Candidate.id)
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.source == INVESTOR_MARKER,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


async def _create_vacancies(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    owner_user_id: uuid.UUID,
    anchor_division_id: uuid.UUID | None,
) -> dict[str, Vacancy]:
    vacancy_objs: dict[str, Vacancy] = {}
    for spec in localize(VACANCIES):
        vacancy = Vacancy(
            tenant_id=tenant_id,
            title=spec["title"],
            description=spec["description"],
            status=spec["status"],
            owner_id=owner_user_id,
            language=spec["language"],
            location=spec["location"],
            employment_type=spec["employment_type"],
            salary_min=spec["salary_min"],
            salary_max=spec["salary_max"],
            salary_currency=spec["salary_currency"],
            # Only anchor the headline role to the engineering division;
            # the supporting roles stay unscoped so the demo still works
            # on a tenant with a single division.
            division_id=(
                anchor_division_id if spec["key"] == "senior-backend" else None
            ),
            tasks_main={"demo_investor": True, "key": spec["key"]},
        )
        db.add(vacancy)
        await db.flush()
        vacancy_objs[spec["key"]] = vacancy

        db.add(
            VacancyProfile(
                tenant_id=tenant_id,
                vacancy_id=vacancy.id,
                profile_data=spec["profile"],
                version=1,
                language=spec["language"],
                generated_by="ai",
            )
        )

    await db.flush()
    return vacancy_objs


async def _create_candidates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    owner_user_id: uuid.UUID,
    vacancy_objs: dict[str, Vacancy],
) -> dict[str, CandidateVacancy]:
    cv_for_interview: dict[str, CandidateVacancy] = {}
    for spec in localize(candidates()):
        # HRP-276 / H2: do not mint Person rows for demo seed candidates.
        # Person is a tenant-less global registry — every demo session
        # otherwise leaks 8 orphan rows that survive Tenant deletion
        # (CASCADE goes Person → Candidate, not the other way round).
        # Candidate.person_id has been nullable since HRP-181 REDO, and
        # all displayable fields (full_name, email, phone) are already
        # denormalised onto Candidate itself.
        candidate = Candidate(
            tenant_id=tenant_id,
            person_id=None,
            full_name=f"{spec['first_name']} {spec['last_name']}",
            email=spec["email"],
            phone=spec.get("phone"),
            location=spec.get("location"),
            current_position=spec.get("current_position"),
            years_of_experience=spec.get("years"),
            linkedin_url=spec.get("linkedin"),
            source=INVESTOR_MARKER,
            notes=translate("Investor demo candidate ({key}).").format(
                key=spec["vacancy_key"]
            ),
        )
        db.add(candidate)
        await db.flush()

        cv = CandidateVacancy(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            vacancy_id=vacancy_objs[spec["vacancy_key"]].id,
            status=spec["status"],
            attached_by=owner_user_id,
            ai_score=spec["ai_score"],
            # HRP-274: identity rebase — demo tenants carry no active
            # ScaleConfig, so normalized equals the raw 0..1 score.
            ai_score_normalized=spec["ai_score"],
            ai_readiness=(
                "resume_and_transcript" if spec["interview"] else "resume_only"
            ),
            ai_verdict=spec["ai_verdict"],
            ai_verdict_summary=spec["ai_summary"],
            ai_key_strength=spec["ai_strength"],
            ai_key_risk=spec["ai_risk"],
            ai_risk_mitigation=spec["ai_mitigation"],
        )
        db.add(cv)
        await db.flush()

        if spec["interview"]:
            # Key by the ASCII-only email instead of the display name so
            # any future Unicode normalisation on Person.first_name /
            # Candidate.full_name can't silently break the lookup below.
            cv_for_interview[spec["email"]] = cv

    return cv_for_interview


def _build_elena_interview(
    *,
    tenant_id: uuid.UUID,
    cv: CandidateVacancy,
    owner_user_id: uuid.UUID,
    now: datetime,
    transcript: str,
) -> Interview:
    return Interview(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv.id,
        interviewer_id=owner_user_id,
        interview_date=now - timedelta(days=2),
        duration_minutes=47,
        duration_seconds=47 * 60,
        title=translate("Technical + system design — Elena Volkov"),
        type="technical",
        status="completed",
        transcript=transcript,
        transcription_status="completed",
        transcription_provider="seeded",
        analysis_status="completed",
        analysis_data=localize(ELENA_INTERVIEW_ANALYSIS),
        notes=translate("Investor demo interview."),
    )


def _build_tomas_interview(
    *,
    tenant_id: uuid.UUID,
    cv: CandidateVacancy,
    owner_user_id: uuid.UUID,
    now: datetime,
) -> Interview:
    return Interview(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv.id,
        interviewer_id=owner_user_id,
        interview_date=now - timedelta(days=5),
        duration_minutes=42,
        duration_seconds=42 * 60,
        title=translate("Recruiter screen — Tomás Becker"),
        type="screen",
        status="completed",
        transcript=translate("[Transcript redacted for demo brevity.]"),
        transcription_status="completed",
        transcription_provider="seeded",
        analysis_status="completed",
        analysis_data=localize(TOMAS_INTERVIEW_ANALYSIS),
        notes=translate("Investor demo interview."),
    )


async def _maybe_seed_analysis_cache(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview,
) -> None:
    """Pre-populate ``InterviewAnalysisCache`` for the Elena seed.

    Skipped (no-op) when the cache key can't be computed — typically
    because the seed didn't lay down a ``VacancyProfile`` row for the
    target vacancy. A demo session then still works (re-analyze falls
    through to the killswitch path), it just doesn't get the cached
    fast-path on first click.
    """
    from app.modules.recruitment.analysis_cache_service import (
        compute_cache_key_for_interview,
        store_cached_analysis,
    )
    from app.modules.recruitment.common import normalize_competence_id
    from app.modules.recruitment.tasks.demo_analysis import (
        _DEMO_VERDICT_TO_SCORE,
        _DEMO_VERDICT_TO_STATUS,
    )

    try:
        cache_key = await compute_cache_key_for_interview(db, tenant_id, interview)
    except Exception:  # noqa: BLE001
        logger.exception(
            "demo seed: cache-key compute failed for interview %s", interview.id
        )
        return
    if cache_key is None:
        return

    # Localized copy so the cache-hit payload matches the localized
    # ``analysis_data`` stored on the seeded Interview row.
    elena_analysis = localize(ELENA_INTERVIEW_ANALYSIS)
    assessments: list[dict] = []
    for ca in elena_analysis.get("competence_assessments", []) or []:
        label = (ca.get("competence") or "").strip()
        slug = (ca.get("competence_id") or "").strip()
        verdict = (ca.get("verdict") or "unknown").lower()
        if not slug:
            # HRP-275: cache pre-population must key off the same slug
            # the killswitch and the Compact matrix use; without it the
            # cache-hit branch would resurrect the label-derived UUIDs
            # the rest of the system stopped recognising.
            logger.warning(
                "demo seed: skipping cache assessment for %r — missing competence_id slug",
                label,
            )
            continue
        comp_uuid = normalize_competence_id(slug)
        if comp_uuid is None:
            continue
        assessments.append(
            {
                "competence_id": str(comp_uuid),
                "score": _DEMO_VERDICT_TO_SCORE.get(verdict, 0.0),
                "status": _DEMO_VERDICT_TO_STATUS.get(verdict, "not_covered"),
                "citations": [
                    {
                        "competence": label,
                        "quote": ca.get("evidence") or "",
                        "verdict": verdict,
                    }
                ],
                "reasoning": ca.get("evidence") or "",
            }
        )

    try:
        await store_cached_analysis(
            db,
            tenant_id,
            cache_key,
            elena_analysis,
            assessments,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "demo seed: failed to pre-populate analysis cache for tenant %s",
            tenant_id,
        )


async def clone_seed_into_demo_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    owner_user_id: uuid.UUID,
    anchor_division_id: uuid.UUID | None = None,
    with_completed_interviews: bool = True,
    require_demo_tenant: bool = True,
) -> dict[str, int]:
    """Lay down the investor demo fixtures on the given tenant.

    Idempotent: a second call against the same tenant short-circuits
    after the marker check and returns the existing-marker summary so
    callers don't accidentally double-seed.

    Parameters
    ----------
    db:
        Async session owned by the caller. We do not commit; the caller
        owns the transaction boundary.
    tenant_id:
        Target tenant. Must already exist with at least one user.
    owner_user_id:
        Used as ``Vacancy.owner_id`` / ``CandidateVacancy.attached_by``
        / ``Interview.interviewer_id`` on every seeded row.
    anchor_division_id:
        Optional. When omitted we pick the first engineering-shaped
        division on the tenant (with a deterministic ordering fallback),
        or leave the headline vacancy without a division if none exists.
    with_completed_interviews:
        Toggle the two completed-interview rows (Elena + Tomás). Off by
        default would make the demo's "ready AI assessment" first-screen
        impossible — keep it on unless you specifically want the
        pre-interview state.
    require_demo_tenant:
        When True (default) raise ``ValueError`` if the target tenant is
        not flagged ``is_demo=True``. The hosted ``POST /api/demo/start``
        flow (D3) leaves this on — a misrouted call must NOT pollute a
        real customer tenant with fake candidates named "Elena Volkov".
        The self-hosted CLI seeds on top of the long-lived Pulsar
        Technologies tenant and explicitly passes False.

    Returns
    -------
    dict
        ``{"vacancies": int, "candidates": int, "interviews": int,
        "skipped": bool}``.
    """
    if require_demo_tenant:
        is_demo = (
            await db.execute(select(Tenant.is_demo).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if is_demo is None:
            raise ValueError(f"Tenant {tenant_id} not found.")
        if not is_demo:
            raise ValueError(
                f"Tenant {tenant_id} is not flagged is_demo=true; "
                "pass require_demo_tenant=False to seed an existing non-demo "
                "tenant (used by the self-hosted CLI)."
            )

    if await _already_seeded(db, tenant_id):
        logger.info(
            "demo seed: tenant %s already carries investor fixtures, skipping",
            tenant_id,
        )
        return {
            "vacancies": 0,
            "candidates": 0,
            "interviews": 0,
            "divisions": 0,
            "positions": 0,
            "competences": 0,
            "employees": 0,
            "assessments": 0,
            "pdps": 0,
            "mass_exams": 0,
            "talent_cards": 0,
            "extra_dictionary_items": 0,
            "notifications": 0,
            "skipped": True,
        }

    # HRP-281 / S1: lay down the company structure first so vacancies
    # have a real Engineering division to anchor on and downstream
    # employee seeders (S3) have positions to point at.
    company_ctx = await _seed_company_structure(db, tenant_id)

    # HRP-281 / S2: tenant-scoped competence ladder + skill levels +
    # grade × competence links (the Competences page is otherwise
    # empty in a fresh demo session).
    await _seed_competences(db, tenant_id, company_ctx)

    if anchor_division_id is None:
        anchor_division_id = company_ctx.anchor_division_id
    if anchor_division_id is None:
        anchor = await _pick_anchor_division(db, tenant_id)
        anchor_division_id = anchor.id if anchor is not None else None

    now = datetime.now(timezone.utc)

    # HRP-281 / S3: 40 employees + their backing users, with division
    # leadership wired up (manager_id / deputy_manager_id).
    await _seed_employees(db, tenant_id, company_ctx, now=now)

    # HRP-281 / S4: assessment cycles + PDPs covering every status.
    assessment_count, pdp_count = await _seed_assessments_and_pdps(
        db,
        tenant_id,
        company_ctx,
        owner_user_id=owner_user_id,
        now=now,
    )

    # HRP-281 / S5: mass exams + questions + assignments + results.
    mass_exam_count = await _seed_exams(
        db,
        tenant_id,
        company_ctx,
        owner_user_id=owner_user_id,
        now=now,
    )

    # HRP-281 / S6: Talent Market cards with matched candidates.
    talent_card_count = await _seed_talent_market(
        db,
        tenant_id,
        company_ctx,
        owner_user_id=owner_user_id,
        now=now,
    )
    vacancy_objs = await _create_vacancies(
        db,
        tenant_id,
        owner_user_id=owner_user_id,
        anchor_division_id=anchor_division_id,
    )
    cv_for_interview = await _create_candidates(
        db,
        tenant_id,
        owner_user_id=owner_user_id,
        vacancy_objs=vacancy_objs,
    )

    interview_count = 0
    elena_interview = None
    if with_completed_interviews:
        transcript = load_transcript()
        elena_cv = cv_for_interview.get(_ELENA_KEY)
        if elena_cv is not None:
            elena_interview = _build_elena_interview(
                tenant_id=tenant_id,
                cv=elena_cv,
                owner_user_id=owner_user_id,
                now=now,
                transcript=transcript,
            )
            db.add(elena_interview)
            interview_count += 1
        tomas_cv = cv_for_interview.get(_TOMAS_KEY)
        if tomas_cv is not None:
            db.add(
                _build_tomas_interview(
                    tenant_id=tenant_id,
                    cv=tomas_cv,
                    owner_user_id=owner_user_id,
                    now=now,
                )
            )
            interview_count += 1
        await db.flush()

        # HRP-276 / L3: pre-populate the analysis cache for Elena so a
        # re-analyze from the demo SPA hits the cache instead of either
        # the LLM (cost) or the killswitch overwrite path (slower UX).
        # Skipped silently if the vacancy profile that drives the cache
        # key isn't present — the seed doesn't ship a VacancyProfile row.
        if elena_interview is not None:
            await _maybe_seed_analysis_cache(db, tenant_id, elena_interview)

    # HRP-281 / S7: extra vacancies + candidates + interview rows in
    # the non-completed states so the recruitment funnel is no longer
    # a two-row demo of the AI analysis screen alone. The
    # ``with_completed_interviews=False`` opt-out is respected — when
    # off, the extras still seed vacancies + candidates but skip every
    # Interview row.
    extra_vac_count, extra_cand_count, extra_iv_count = await _seed_recruitment_extras(
        db,
        tenant_id,
        company_ctx,
        owner_user_id=owner_user_id,
        legacy_vacancies=vacancy_objs,
        now=now,
        with_interviews=with_completed_interviews,
    )

    # HRP-281 / S8: small page-finishers — custom DictionaryItem rows
    # in the language / certification / office_location types, plus
    # in-app Notification rows so the notification bell isn't empty.
    dict_count, notification_count = await _seed_misc(
        db,
        tenant_id,
        company_ctx,
        owner_user_id=owner_user_id,
        now=now,
    )

    return {
        "vacancies": len(vacancy_objs) + extra_vac_count,
        "candidates": len(candidates()) + extra_cand_count,
        "interviews": interview_count + extra_iv_count,
        "divisions": len(company_ctx.divisions),
        "positions": len(company_ctx.positions),
        "competences": len(company_ctx.competences),
        "employees": len(company_ctx.employees),
        "assessments": assessment_count,
        "pdps": pdp_count,
        "mass_exams": mass_exam_count,
        "talent_cards": talent_card_count,
        "extra_dictionary_items": dict_count,
        "notifications": notification_count,
        "skipped": False,
    }
