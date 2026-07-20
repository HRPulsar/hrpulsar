"""HRP-183 (REDO #2): the assessment detail payload must round-trip the
explicit passing_score the user typed in the Evaluation criteria sheet.

The original REDO mistakenly initialised the form input from a constant on
every open, hiding the previously saved value from HR. The frontend now
seeds the input from ``initial.passing_score`` — these tests pin the
server-side guarantee that the value the form reads back is exactly what
was stored.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment import service
from app.modules.assessment.schemas import (
    AssessmentCreate,
    CriteriaUpdate,
)
from app.modules.competence.models import SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import GradeSpecialization

from tests.unit.test_passing_score import (
    _link_competence,
    _make_competence,
    _make_grade_specialization,
    _make_skill_level,
)


async def _make_dict_item(db, tenant, type_: str, title: str) -> DictionaryItem:
    item = DictionaryItem(tenant_id=tenant.id, type=type_, title=title, is_active=True)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@pytest.mark.asyncio
class TestHRP183PassingScoreRoundtrip:
    async def test_target_position_explicit_value_survives_reopen(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """Save an explicit 95 then re-fetch — the detail must report 95.

        Before the fix the assessment page would read 75 from the form
        default and silently overwrite the saved 95 if the user pressed
        Save without editing the input again.
        """
        spec = await _make_dict_item(db, tenant, "specialization", "Backend")
        grade = await _make_dict_item(db, tenant, "grade", "Senior")
        skill_level: SkillLevel = await _make_skill_level(db, "L1", 1)
        comp = await _make_competence(db, tenant, "C-RT")
        gs: GradeSpecialization = await _make_grade_specialization(
            db,
            tenant,
            spec_id=spec.id,
            grade_id=grade.id,
            sort_index=1,
            passing_score=80,
        )
        await _link_competence(
            db, gs_id=gs.id, competence_id=comp.id, skill_level_id=skill_level.id
        )
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Reopen-explicit",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=grade.id,
                passing_score=95,
            ),
        )

        detail = await service.get_assessment_detail(
            db, tenant.id, uuid.UUID(str(created["id"]))
        )
        assert detail["passing_score"] == 95

    async def test_current_positions_explicit_value_survives_reopen(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        """current_positions also stores an explicit override (not just 75)."""
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="CP-Reopen",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(criteria_type="current_positions", passing_score=88),
        )
        detail = await service.get_assessment_detail(
            db, tenant.id, uuid.UUID(str(created["id"]))
        )
        assert detail["passing_score"] == 88
