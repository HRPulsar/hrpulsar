"""Regression tests for Assessment bugs reported by QA against v1.5.0
(Slack thread #gf-development-ai, 2026-04-30 → 2026-05-04) and fixed
in v1.6.0.

Coverage:
  #6  — record_answer flips participant.is_completed once every
        indicator is answered and moves the assessment from Sent to
        In Progress on the first recorded answer.
  #7  — bulk_change_status returns a per-reason skip breakdown
        (terminal / same_or_lower_status / already_cancelled) so the
        UI can render an accurate snackbar.
  #9  — change_status(draft -> sent) rejects assessments that have no
        criteria_type or no scale_id with a 400, criteria taking
        priority in the message.
  #11 — service.update_assessment + PATCH /assessments/{id} let admins
        edit title and deadline on non-terminal assessments.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.assessment import service
from app.modules.assessment.schemas import (
    AnswerRecord,
    AssessmentCreate,
    CriteriaUpdate,
    MassAssessmentCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import seed_send_prereqs

# ---------- Local helpers (kept independent from test_assessment_service.py
# so this file can move/rename without breaking that suite). ----------


async def _make_assessment(db, tenant, user, employee, **kwargs) -> dict:
    data = AssessmentCreate(
        title=kwargs.get("title", f"v160-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    """Create a second User+Employee for mass-assessment scenarios."""
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
        email=f"v160-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
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


async def _make_competence_with_indicator(db: AsyncSession, tenant, suffix: str):
    """Returns (competence, indicator) with one skill level."""
    from app.modules.competence import service as comp_service
    from app.modules.competence.models import Indicator, SkillLevel
    from app.modules.competence.schemas import CompetenceCreate, CompetenceGroupCreate
    from sqlalchemy import select

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"Grp-{suffix}")
    )
    comp = await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=f"Comp-{suffix}", group_id=group.id)
    )

    sl = (await db.execute(select(SkillLevel).limit(1))).scalar_one_or_none()
    if not sl:
        sl = SkillLevel(title="Basic", sort_index=0)
        db.add(sl)
        await db.commit()
        await db.refresh(sl)

    ind = Indicator(
        title=f"Ind-{suffix}",
        weight=1,
        sort_index=0,
        skill_level_id=sl.id,
        competence_id=comp.id,
        tenant_id=tenant.id,
    )
    db.add(ind)
    await db.commit()
    await db.refresh(ind)
    return comp, ind


# ---------------------------------------------------------------------
# Bug #6 — submit answers does not flip participant.is_completed and
# does not move assessment from Sent → In Progress.
#
# Slack: "Answers submitted snackbar shows, ... assessment status moves
# to In Progress, the Details block hides the Take this assessment CTA,
# the Participants block shows Completed=Yes for me".
#
# Current code: backend/app/modules/assessment/service.py:831-888
# (record_answer) only inserts a row into assessment_answers.
# ---------------------------------------------------------------------


class TestBug6SubmitAnswersFlipsCompletionAndStatus:
    async def test_first_answer_moves_assessment_to_in_progress(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.models import Assessment
        from sqlalchemy import select

        comp, ind = await _make_competence_with_indicator(db, tenant, "p6a")
        # Add a second indicator so the first answer doesn't also complete
        # the (only) participant — completion would auto-flip the
        # assessment to on_review and bypass the in_progress checkpoint
        # we're pinning here.
        from app.modules.competence.models import Indicator

        db.add(
            Indicator(
                title="Ind-p6a-2",
                weight=1,
                sort_index=1,
                skill_level_id=ind.skill_level_id,
                competence_id=comp.id,
                tenant_id=tenant.id,
            )
        )
        await db.commit()

        created = await _make_assessment(db, tenant, user, employee)
        await service.add_competences(db, tenant.id, created["id"], [comp.id])
        await seed_send_prereqs(db, tenant.id, created["id"])
        await service.change_status(db, tenant.id, created["id"], "sent")

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        await service.record_answer(
            db,
            tenant.id,
            user.id,
            created["id"],
            AnswerRecord(participant_id=self_part["id"], indicator_id=ind.id, score=4),
        )

        a = (
            await db.execute(select(Assessment).where(Assessment.id == created["id"]))
        ).scalar_one()
        await db.refresh(a, ["status"])
        assert (
            a.status.code == "in_progress"
        ), f"After first answer status must advance to 'in_progress', got '{a.status.code}'"

    async def test_all_answers_mark_internal_participant_completed(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.models import AssessmentParticipant
        from sqlalchemy import select

        comp, ind = await _make_competence_with_indicator(db, tenant, "p6b")
        created = await _make_assessment(db, tenant, user, employee)
        await service.add_competences(db, tenant.id, created["id"], [comp.id])
        await seed_send_prereqs(db, tenant.id, created["id"])
        await service.change_status(db, tenant.id, created["id"], "sent")

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        # Submit answers for every indicator that belongs to the assessment —
        # in this fixture there is exactly one.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            created["id"],
            AnswerRecord(participant_id=self_part["id"], indicator_id=ind.id, score=4),
        )

        part = (
            await db.execute(
                select(AssessmentParticipant).where(
                    AssessmentParticipant.id == self_part["id"]
                )
            )
        ).scalar_one()
        assert part.is_completed is True, (
            "After answering every indicator, internal participant must be flagged "
            "is_completed=True (matches the external-reviewer code path at "
            "service.py:submit_external_answers)"
        )


# ---------------------------------------------------------------------
# Bug #7 — bulk_change_status returns only aggregate {changed, skipped,
# total}. The UI needs to distinguish *why* assessments were skipped:
# already in a terminal status vs. already in / past the requested
# status. Today every skip surfaces as «already in terminal status».
#
# Slack: "Actual: Updated 0 of 2 assessment (2 already in terminal status)
#         Expected: Cannot transition from {status} to {status}" (case 1)
#        "Expected: Updated 0 of 2 assessment (1 already in terminal
#         status, 1 already in in progress)" (case 2)
#
# Current code: backend/app/modules/assessment/service.py:1688-1738.
# ---------------------------------------------------------------------


class TestBug7BulkChangeStatusReportsSkipReasons:
    async def test_skipped_reasons_distinguishes_terminal_and_same_status(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "b7")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Bulk reasons",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        first_id = group["assessments"][0]["id"]
        second_id = group["assessments"][1]["id"]

        await seed_send_prereqs(db, tenant.id, first_id)
        await seed_send_prereqs(db, tenant.id, second_id)

        # First → done (terminal). Second → sent (same as the bulk target
        # we'll request, so it lands in the same_or_lower_status bucket).
        # HRP-192 removed manual Sent → In progress, so the in_progress
        # checkpoint that this test used to lean on is no longer reachable
        # without going through the auto-flip (record_answer). Targeting
        # ``sent`` keeps the same contract intact without that detour.
        from tests.unit._send_prereqs import advance_to_done

        await service.change_status(db, tenant.id, first_id, "sent")
        await advance_to_done(db, tenant.id, first_id)
        await service.change_status(db, tenant.id, second_id, "sent")

        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "sent"
        )

        assert result["changed"] == 0
        assert result["skipped"] == 2
        # The structure below is the contract QA needs to render its snackbar
        # "1 already in terminal status, 1 already in sent".
        assert (
            "skipped_reasons" in result
        ), "bulk_change_status must return per-reason skip counts"
        reasons = result["skipped_reasons"]
        assert reasons.get("terminal") == 1
        assert reasons.get("same_or_lower_status") == 1

    async def test_bulk_draft_to_sent_skips_assessments_missing_prereqs(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Mirror the change_status guard (Bug #9) in bulk: draft → sent
        must not silently kick assessments without criteria or scale."""
        emp2 = await _make_extra_employee(db, tenant, "b7m")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Bulk missing prereqs",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        # Seed only the first child; the second stays without criteria/scale.
        await seed_send_prereqs(db, tenant.id, group["assessments"][0]["id"])

        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")
        assert result["changed"] == 1
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["missing_criteria_or_scale"] == 1


# ---------------------------------------------------------------------
# Bug #9 — change_status(draft -> sent) succeeds when criteria_type is
# unset and/or scale_id is unset. The snapshot-on-launch path in
# service.py:406-407 silently skips both cases.
#
# Slack: "Create an assessment, skip Evaluation criteria and/or Rating
# scale → pick sent. Actual: assessment flips to Sent. Expected: error
# snackbar 'Evaluation criteria are not selected' (priority) or
# 'Evaluation scale is not selected'".
# ---------------------------------------------------------------------


class TestBug9DraftToSentValidation:
    async def test_draft_to_sent_requires_criteria(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        # No criteria, no scale set on the assessment.

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 400
        assert "criteria" in exc.value.detail.lower()

    async def test_draft_to_sent_requires_scale(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)

        # Set criteria but leave scale empty.
        await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(criteria_type="current_positions"),
        )

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 400
        assert "scale" in exc.value.detail.lower()


# ---------------------------------------------------------------------
# Bug #11 — there is no PATCH endpoint / service for editing an
# assessment's title or deadline (ended_at) on a non-terminal
# assessment. Slack screenshot shows pencil icons missing next to
# Title and Deadline (PDP got inline-edit in v1.5.0; assessment did
# not).
#
# Frontend: assessments/[id]/page.tsx renders title statically, no
# pencil. Backend: router.py exposes no PATCH /assessments/{id}.
# ---------------------------------------------------------------------


class TestBug11AssessmentEditableTitleAndDeadline:
    async def test_service_update_assessment_changes_title_and_deadline(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.models import Assessment
        from sqlalchemy import select

        created = await _make_assessment(
            db, tenant, user, employee, title="Original title"
        )
        new_deadline = datetime.now(timezone.utc) + timedelta(days=7)

        # Service-level API expected by the upcoming PATCH endpoint.
        # AttributeError here is itself a documented failure of the bug.
        update = getattr(service, "update_assessment", None)
        assert update is not None, "service.update_assessment must exist"
        await update(
            db,
            tenant.id,
            created["id"],
            title="Renamed title",
            ended_at=new_deadline,
        )

        a = (
            await db.execute(select(Assessment).where(Assessment.id == created["id"]))
        ).scalar_one()
        assert a.title == "Renamed title"
        assert a.ended_at is not None
        assert abs((a.ended_at - new_deadline).total_seconds()) < 1

    async def test_patch_endpoint_exposed_for_assessment(
        self,
        auth_client,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        db: AsyncSession,
    ):
        created = await _make_assessment(db, tenant, user, employee)

        response = await auth_client.patch(
            f"/api/assessments/{created['id']}",
            json={"title": "via HTTP"},
        )
        # Today the route is missing → 404/405. After the fix → 200.
        assert (
            response.status_code == 200
        ), f"PATCH /assessments/{{id}} must be exposed; got {response.status_code}"
        assert response.json()["title"] == "via HTTP"

    async def test_patch_with_explicit_null_deadline_clears_it(
        self,
        auth_client,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        db: AsyncSession,
    ):
        """Tri-state PATCH: explicit `ended_at: null` clears the field;
        omitting it leaves the previous value intact."""
        from app.modules.assessment.models import Assessment
        from sqlalchemy import select

        created = await _make_assessment(db, tenant, user, employee)

        # First set a deadline.
        seed_deadline = datetime.now(timezone.utc) + timedelta(days=14)
        r1 = await auth_client.patch(
            f"/api/assessments/{created['id']}",
            json={"ended_at": seed_deadline.isoformat()},
        )
        assert r1.status_code == 200
        assert r1.json()["ended_at"] is not None

        # Touch only the title — deadline must survive.
        r2 = await auth_client.patch(
            f"/api/assessments/{created['id']}",
            json={"title": "Renamed"},
        )
        assert r2.status_code == 200
        assert r2.json()["ended_at"] is not None

        # Explicit null clears it.
        r3 = await auth_client.patch(
            f"/api/assessments/{created['id']}",
            json={"ended_at": None},
        )
        assert r3.status_code == 200
        assert r3.json()["ended_at"] is None

        # Re-read to confirm persistence.
        db.expunge_all()
        a = (
            await db.execute(select(Assessment).where(Assessment.id == created["id"]))
        ).scalar_one()
        assert a.ended_at is None
        assert a.title == "Renamed"

    async def test_patch_rejects_empty_title(
        self,
        auth_client,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        db: AsyncSession,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        response = await auth_client.patch(
            f"/api/assessments/{created['id']}",
            json={"title": "   "},
        )
        assert response.status_code == 400
        assert "title" in response.json()["detail"].lower()
