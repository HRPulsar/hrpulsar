"""Regression tests for Session 2 Assessment bugs filed by QA on
2026-05-06/07 — HRP-26, HRP-30, HRP-35, HRP-39.

Each class targets a distinct ticket; the helpers are intentionally
inlined so removing one bug fix doesn't pull the others' fixtures with
it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    Assessment,
)
from app.modules.assessment.schemas import (
    AssessmentCreate,
    CriteriaUpdate,
    MassAssessmentCreate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import advance_to_in_progress, seed_send_prereqs


async def _make_assessment(db, tenant, user, employee, **kwargs) -> dict:
    data = AssessmentCreate(
        title=kwargs.get("title", f"sess2-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    from datetime import date

    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"sess2-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
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
    return emp


# ---------------------------------------------------------------------
# HRP-26 — bulk_change_status with new_code="cancelled" overrides terminal
# "done" assessments. Reporter expects done/cancelled to be skipped just
# like in non-cancel transitions; only non-terminal children cancel and
# the snackbar should show the actual count.
# ---------------------------------------------------------------------


class TestHRP26BulkCancelSkipsTerminal:
    async def test_bulk_cancel_skips_done_assessments(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "h26")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-26 group",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        first_id = group["assessments"][0]["id"]
        second_id = group["assessments"][1]["id"]

        await seed_send_prereqs(db, tenant.id, first_id)
        await seed_send_prereqs(db, tenant.id, second_id)

        # First → done (terminal). Second stays in_progress (non-terminal).
        from tests.unit._send_prereqs import advance_to_done

        await service.change_status(db, tenant.id, first_id, "sent")
        await advance_to_in_progress(db, tenant.id, first_id)
        await advance_to_done(db, tenant.id, first_id)
        await service.change_status(db, tenant.id, second_id, "sent")
        await advance_to_in_progress(db, tenant.id, second_id)

        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "cancelled"
        )

        assert result["changed"] == 1, (
            "Only the in_progress child must transition to cancelled; the "
            "done one is terminal and must be left alone."
        )
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["terminal"] == 1
        assert result["skipped_reasons"]["already_cancelled"] == 0

        first = (
            await db.execute(select(Assessment).where(Assessment.id == first_id))
        ).scalar_one()
        await db.refresh(first, ["status"])
        assert (
            first.status.code == "done"
        ), "Done assessments must NOT be flipped to cancelled by bulk-cancel."

    async def test_bulk_cancel_still_skips_already_cancelled(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "h26b")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-26 group cancelled",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        first_id = group["assessments"][0]["id"]
        second_id = group["assessments"][1]["id"]
        await seed_send_prereqs(db, tenant.id, first_id)
        await seed_send_prereqs(db, tenant.id, second_id)

        # First → cancelled directly from draft. Second stays draft.
        await service.change_status(db, tenant.id, first_id, "cancelled")

        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "cancelled"
        )
        assert result["changed"] == 1
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["already_cancelled"] == 1
        assert result["skipped_reasons"]["terminal"] == 0


# ---------------------------------------------------------------------
# HRP-35 — there is no PATCH endpoint to rename a Mass Assessment, and
# even if there were, the children must inherit the new title (UI hides
# the per-child pencil when group_id is set).
# ---------------------------------------------------------------------


class TestHRP35MassAssessmentRename:
    async def test_service_update_assessment_group_renames_and_cascades(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "h35a")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Original group title",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        update = getattr(service, "update_assessment_group", None)
        assert update is not None, "service.update_assessment_group must exist"
        result = await update(db, tenant.id, group["id"], title="Renamed group")

        assert result["title"] == "Renamed group"
        for child in result["assessments"]:
            assert child["title"] == "Renamed group", (
                "Every child assessment must inherit the new group title"
            )

    async def test_patch_endpoint_exposed_for_assessment_group(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "h35b")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Group via HTTP",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        response = await auth_client.patch(
            f"/api/assessment-groups/{group['id']}",
            json={"title": "via HTTP renamed"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "via HTTP renamed"
        for child in body["assessments"]:
            assert child["title"] == "via HTTP renamed"

    async def test_patch_rejects_empty_title(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "h35c")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Group empty test",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        response = await auth_client.patch(
            f"/api/assessment-groups/{group['id']}",
            json={"title": "   "},
        )
        # Pydantic rejects min_length=1 on stripped value at validator level
        # (422), service-level rejects any-whitespace too (400).
        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------
# HRP-30 — answer scale options always render "(weight)" on the
# assessment page, leaking "I don't know ()" for the neutral option
# (weight is NULL). The fix lives in the frontend; this test pins the
# contract on the API side (is_neutral comes through and weight stays
# nullable).
# ---------------------------------------------------------------------


class TestHRP30NeutralOptionContract:
    async def test_assessment_detail_returns_is_neutral_and_nullable_weight(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = AnswerScale(
            tenant_id=tenant.id,
            title="HRP-30 scale",
            description=None,
            is_default=False,
        )
        db.add(scale)
        await db.flush()
        db.add_all(
            [
                AnswerScaleLevel(
                    scale_id=scale.id,
                    percent_from=0,
                    percent_to=100,
                    system_title="Always",
                    sort_index=0,
                ),
                AnswerOption(
                    scale_id=scale.id,
                    title="Yes",
                    code="yes",
                    weight=4,
                    sort_index=0,
                    is_neutral=False,
                ),
                AnswerOption(
                    scale_id=scale.id,
                    title="I don't know",
                    code="dontknow",
                    weight=None,
                    sort_index=1,
                    is_neutral=True,
                ),
            ]
        )
        await db.commit()

        created = await _make_assessment(db, tenant, user, employee)
        # Use service.set_assessment_scale to pin the scale to the assessment.
        await service.set_assessment_scale(db, tenant.id, created["id"], scale.id)

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["scale"] is not None
        opts = {o["code"]: o for o in detail["scale"]["options"]}
        assert opts["dontknow"]["is_neutral"] is True
        assert opts["dontknow"]["weight"] is None
        assert opts["yes"]["is_neutral"] is False
        assert opts["yes"]["weight"] == 4


# ---------------------------------------------------------------------
# HRP-39 — selected Individual competences render only the title; the
# skill level the admin picked is missing. Backend now needs to expose
# the skill-level title (and code) alongside the id so the UI doesn't
# have to second-fetch /skill-levels just to show the chosen level.
# ---------------------------------------------------------------------


class TestHRP39CompetenceLevelIncludesTitle:
    async def test_assessment_detail_competences_include_skill_level_title(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.competence import service as comp_service
        from app.modules.competence.models import SkillLevel
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        # Seed a skill level.
        sl = SkillLevel(title="Basic", sort_index=0)
        db.add(sl)
        await db.commit()
        await db.refresh(sl)

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="HRP-39 group")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="HRP-39 comp", group_id=group.id)
        )

        created = await _make_assessment(db, tenant, user, employee)
        await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="competences",
                competences=[
                    {"competence_id": comp.id, "skill_level_id": sl.id},  # type: ignore[list-item]
                ],
            ),
        )

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        comp_rows = detail["competences"]
        assert len(comp_rows) == 1
        row = comp_rows[0]
        assert row["competence_title"] == "HRP-39 comp"
        # The bug is that the level title was missing — the new field must
        # surface the human-readable name so the UI stops printing UUIDs.
        assert "skill_level_title" in row, (
            "AssessmentCompetenceRead must expose skill_level_title alongside "
            "skill_level_id so the frontend renders 'Basic' instead of a UUID."
        )
        assert row["skill_level_title"] == "Basic"
