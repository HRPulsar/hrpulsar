"""HRP-210: Experience match falls back to the employee's current Position.

Without this fallback, an employee whose current job lines up with the
card's Required specialization but who has no logged WorkExperience row
shows up as "no experience" (red) — recruiters then dismiss them as a
mismatch when they're really a perfect fit. HRP-210 adds the current
Position fallback:

* if a matching WorkExperience row exists → existing behaviour (green
  with tenure, red below the floor);
* else if ``Employee.position`` (via ``position_id``) matches → match
  drawer surfaces "Current position" muted, the Match cell shows
  "has experience" greyed, and the per-axis ``qualifies`` flag flips
  to True when the spec has no ``min_experience_years`` floor;
* else → existing "no experience" muted chip.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee, WorkExperience
from app.modules.position.models import Position
from app.modules.talent_market import service
from app.modules.talent_market.schemas import (
    TalentCardCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import (
    _make_employee,
)


async def _make_spec_and_grade(
    db: AsyncSession, tenant
) -> tuple[DictionaryItem, DictionaryItem]:
    spec = DictionaryItem(
        type="specialization",
        tenant_id=tenant.id,
        title=f"Spec-{uuid.uuid4().hex[:4]}",
        is_active=True,
    )
    grade = DictionaryItem(
        type="grade",
        tenant_id=tenant.id,
        title=f"Grade-{uuid.uuid4().hex[:4]}",
        is_active=True,
    )
    db.add_all([spec, grade])
    await db.flush()
    return spec, grade


async def _attach_position(
    db: AsyncSession,
    tenant,
    employee_id: uuid.UUID,
    spec: DictionaryItem,
    grade: DictionaryItem,
) -> Position:
    pos = Position(
        tenant_id=tenant.id,
        title=f"Pos-{uuid.uuid4().hex[:4]}",
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(pos)
    await db.flush()
    emp = await db.get(Employee, employee_id)
    assert emp is not None
    emp.position_id = pos.id
    await db.commit()
    await db.refresh(emp)
    return pos


async def _attach_required_spec(
    db: AsyncSession,
    tenant,
    card_id: uuid.UUID,
    spec: DictionaryItem,
    grade: DictionaryItem,
    *,
    min_years: int | None = None,
) -> uuid.UUID:
    """Insert a TalentCardSpecialization without going through the
    GradeSpecialization validation (which the HRP-87 add API enforces).
    Keeps the test focused on the matcher without dragging in the grade-
    system fixture wiring."""
    from app.modules.talent_market.models import TalentCardSpecialization

    row = TalentCardSpecialization(
        card_id=card_id,
        specialization_id=spec.id,
        grade_id=grade.id,
        min_experience_years=min_years,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.id


async def test_current_position_fallback_marks_has_experience(
    db: AsyncSession, tenant, user
) -> None:
    """Employee with no WorkExperience but current position matching the
    Required spec shows up as exp_via_current_position=True in the pool."""
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    spec, grade = await _make_spec_and_grade(db, tenant)
    await _attach_required_spec(db, tenant, card_dict["id"], spec, grade)

    emp = await _make_employee(db, tenant.id, name="CurrentOnly")
    await _attach_position(db, tenant, emp.id, spec, grade)

    items = await service.list_candidate_pool(
        db, tenant.id, card_dict["id"], include_attached=False
    )
    ours = next(it for it in items if it["employee_id"] == emp.id)
    assert ours["exp_via_current_position"] is True
    assert ours["exp_months"] is None
    assert ours["exp_qualifies"] is True
    # With no Required competences the spec match alone qualifies them.
    assert ours["status"] == "matched"


async def test_current_position_skipped_when_work_experience_present(
    db: AsyncSession, tenant, user
) -> None:
    """If a WorkExperience row already covers the spec, the fallback
    must stay off (the chip shows tenure, not "Current position")."""
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    spec, grade = await _make_spec_and_grade(db, tenant)
    await _attach_required_spec(db, tenant, card_dict["id"], spec, grade)

    emp = await _make_employee(db, tenant.id, name="Both")
    pos = await _attach_position(db, tenant, emp.id, spec, grade)
    # Real WorkExperience tenure on the same position.
    we = WorkExperience(
        tenant_id=tenant.id,
        employee_id=emp.id,
        position_id=pos.id,
        start_date=date(2023, 1, 1),
        end_date=date(2024, 1, 1),
    )
    db.add(we)
    await db.commit()

    items = await service.list_candidate_pool(
        db, tenant.id, card_dict["id"], include_attached=False
    )
    ours = next(it for it in items if it["employee_id"] == emp.id)
    assert ours["exp_via_current_position"] is False
    assert ours["exp_months"] is not None and ours["exp_months"] > 0


async def test_current_position_fallback_does_not_qualify_with_min_years(
    db: AsyncSession, tenant, user
) -> None:
    """Current position alone can't prove a multi-year tenure — the
    spec stays unqualified when min_experience_years is set."""
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    spec, grade = await _make_spec_and_grade(db, tenant)
    await _attach_required_spec(
        db, tenant, card_dict["id"], spec, grade, min_years=3
    )

    emp = await _make_employee(db, tenant.id, name="FreshHire")
    await _attach_position(db, tenant, emp.id, spec, grade)

    items = await service.list_candidate_pool(
        db, tenant.id, card_dict["id"], include_attached=False
    )
    ours = next(it for it in items if it["employee_id"] == emp.id)
    # Picker still surfaces the current-position fallback for the chip,
    # but the qualification gate stays off because we can't prove tenure.
    assert ours["exp_via_current_position"] is True
    assert ours["exp_qualifies"] is False


async def test_breakdown_marks_current_position_on_spec_row(
    db: AsyncSession, tenant, user
) -> None:
    """Match drawer payload labels the spec row with current_position_match."""
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    spec, grade = await _make_spec_and_grade(db, tenant)
    await _attach_required_spec(db, tenant, card_dict["id"], spec, grade)

    emp = await _make_employee(db, tenant.id, name="DrawerEmp")
    await _attach_position(db, tenant, emp.id, spec, grade)

    payload = await service.get_candidate_breakdown(
        db, tenant.id, card_dict["id"], emp.id
    )
    assert len(payload["specializations"]) == 1
    spec_row = payload["specializations"][0]
    assert spec_row["current_position_match"] is True
    assert spec_row["actual_months"] is None
    assert spec_row["qualifies"] is True


async def test_breakdown_marks_current_position_even_when_min_years_set(
    db: AsyncSession, tenant, user
) -> None:
    """HRP-210 REDO (2026-06-09): the drawer must label the spec row as
    ``Current position`` whenever the employee's current Position lines
    up with the spec, even when the spec has a non-zero
    ``min_experience_years``. The qualifies verdict still respects the
    floor — only the label flips."""
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    spec, grade = await _make_spec_and_grade(db, tenant)
    await _attach_required_spec(
        db, tenant, card_dict["id"], spec, grade, min_years=3
    )

    emp = await _make_employee(db, tenant.id, name="FreshDrawer")
    await _attach_position(db, tenant, emp.id, spec, grade)

    payload = await service.get_candidate_breakdown(
        db, tenant.id, card_dict["id"], emp.id
    )
    spec_row = payload["specializations"][0]
    assert spec_row["current_position_match"] is True
    assert spec_row["actual_months"] is None
    # Min-years floor isn't satisfied by the current-position fallback —
    # qualifies stays False so the chip stays red.
    assert spec_row["qualifies"] is False
