"""HRP-185: per-indicator Total calibration.

Covers the lifecycle:
  1. start_calibration flips the lock so participant submissions stop.
  2. save_calibration upserts the per-indicator totals, recomputes
     percent / level using the calibrated answer, and exposes the
     override + `is_calibrated` flag in Detailed results.
  3. cancel_calibration wipes the totals, releases the lock, and
     re-runs the recompute on raw answers.
  4. record_answer is rejected with 409 while calibration is in
     progress so the baseline stays stable.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentCalibratedTotal,
    AssessmentParticipant,
)
from app.modules.assessment.schemas import (
    AnswerRecord,
    AssessmentCreate,
    CalibratedTotalItem,
    CompetenceCriteriaItem,
    CriteriaUpdate,
)
from app.modules.competence.models import Indicator, SkillLevel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.unit._send_prereqs import advance_to_in_progress, seed_send_prereqs


async def _make_skill_level(db, title: str, sort_index: int) -> SkillLevel:
    sl = SkillLevel(title=title, sort_index=sort_index)
    db.add(sl)
    await db.commit()
    await db.refresh(sl)
    return sl


async def _make_competence(db, tenant, title: str):
    from app.modules.competence import service as comp_service
    from app.modules.competence.schemas import (
        CompetenceCreate,
        CompetenceGroupCreate,
    )

    group = await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title=f"G-{title}-{uuid.uuid4().hex[:6]}")
    )
    return await comp_service.create_competence(
        db, tenant.id, CompetenceCreate(title=title, group_id=group.id)
    )


async def _make_indicator(db, tenant, *, competence_id, skill_level_id, weight=1):
    ind = Indicator(
        title=f"Ind-{uuid.uuid4().hex[:6]}",
        weight=weight,
        sort_index=0,
        skill_level_id=skill_level_id,
        competence_id=competence_id,
        tenant_id=tenant.id,
    )
    db.add(ind)
    await db.commit()
    await db.refresh(ind)
    return ind


async def _make_scale(db, tenant) -> AnswerScale:
    """6-option scale, weights 0..5 → max weight 5."""
    scale = AnswerScale(
        title=f"S-{uuid.uuid4().hex[:6]}", tenant_id=tenant.id, is_default=False
    )
    db.add(scale)
    await db.flush()
    for i in range(6):
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=f"L{i}",
                code=f"l{i}",
                weight=i,
                sort_index=i,
                is_neutral=False,
            )
        )
    await db.commit()
    res = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == scale.id)
    )
    return res.scalar_one()


def _opt_by_weight(scale: AnswerScale, weight: int) -> AnswerOption:
    for o in scale.options:
        if o.weight == weight:
            return o
    raise AssertionError(f"weight {weight} missing")


async def _setup_in_review(
    db, tenant, user, employee, *, scale_weight: int
) -> dict:
    sl = await _make_skill_level(db, "Basic", 1)
    comp = await _make_competence(db, tenant, "C")
    ind = await _make_indicator(
        db, tenant, competence_id=comp.id, skill_level_id=sl.id
    )
    scale = await _make_scale(db, tenant)
    created = await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title="cal",
            employee_id=employee.id,
            type_code="self",
            scale_id=scale.id,
        ),
    )
    await service.set_assessment_criteria(
        db,
        tenant.id,
        created["id"],
        CriteriaUpdate(
            criteria_type="competences",
            competences=[
                CompetenceCriteriaItem(competence_id=comp.id, skill_level_id=sl.id)
            ],
        ),
    )
    detail = await service.get_assessment_detail(db, tenant.id, created["id"])
    self_p = next(p for p in detail["participants"] if p["role"] == "self")
    await seed_send_prereqs(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "sent")
    live = await db.execute(
        select(AnswerScale)
        .options(selectinload(AnswerScale.options))
        .where(AnswerScale.id == (await db.get(Assessment, created["id"])).scale_id)
    )
    live_scale = live.scalar_one()
    db.add(
        AssessmentAnswer(
            assessment_id=created["id"],
            participant_id=self_p["id"],
            indicator_id=ind.id,
            answer_option_id=_opt_by_weight(live_scale, scale_weight).id,
        )
    )
    # Mark participant completed manually and drive to on_review.
    p = await db.get(AssessmentParticipant, self_p["id"])
    p.is_completed = True
    await db.commit()
    await advance_to_in_progress(db, tenant.id, created["id"])
    await service.change_status(db, tenant.id, created["id"], "on_review")
    return {
        "assessment_id": uuid.UUID(str(created["id"])),
        "indicator_id": ind.id,
        "scale": live_scale,
        "competence_id": comp.id,
        "participant_id": uuid.UUID(str(self_p["id"])),
    }


@pytest.mark.asyncio
async def test_start_calibration_locks_submissions(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)
    await service.start_calibration(db, tenant.id, ctx["assessment_id"])

    a = await db.get(Assessment, ctx["assessment_id"])
    assert a.calibration_in_progress is True

    # record_answer must be blocked with 409 while in_progress.
    with pytest.raises(Exception) as exc:
        await service.record_answer(
            db,
            tenant.id,
            user.id,  # caller user_id doesn't matter — we error before ownership.
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ctx["indicator_id"],
                answer_option_id=_opt_by_weight(ctx["scale"], 5).id,
            ),
        )
    assert getattr(exc.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_save_calibration_uses_calibrated_total(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Raw answer was weight=2 (=40%). Calibrated Total is set to
    weight=5 (=100%). After save the percent / level must reflect the
    calibrated value."""
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)
    await service.start_calibration(db, tenant.id, ctx["assessment_id"])
    calibrated_opt = _opt_by_weight(ctx["scale"], 5)
    detail = await service.save_calibration(
        db,
        tenant.id,
        ctx["assessment_id"],
        [
            CalibratedTotalItem(
                indicator_id=ctx["indicator_id"],
                answer_option_id=calibrated_opt.id,
            )
        ],
    )
    # calibration_in_progress is released after save.
    assert detail["calibration_in_progress"] is False
    assert detail["results"], f"expected results, got {detail!r}"
    result = next(
        r for r in detail["results"] if r["competence_id"] == ctx["competence_id"]
    )
    assert result["percent"] == 100

    # Detailed results carries the override + is_calibrated flag.
    details = await service.get_detailed_results(
        db, tenant.id, ctx["assessment_id"]
    )
    comp = details["competences"][0]
    q = comp["skill_levels"][0]["questions"][0]
    assert q["is_calibrated"] is True
    assert q["calibrated_answer_option_id"] == calibrated_opt.id
    assert q["overall_percent"] == 100


@pytest.mark.asyncio
async def test_detailed_results_exposes_overall_answer_option_id(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-185 REDO: the auto-computed Total ships with an option id so
    the calibration Select can pre-populate with the same answer the
    badge shows (instead of an empty "Total" placeholder)."""
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)

    details = await service.get_detailed_results(db, tenant.id, ctx["assessment_id"])
    q = details["competences"][0]["skill_levels"][0]["questions"][0]
    assert q["overall_answer_option_id"] is not None
    expected_opt = _opt_by_weight(ctx["scale"], 2)
    assert q["overall_answer_option_id"] == expected_opt.id, (
        "overall_answer_option_id must point at the nearest answer option to "
        f"the auto-computed Total (weight 2) — got {q['overall_answer_option_id']!r}"
    )


@pytest.mark.asyncio
async def test_per_level_breakdown_reflects_calibrated_total(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-185 REDO: Results-by-level popup must mirror the calibration
    override, just like the per-competence percent in the Results table.
    Raw answer was weight=2 (40%); calibrated to weight=5 (100%) — the
    breakdown row for that skill level must follow the override."""
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)
    await service.start_calibration(db, tenant.id, ctx["assessment_id"])
    calibrated_opt = _opt_by_weight(ctx["scale"], 5)
    await service.save_calibration(
        db,
        tenant.id,
        ctx["assessment_id"],
        [
            CalibratedTotalItem(
                indicator_id=ctx["indicator_id"],
                answer_option_id=calibrated_opt.id,
            )
        ],
    )

    detail = await service.get_assessment_detail(db, tenant.id, ctx["assessment_id"])
    result = next(
        r for r in detail["results"] if r["competence_id"] == ctx["competence_id"]
    )
    per_level = result["per_level_results"]
    assert per_level, "Expected at least one per-level row"
    assert per_level[0]["percent"] == 100, (
        "Per-level breakdown must reflect calibrated Total (100%), got "
        f"{per_level[0]['percent']!r}"
    )


@pytest.mark.asyncio
async def test_cancel_calibration_restores_raw_average(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """After save + cancel the per-competence percent must fall back to
    the raw survey value (40%)."""
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)
    await service.start_calibration(db, tenant.id, ctx["assessment_id"])
    calibrated_opt = _opt_by_weight(ctx["scale"], 5)
    await service.save_calibration(
        db,
        tenant.id,
        ctx["assessment_id"],
        [
            CalibratedTotalItem(
                indicator_id=ctx["indicator_id"],
                answer_option_id=calibrated_opt.id,
            )
        ],
    )
    detail = await service.cancel_calibration(
        db, tenant.id, ctx["assessment_id"]
    )
    result = next(
        r for r in detail["results"] if r["competence_id"] == ctx["competence_id"]
    )
    assert result["percent"] == 40

    # And the calibrated row was wiped.
    rows = (
        await db.execute(
            select(AssessmentCalibratedTotal).where(
                AssessmentCalibratedTotal.assessment_id == ctx["assessment_id"]
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_saved_calibration_keeps_submissions_locked(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """HRP-329: the questionnaire stays closed after Save calibration —
    a late survey would shift the baseline under the saved results."""
    ctx = await _setup_in_review(db, tenant, user, employee, scale_weight=2)
    await service.start_calibration(db, tenant.id, ctx["assessment_id"])
    detail = await service.save_calibration(
        db,
        tenant.id,
        ctx["assessment_id"],
        [
            CalibratedTotalItem(
                indicator_id=ctx["indicator_id"],
                answer_option_id=_opt_by_weight(ctx["scale"], 5).id,
            )
        ],
    )
    assert detail["calibration_in_progress"] is False
    # The detail payload tells the UI to keep Take/Evaluate hidden.
    assert detail["has_calibrated_totals"] is True

    with pytest.raises(Exception) as exc:
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ctx["indicator_id"],
                answer_option_id=_opt_by_weight(ctx["scale"], 5).id,
            ),
        )
    assert getattr(exc.value, "status_code", None) == 409

    # Cancel wipes the overrides — the questionnaire opens back up.
    detail = await service.cancel_calibration(db, tenant.id, ctx["assessment_id"])
    assert detail["has_calibrated_totals"] is False
