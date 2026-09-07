"""HRP-733: creating an assessment for one employee fills in its criteria
and rating scale in the same transaction.

The Create assessment dialog used to leave a bare draft behind: HR then had
to pick the evaluation criteria, pick a scale and only then send it. Doing
the two obvious ones at creation time removes three round trips and, more
importantly, means the assessment never exists in a half-configured state.

The prefill is opt-in (``apply_position_criteria``) so mass creation, group
children and API clients keep getting the bare draft they always got.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from app.modules.assessment import service
from app.modules.assessment.models import AnswerScale
from app.modules.assessment.schemas import AssessmentCreate
from app.modules.dictionary.models import DictionaryItem
from app.modules.position.models import Position
from sqlalchemy import select

from tests.unit.test_passing_score import (
    _link_competence,
    _make_competence,
    _make_grade_specialization,
    _make_skill_level,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_scales(db):
    """Drop the scales this module creates.

    The unit test database is shared across the session and answer scales
    are not tenant-scoped, so a global default left behind here would be
    picked up by every later test — the demo-seed suite in particular.
    """
    before = set(
        (await db.execute(select(AnswerScale.id))).scalars().all()
    )
    yield
    # Clear the flag rather than deleting the row: assessments created by
    # the test point at these scales, and an unflagged leftover scale is
    # invisible to every default lookup.
    after = (await db.execute(select(AnswerScale))).scalars().all()
    for scale in after:
        if scale.id not in before and scale.is_default:
            scale.is_default = False
    await db.commit()


async def _dict_item(db, tenant, type_: str, title: str) -> DictionaryItem:
    item = DictionaryItem(tenant_id=tenant.id, type=type_, title=title, is_active=True)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _scale(db, *, tenant_id, title, is_default, is_snapshot=False) -> AnswerScale:
    scale = AnswerScale(
        tenant_id=tenant_id,
        title=title,
        is_default=is_default,
        is_snapshot=is_snapshot,
    )
    db.add(scale)
    await db.commit()
    await db.refresh(scale)
    return scale


async def _global_default_scale(db) -> AnswerScale:
    """The seeded global default — get-or-create.

    A partial unique index allows exactly one of these, which is also what
    production looks like, so tests must reuse the row rather than add a
    second one.
    """
    existing = (
        await db.execute(
            select(AnswerScale).where(
                AnswerScale.tenant_id.is_(None),
                AnswerScale.is_default.is_(True),
                AnswerScale.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await _scale(db, tenant_id=None, title="Standard", is_default=True)


async def _employee_on_a_position(db, tenant, employee):
    """Give the employee a position wired to a one-competence grade matrix."""
    spec = await _dict_item(db, tenant, "specialization", "Sales")
    grade = await _dict_item(db, tenant, "grade", "Middle")
    skill_level = await _make_skill_level(db, "Basic", 0)
    competence = await _make_competence(db, tenant, "Product knowledge")
    gs = await _make_grade_specialization(
        db, tenant, spec_id=spec.id, grade_id=grade.id, sort_index=1
    )
    await _link_competence(
        db, gs_id=gs.id, competence_id=competence.id, skill_level_id=skill_level.id
    )
    position = Position(
        tenant_id=tenant.id,
        title="Sales manager",
        source="manual",
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(position)
    await db.flush()
    employee.position_id = position.id
    await db.commit()
    return competence


@pytest.mark.asyncio
class TestHRP733CreationDefaults:
    async def test_prefills_criteria_and_the_default_scale(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        competence = await _employee_on_a_position(db, tenant, employee)
        default_scale = await _global_default_scale(db)

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Competence assessment",
                employee_id=employee.id,
                type_code="self",
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["criteria_type"] == "current_positions"
        assert detail["competence_ids"] == [competence.id]
        assert detail["scale_id"] == default_scale.id
        # The bar snapshot follows the same rules as PUT /criteria.
        assert detail["passing_score"] == service.DEFAULT_PASSING_SCORE

    async def test_employee_without_a_position_gets_no_criteria(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """No position, no criteria — and that is the dialog's warning cue.

        A NULL criteria_type is what tells the caller "these could not be
        filled in, pick them by hand"; creation itself must still succeed.
        """
        default_scale = await _global_default_scale(db)
        employee.position_id = None
        await db.commit()

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["criteria_type"] is None
        assert detail["competence_ids"] == []
        # The scale is independent of the position, so it is still filled.
        assert detail["scale_id"] == default_scale.id

    async def test_position_without_competences_gets_no_criteria(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """A position whose grade matrix is empty behaves like no position."""
        spec = await _dict_item(db, tenant, "specialization", "Empty")
        grade = await _dict_item(db, tenant, "grade", "Junior")
        position = Position(
            tenant_id=tenant.id,
            title="Unmapped role",
            source="manual",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(position)
        await db.flush()
        employee.position_id = position.id
        await db.commit()

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["criteria_type"] is None
        assert detail["competence_ids"] == []

    async def test_prefill_is_off_unless_asked_for(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Mass creation and API clients keep getting a bare draft."""
        await _employee_on_a_position(db, tenant, employee)
        await _global_default_scale(db)

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(employee_id=employee.id, type_code="self"),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["criteria_type"] is None
        assert detail["scale_id"] is None

    async def test_tenant_default_scale_wins_over_the_global_one(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """"The scale the tenant configured" means exactly that."""
        await _employee_on_a_position(db, tenant, employee)
        await _global_default_scale(db)
        tenant_scale = await _scale(
            db, tenant_id=tenant.id, title="Our scale", is_default=True
        )

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["scale_id"] == tenant_scale.id

    async def test_snapshot_scales_are_never_offered(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """A frozen copy of a scale must not be handed to a new assessment."""
        await _employee_on_a_position(db, tenant, employee)
        await _scale(
            db,
            tenant_id=tenant.id,
            title="Frozen",
            is_default=True,
            is_snapshot=True,
        )
        global_scale = await _global_default_scale(db)

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["scale_id"] == global_scale.id

    async def test_an_explicit_scale_is_not_overwritten(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        await _employee_on_a_position(db, tenant, employee)
        await _global_default_scale(db)
        chosen = await _scale(
            db, tenant_id=tenant.id, title="Chosen by hand", is_default=False
        )

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                scale_id=chosen.id,
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["scale_id"] == chosen.id

    async def test_explicit_specialization_and_grade_are_kept(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """A target named in the payload outranks the position prefill.

        The prefill answers "measure them against the position they hold";
        a caller who already said which specialization and grade to measure
        against has answered that question themselves, and the criteria are
        left for them to set.
        """
        await _employee_on_a_position(db, tenant, employee)
        default_scale = await _global_default_scale(db)
        spec = await _dict_item(db, tenant, "specialization", "Target")
        grade = await _dict_item(db, tenant, "grade", "Senior")

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                employee_id=employee.id,
                type_code="self",
                specialization_id=spec.id,
                grade_id=grade.id,
                apply_position_criteria=True,
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["specialization_id"] == spec.id
        assert detail["grade_id"] == grade.id
        assert detail["criteria_type"] is None
        # The scale does not depend on the target, so it is still filled.
        assert detail["scale_id"] == default_scale.id
