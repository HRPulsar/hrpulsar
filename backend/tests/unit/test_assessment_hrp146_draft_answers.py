"""HRP-146: replacing the survey modal with a Sheet introduces auto-save
on every change, which means the same (assessment, participant,
indicator) row must be upserted rather than inserted afresh. The Sheet
also rehydrates from ``GET /assessments/{id}/my-answers`` when reopened.

These tests cover both halves: the upsert behaviour of ``record_answer``
and the read endpoint surfaced for the frontend.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentParticipant,
)
from app.modules.assessment.schemas import (
    AnswerRecord,
    AssessmentCreate,
)
from app.modules.auth.models import User as AuthUser
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _make_self_assessment_ready(
    db: AsyncSession, tenant, user, employee
) -> dict:
    scale = AnswerScale(tenant_id=tenant.id, title=f"Scale-{uuid.uuid4().hex[:6]}")
    db.add(scale)
    await db.flush()
    for i, w in enumerate([0, 1, 2, 3, 4]):
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=f"Opt{i}",
                code=f"opt{i}",
                weight=w,
                sort_index=i,
            )
        )
    await db.commit()
    await db.refresh(scale)

    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title="G-draft")
    )
    comp = await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title="C-draft", group_id=group.id)
    )
    sl = SkillLevel(title="L-draft", sort_index=0, tenant_id=tenant.id)
    db.add(sl)
    await db.flush()
    indicators: list[Indicator] = []
    for idx in range(2):
        ind = Indicator(
            title=f"Ind-{idx}",
            weight=1,
            sort_index=idx,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=tenant.id,
        )
        db.add(ind)
        indicators.append(ind)
    await db.commit()
    for ind in indicators:
        await db.refresh(ind)

    a = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="Draft-rehydrate",
            employee_id=employee.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp.id))
    a_obj = await db.get(Assessment, a["id"])
    a_obj.criteria_type = "current_positions"
    await db.commit()

    detail = await service.get_assessment_detail(db, tenant.id, a["id"])
    self_part_id = next(
        p["id"] for p in detail["participants"] if p["role"] == "self"
    )
    await service.change_status(db, tenant.id, a["id"], "sent")

    snap = await service._load_scale_full(
        db, (await db.get(Assessment, a["id"])).scale_id
    )
    opt_by_weight = {o.weight: o for o in snap.options if not o.is_neutral}
    return {
        "assessment_id": a["id"],
        "participant_id": self_part_id,
        "indicators": indicators,
        "opt_by_weight": opt_by_weight,
    }


class TestRecordAnswerUpsert:
    async def test_re_submission_updates_existing_row(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        ind = ctx["indicators"][0]
        opt_low = ctx["opt_by_weight"][1]
        opt_high = ctx["opt_by_weight"][4]

        first = await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ind.id,
                answer_option_id=opt_low.id,
                comment="initial",
            ),
        )
        second = await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ind.id,
                answer_option_id=opt_high.id,
                comment="updated",
            ),
        )
        assert first["id"] == second["id"], "second submit must upsert, not insert"

        rows = (
            await db.execute(
                select(AssessmentAnswer).where(
                    AssessmentAnswer.assessment_id == ctx["assessment_id"],
                    AssessmentAnswer.participant_id == ctx["participant_id"],
                    AssessmentAnswer.indicator_id == ind.id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].answer_option_id == opt_high.id
        assert rows[0].comment == "updated"

    async def test_completion_distinct_count_unaffected_by_re_submit(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Even after several re-submits per indicator, the participant
        flips to is_completed when *every* indicator has an answer —
        without the upsert this regressed because the per-indicator
        distinct count under-counted vs. the inflated row count."""
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        opt = ctx["opt_by_weight"][3]
        for ind in ctx["indicators"]:
            for _ in range(3):
                await service.record_answer(
                    db,
                    tenant.id,
                    user.id,
                    ctx["assessment_id"],
                    AnswerRecord(
                        participant_id=ctx["participant_id"],
                        indicator_id=ind.id,
                        answer_option_id=opt.id,
                    ),
                )

        await db.refresh(
            await db.get(AssessmentParticipant, ctx["participant_id"]),
            ["is_completed"],
        )
        participant = await db.get(AssessmentParticipant, ctx["participant_id"])
        assert participant.is_completed is True


class TestGetParticipantAnswers:
    async def test_returns_caller_draft_answers(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        ind_a, ind_b = ctx["indicators"]
        opt_a = ctx["opt_by_weight"][2]
        opt_b = ctx["opt_by_weight"][3]
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ind_a.id,
                answer_option_id=opt_a.id,
                comment="half-way",
            ),
        )

        out = await service.get_participant_answers(
            db, tenant.id, user.id, ctx["assessment_id"]
        )
        assert out["participant_id"] == ctx["participant_id"]
        # Only the indicator the participant has actually touched comes
        # back — the Sheet hydrates radios from this set, the rest stay
        # blank.
        assert len(out["answers"]) == 1
        row = out["answers"][0]
        assert row["indicator_id"] == ind_a.id
        assert row["answer_option_id"] == opt_a.id
        assert row["comment"] == "half-way"

        # After answering the second indicator the read endpoint
        # surfaces both rows.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ind_b.id,
                answer_option_id=opt_b.id,
            ),
        )
        out2 = await service.get_participant_answers(
            db, tenant.id, user.id, ctx["assessment_id"]
        )
        assert {row["indicator_id"] for row in out2["answers"]} == {
            ind_a.id,
            ind_b.id,
        }

    async def test_non_participant_gets_empty_payload(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        # Create a second user that is NOT a participant of the
        # assessment — the endpoint must not 403 (the page still loads)
        # but the answers list stays empty.
        pos = Position(tenant_id=tenant.id, title="Pos-other", source="manual")
        db.add(pos)
        await db.flush()
        other = AuthUser(
            email=f"other-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("testpass"),
            first_name="O",
            last_name="X",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(other)
        await db.flush()
        db.add(
            Employee(
                user_id=other.id,
                tenant_id=tenant.id,
                position_id=pos.id,
                position_title=pos.title,
                hire_date=date(2024, 1, 15),
            )
        )
        await db.commit()

        out = await service.get_participant_answers(
            db, tenant.id, other.id, ctx["assessment_id"]
        )
        assert out == {"participant_id": None, "answers": []}
