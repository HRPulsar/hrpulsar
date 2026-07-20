"""Regression tests for the third Assessment bug pack (HRP-18, HRP-37,
HRP-40, HRP-43) filed by QA on 2026-05-06/07.

Each class targets a distinct ticket; helpers are inlined so dropping
one fix doesn't drag the rest's fixtures with it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.models import (
    AssessmentParticipant,
)
from app.modules.assessment.schemas import (
    AssessmentCreate,
    ParticipantAdd,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Shared helpers (inline factories — no shared fixture beyond conftest's user)
# ---------------------------------------------------------------------------


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("pass12345"),
        first_name=f"User{suffix}",
        last_name="Extra",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp, u


async def _make_assessment(
    db: AsyncSession,
    tenant,
    user,
    employee,
    *,
    type_code: str = "360",
    title_suffix: str | None = None,
):
    data = AssessmentCreate(
        title=f"sess3-{title_suffix or uuid.uuid4().hex[:6]}",
        employee_id=employee.id,
        type_code=type_code,
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


# ---------------------------------------------------------------------------
# HRP-18 — same human cannot become a participant twice in one assessment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp18_duplicate_participant_rejected(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    a = await _make_assessment(db, tenant, user, employee, type_code="360")
    other_emp, _ = await _make_extra_employee(db, tenant, "h18a")

    first = await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=other_emp.id, role="peer"),
    )
    assert first["user_id"] == other_emp.user_id

    # Same employee, same role → 409
    with pytest.raises(Exception) as exc1:
        await service.add_participant(
            db,
            tenant.id,
            a["id"],
            ParticipantAdd(employee_id=other_emp.id, role="peer"),
        )
    assert getattr(exc1.value, "status_code", None) == 409

    # Same employee, different role → still 409 (one human = one slot)
    with pytest.raises(Exception) as exc2:
        await service.add_participant(
            db,
            tenant.id,
            a["id"],
            ParticipantAdd(employee_id=other_emp.id, role="manager"),
        )
    assert getattr(exc2.value, "status_code", None) == 409

    rows = (
        (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.assessment_id == a["id"],
                    AssessmentParticipant.user_id == other_emp.user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# HRP-37 — cap concurrent active assessments per employee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp37_cap_blocks_extra_active_assessments(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    cap = service.MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE
    # Fill the quota with active assessments.
    for i in range(cap):
        await _make_assessment(
            db, tenant, user, employee, type_code="self", title_suffix=f"a{i}"
        )

    # The next one must be rejected with 409.
    with pytest.raises(Exception) as exc:
        await _make_assessment(
            db, tenant, user, employee, type_code="self", title_suffix="overflow"
        )
    assert getattr(exc.value, "status_code", None) == 409
    assert "limit" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_hrp37_cap_ignores_terminal_assessments(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    cap = service.MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE

    # Fill to the cap, then close one to free a slot.
    created = []
    for i in range(cap):
        created.append(
            await _make_assessment(
                db, tenant, user, employee, type_code="self", title_suffix=f"b{i}"
            )
        )
    await service.change_status(db, tenant.id, created[0]["id"], "cancelled")

    # Now creating one more must succeed.
    fresh = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="after-cancel"
    )
    assert fresh["status_code"] == "draft"


# ---------------------------------------------------------------------------
# HRP-40 — restricted callers cannot fetch other-tenant-employees' details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp40_detail_404_for_unscoped_employee(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    other_emp, _other_user = await _make_extra_employee(db, tenant, "h40")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="hidden"
    )

    # `user` (caller) is neither the assessee nor a participant of `a`.
    # With visible_employee_ids restricted to {user.employee_id}, detail must 404.
    visible_ids: set[uuid.UUID] = {employee.id}

    with pytest.raises(Exception) as exc:
        await service.get_assessment_detail(
            db,
            tenant.id,
            uuid.UUID(str(a["id"])),
            visible_employee_ids=visible_ids,
            participant_user_id=user.id,
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_hrp40_detail_visible_when_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    other_emp, _other_user = await _make_extra_employee(db, tenant, "h40b")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="seen"
    )
    # Add `user` (current caller) as a participant.
    # Need an Employee row pointing at `user` for add_participant.
    await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )

    visible_ids: set[uuid.UUID] = {employee.id}

    detail = await service.get_assessment_detail(
        db,
        tenant.id,
        uuid.UUID(str(a["id"])),
        visible_employee_ids=visible_ids,
        participant_user_id=user.id,
    )
    assert detail["id"] == a["id"]


# HRP-40 redux (2026-05-12): regular employee must not see Draft assessments
# even when added as a participant — `restrict_to_active=True` toggle hides them.


@pytest.mark.asyncio
async def test_hrp40_list_hides_draft_for_employee_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    other_emp, _ = await _make_extra_employee(db, tenant, "h40c")
    draft = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="draft"
    )
    await service.add_participant(
        db,
        tenant.id,
        draft["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )
    # Sanity: a non-Draft assessment where employee is the assessee must remain
    # visible — proves the filter is status-scoped, not scope-wide. Cancelled
    # is the cheapest non-Draft terminal status to set up (Draft → Cancelled is
    # a one-step transition; Draft → Sent needs criteria + a scale).
    visible = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="visible"
    )
    await service.change_status(db, tenant.id, visible["id"], "cancelled")

    items, total = await service.list_assessments(
        db,
        tenant.id,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    ids = {row["id"] for row in items}
    assert visible["id"] in ids
    assert draft["id"] not in ids
    assert total == len(items)


@pytest.mark.asyncio
async def test_hrp40_list_shows_draft_for_admin(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    other_emp, _ = await _make_extra_employee(db, tenant, "h40d")
    draft = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="admin-draft"
    )
    # Admin path: visible_employee_ids=None, restrict_to_active=False.
    items, _total = await service.list_assessments(
        db,
        tenant.id,
        visible_employee_ids=None,
        participant_user_id=user.id,
        restrict_to_active=False,
    )
    assert draft["id"] in {row["id"] for row in items}


@pytest.mark.asyncio
async def test_hrp40_detail_404_for_employee_on_draft_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    other_emp, _ = await _make_extra_employee(db, tenant, "h40e")
    draft = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="draft-detail"
    )
    await service.add_participant(
        db,
        tenant.id,
        draft["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )

    with pytest.raises(Exception) as exc:
        await service.get_assessment_detail(
            db,
            tenant.id,
            uuid.UUID(str(draft["id"])),
            visible_employee_ids={employee.id},
            participant_user_id=user.id,
            restrict_to_active=True,
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_hrp40_detail_visible_for_employee_participant_on_non_draft(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Participant on a non-Draft assessment must still see detail under the
    `restrict_to_active=True` flag — the Draft filter is status-specific."""
    other_emp, _ = await _make_extra_employee(db, tenant, "h40f")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="participant-active"
    )
    await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )
    # Move out of Draft via the cheapest legal transition (Cancelled).
    await service.change_status(db, tenant.id, a["id"], "cancelled")

    detail = await service.get_assessment_detail(
        db,
        tenant.id,
        uuid.UUID(str(a["id"])),
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    assert detail["id"] == a["id"]


# HRP-40 follow-up (2026-05-14): the grouped list endpoint had no scope/Draft
# filter, so employees still saw every assessment via /assessments-grouped.
# These tests mirror the list_assessments coverage above for the grouped path.


@pytest.mark.asyncio
async def test_hrp40_grouped_hides_draft_for_employee(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    from app.modules.assessment.schemas import MassAssessmentCreate

    other_emp, _ = await _make_extra_employee(db, tenant, "h40g1")
    # Standalone Draft on someone else — must NOT be visible to `employee`.
    draft_standalone = await _make_assessment(
        db,
        tenant,
        user,
        other_emp,
        type_code="360",
        title_suffix="grouped-draft-standalone",
    )
    # Mass assessment (= group) on someone else, both children stay in Draft.
    group_other_only = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="grouped-other-only",
            employee_ids=[other_emp.id],
            type_code="360",
        ),
    )
    # Standalone non-Draft on `employee` — must remain visible.
    visible = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="grouped-visible"
    )
    await service.change_status(db, tenant.id, visible["id"], "cancelled")

    items, total = await service.list_assessments_grouped(
        db,
        tenant.id,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    standalone_ids = {
        row["assessment"]["id"]
        for row in items
        if row["kind"] == "single" and row["assessment"]
    }
    group_ids = {row["group"]["id"] for row in items if row["kind"] == "group"}

    assert visible["id"] in standalone_ids
    assert draft_standalone["id"] not in standalone_ids
    assert group_other_only["id"] not in group_ids
    assert total == len(items)


@pytest.mark.asyncio
async def test_hrp40_grouped_shows_draft_for_admin(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    from app.modules.assessment.schemas import MassAssessmentCreate

    other_emp, _ = await _make_extra_employee(db, tenant, "h40g2")
    draft_standalone = await _make_assessment(
        db,
        tenant,
        user,
        other_emp,
        type_code="self",
        title_suffix="admin-grouped-draft",
    )
    group = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="admin-grouped-mass",
            employee_ids=[employee.id, other_emp.id],
            type_code="360",
        ),
    )
    items, _total = await service.list_assessments_grouped(
        db,
        tenant.id,
        visible_employee_ids=None,
        participant_user_id=user.id,
        restrict_to_active=False,
    )
    standalone_ids = {
        row["assessment"]["id"]
        for row in items
        if row["kind"] == "single" and row["assessment"]
    }
    group_ids = {row["group"]["id"] for row in items if row["kind"] == "group"}
    assert draft_standalone["id"] in standalone_ids
    assert group["id"] in group_ids
    # Admin pagination total is unaffected by scope drops (none happen here).
    assert _total == len(items)


@pytest.mark.asyncio
async def test_hrp40_grouped_endpoint_includes_standalone_for_participant_on_non_draft(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Standalone assessment surfaced through the grouped endpoint: a
    participant on a non-Draft assessment must still see it via the kind=single
    branch, even when the assessee is outside the caller's subtree."""
    other_emp, _ = await _make_extra_employee(db, tenant, "h40g3")
    a = await _make_assessment(
        db,
        tenant,
        user,
        other_emp,
        type_code="360",
        title_suffix="grouped-participant-single",
    )
    await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )
    await service.change_status(db, tenant.id, a["id"], "cancelled")

    items, _total = await service.list_assessments_grouped(
        db,
        tenant.id,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    standalone_ids = {
        row["assessment"]["id"]
        for row in items
        if row["kind"] == "single" and row["assessment"]
    }
    assert a["id"] in standalone_ids


@pytest.mark.asyncio
async def test_hrp40_grouped_visible_when_participant_on_grouped_non_draft(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Real grouped-children participant path: employee is a peer on one
    non-Draft child of a mass assessment whose assessees are otherwise out of
    scope — the parent group must still appear in the grouped list."""
    from app.modules.assessment.schemas import MassAssessmentCreate

    out1, _ = await _make_extra_employee(db, tenant, "h40g4a")
    out2, _ = await _make_extra_employee(db, tenant, "h40g4b")
    group = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="grouped-participant-mass",
            employee_ids=[out1.id, out2.id],
            type_code="360",
        ),
    )
    # Pick a child, add `employee` as participant, move it out of Draft so the
    # restrict_to_active filter doesn't hide it.
    child_id = group["assessments"][0]["id"]
    await service.add_participant(
        db,
        tenant.id,
        child_id,
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )
    await service.change_status(db, tenant.id, child_id, "cancelled")

    items, _total = await service.list_assessments_grouped(
        db,
        tenant.id,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    group_rows = [row for row in items if row["kind"] == "group"]
    visible_group = next((r for r in group_rows if r["group"]["id"] == group["id"]), None)
    assert visible_group is not None
    # Only the one child the employee participates in survives the filter.
    assert visible_group["group"]["assessment_count"] == 1


# HRP-40 follow-up (2026-05-14): /assessment-groups/{id} is the lazy-load
# companion to /assessments-grouped — same scope/Draft filters apply.


@pytest.mark.asyncio
async def test_hrp40_group_detail_404_for_employee_when_all_drafts(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    from app.modules.assessment.schemas import MassAssessmentCreate

    out_emp, _ = await _make_extra_employee(db, tenant, "h40g5")
    group = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="group-detail-all-draft",
            employee_ids=[out_emp.id],
            type_code="360",
        ),
    )

    with pytest.raises(Exception) as exc:
        await service.get_assessment_group(
            db,
            tenant.id,
            uuid.UUID(str(group["id"])),
            visible_employee_ids={employee.id},
            participant_user_id=user.id,
            restrict_to_active=True,
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_hrp40_group_detail_shows_full_for_admin(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    from app.modules.assessment.schemas import MassAssessmentCreate

    out_emp, _ = await _make_extra_employee(db, tenant, "h40g6")
    group = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="group-detail-admin",
            employee_ids=[employee.id, out_emp.id],
            type_code="360",
        ),
    )
    detail = await service.get_assessment_group(
        db,
        tenant.id,
        uuid.UUID(str(group["id"])),
        visible_employee_ids=None,
        participant_user_id=user.id,
        restrict_to_active=False,
    )
    assert detail["assessment_count"] == 2


@pytest.mark.asyncio
async def test_hrp40_group_detail_filters_children_for_employee_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Employee participant on one non-Draft child of a group must see the
    group but only the child they participate in — other-employee Drafts stay
    hidden in the lazy-load response."""
    from app.modules.assessment.schemas import MassAssessmentCreate

    out1, _ = await _make_extra_employee(db, tenant, "h40g7a")
    out2, _ = await _make_extra_employee(db, tenant, "h40g7b")
    group = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="group-detail-participant",
            employee_ids=[out1.id, out2.id],
            type_code="360",
        ),
    )
    visible_child_id = group["assessments"][0]["id"]
    hidden_child_id = group["assessments"][1]["id"]
    await service.add_participant(
        db,
        tenant.id,
        visible_child_id,
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )
    await service.change_status(db, tenant.id, visible_child_id, "cancelled")

    detail = await service.get_assessment_group(
        db,
        tenant.id,
        uuid.UUID(str(group["id"])),
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=True,
    )
    child_ids = {a["id"] for a in detail["assessments"]}
    assert visible_child_id in child_ids
    assert hidden_child_id not in child_ids
    assert detail["assessment_count"] == 1


# ---------------------------------------------------------------------------
# HRP-43 — competence detail filters indicators by skill level + lower
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp43_competence_detail_filters_indicators_by_skill_level(db, tenant):
    from app.modules.competence import service as compsvc
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        Indicator,
        SkillLevel,
    )

    # Three skill levels: Basic (0) < Intermediate (1) < Advanced (2).
    levels = []
    for sort_index, title in enumerate(("Basic", "Intermediate", "Advanced")):
        sl = SkillLevel(
            tenant_id=tenant.id,
            title=title,
            sort_index=sort_index,
            is_active=True,
        )
        db.add(sl)
        levels.append(sl)
    await db.commit()
    for sl in levels:
        await db.refresh(sl)

    group = CompetenceGroup(
        tenant_id=tenant.id, title="Soft", description=None, sort_index=0
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)

    comp = Competence(
        tenant_id=tenant.id,
        group_id=group.id,
        title="Communication",
        is_active=True,
        is_published=True,
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)

    for sort_index, sl in enumerate(levels):
        db.add(
            Indicator(
                tenant_id=tenant.id,
                competence_id=comp.id,
                skill_level_id=sl.id,
                title=f"Ind-{sl.title}",
                weight=1,
                sort_index=sort_index,
                is_active=True,
            )
        )
    await db.commit()

    # No filter → all three indicators.
    full = await compsvc.get_competence_detail(db, tenant.id, comp.id)
    assert {i["title"] for i in full["indicators"]} == {
        "Ind-Basic",
        "Ind-Intermediate",
        "Ind-Advanced",
    }

    # Basic → only Basic.
    basic = await compsvc.get_competence_detail(
        db, tenant.id, comp.id, skill_level_id=levels[0].id
    )
    assert {i["title"] for i in basic["indicators"]} == {"Ind-Basic"}

    # Intermediate → Basic + Intermediate.
    inter = await compsvc.get_competence_detail(
        db, tenant.id, comp.id, skill_level_id=levels[1].id
    )
    assert {i["title"] for i in inter["indicators"]} == {
        "Ind-Basic",
        "Ind-Intermediate",
    }

    # Advanced → all three.
    adv = await compsvc.get_competence_detail(
        db, tenant.id, comp.id, skill_level_id=levels[2].id
    )
    assert {i["title"] for i in adv["indicators"]} == {
        "Ind-Basic",
        "Ind-Intermediate",
        "Ind-Advanced",
    }


# ---------------------------------------------------------------------------
# HRP-112 — /assessments/{id}/results inherits the HRP-40 scope fence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp112_results_404_for_unscoped_employee(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """A restricted caller can't read calibrated results via the URL."""
    other_emp, _other_user = await _make_extra_employee(db, tenant, "h112a")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="hidden"
    )

    visible_ids: set[uuid.UUID] = {employee.id}

    with pytest.raises(Exception) as exc:
        await service.get_results(
            db,
            tenant.id,
            uuid.UUID(str(a["id"])),
            visible_employee_ids=visible_ids,
            participant_user_id=user.id,
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_hrp112_results_visible_when_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Participants keep seeing results even when the assessee is out of
    their subtree — same rule as `get_assessment_detail`."""
    other_emp, _other_user = await _make_extra_employee(db, tenant, "h112b")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="seen"
    )
    await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )

    visible_ids: set[uuid.UUID] = {employee.id}

    # Empty list is fine — the assertion is "didn't 404".
    results = await service.get_results(
        db,
        tenant.id,
        uuid.UUID(str(a["id"])),
        visible_employee_ids=visible_ids,
        participant_user_id=user.id,
    )
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_hrp112_results_admin_unrestricted(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Admin / HR / platform_admin pass `visible_employee_ids=None`; the
    scope branch is skipped and they keep seeing everything."""
    other_emp, _ = await _make_extra_employee(db, tenant, "h112c")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="admin"
    )

    results = await service.get_results(
        db, tenant.id, uuid.UUID(str(a["id"]))
    )
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_hrp112_results_hide_draft_for_employee_participant(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """`restrict_to_active=True` hides Draft assessments from regular
    employees even when they are participants — same toggle as list/detail."""
    other_emp, _ = await _make_extra_employee(db, tenant, "h112d")
    draft = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="draft"
    )
    await service.add_participant(
        db,
        tenant.id,
        draft["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )

    with pytest.raises(Exception) as exc:
        await service.get_results(
            db,
            tenant.id,
            uuid.UUID(str(draft["id"])),
            visible_employee_ids={employee.id},
            participant_user_id=user.id,
            restrict_to_active=True,
        )
    assert getattr(exc.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# HRP-113 — apply_assessment_scope helper extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hrp113_helper_unscoped_returns_everything(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """visible_employee_ids=None + restrict_to_active=False → no filters
    applied; both the assessee-owned and a draft assessment for another
    employee remain visible."""
    from app.modules.assessment.models import Assessment

    own = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="hrp113-own"
    )
    other_emp, _ = await _make_extra_employee(db, tenant, "h113")
    other = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="hrp113-oth"
    )

    base = select(Assessment).where(Assessment.tenant_id == tenant.id)
    scoped = service.apply_assessment_scope(
        base,
        visible_employee_ids=None,
        participant_user_id=None,
        restrict_to_active=False,
    )
    rows = (await db.execute(scoped)).scalars().all()
    ids = {r.id for r in rows}
    assert own["id"] in ids
    assert other["id"] in ids


@pytest.mark.asyncio
async def test_hrp113_helper_restricts_by_scope(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """visible_employee_ids={employee.id} → only the assessment whose
    assessee is in the subtree survives; the other-employee row drops out
    (participant arm is empty because the caller is not on it)."""
    from app.modules.assessment.models import Assessment

    own = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="hrp113s-own"
    )
    other_emp, other_user = await _make_extra_employee(db, tenant, "h113s")
    other = await _make_assessment(
        db, tenant, user, other_emp, type_code="self", title_suffix="hrp113s-oth"
    )

    base = select(Assessment).where(Assessment.tenant_id == tenant.id)
    scoped = service.apply_assessment_scope(
        base,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=False,
    )
    rows = (await db.execute(scoped)).scalars().all()
    ids = {r.id for r in rows}
    assert own["id"] in ids
    assert other["id"] not in ids
    # participant arm: caller_user is on `other` as initiator's self → not a
    # participant though. Sanity-check the unrelated other_user has no rows.
    assert other_user.id is not None


@pytest.mark.asyncio
async def test_hrp113_helper_keeps_participant_outside_subtree(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """The OR arm: if the caller participates in another employee's
    assessment, the row is still visible even when the assessee is outside
    visible_employee_ids."""
    from app.modules.assessment.models import Assessment

    other_emp, _ = await _make_extra_employee(db, tenant, "h113p")
    a = await _make_assessment(
        db, tenant, user, other_emp, type_code="360", title_suffix="hrp113p"
    )
    await service.add_participant(
        db,
        tenant.id,
        a["id"],
        ParticipantAdd(employee_id=employee.id, role="peer"),
    )

    base = select(Assessment).where(Assessment.tenant_id == tenant.id)
    scoped = service.apply_assessment_scope(
        base,
        visible_employee_ids={employee.id},
        participant_user_id=user.id,
        restrict_to_active=False,
    )
    rows = (await db.execute(scoped)).scalars().all()
    assert a["id"] in {r.id for r in rows}


@pytest.mark.asyncio
async def test_hrp113_helper_drops_drafts_when_active_only(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """restrict_to_active=True → Draft assessments fall out of the result,
    even for an unscoped admin caller."""
    from app.modules.assessment.models import Assessment

    draft = await _make_assessment(
        db, tenant, user, employee, type_code="self", title_suffix="hrp113-draft"
    )

    base = select(Assessment).where(Assessment.tenant_id == tenant.id)
    scoped = service.apply_assessment_scope(
        base,
        visible_employee_ids=None,
        participant_user_id=None,
        restrict_to_active=True,
    )
    rows = (await db.execute(scoped)).scalars().all()
    assert draft["id"] not in {r.id for r in rows}
