"""HRP-185 REDO #3: Detailed results' "Percent for Skill level" line must
reflect the calibrated Total just like the Results table and the
Results-by-level popup. The previous implementation was deriving the
per-level percent purely from the raw role answers, so even after Save
calibration the popup kept showing the pre-calibration number.
"""

from __future__ import annotations

import pytest
from app.modules.assessment import service
from app.modules.assessment.schemas import CalibratedTotalItem

from tests.unit.test_hrp185_calibrate_totals import _opt_by_weight, _setup_in_review


@pytest.mark.asyncio
async def test_detailed_results_skill_level_percent_uses_calibrated_total(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Raw answer 2/5 (40%) calibrated to 5/5 (100%) — the per-skill-level
    percent on Detailed results must follow the override (100), not the
    raw 40 the answer weights would yield."""
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

    details = await service.get_detailed_results(
        db, tenant.id, ctx["assessment_id"]
    )
    comp = details["competences"][0]
    level = comp["skill_levels"][0]
    assert level["percent_for_skill_level"] == 100, (
        "Detailed results 'Percent for Skill level' must mirror the "
        f"calibrated Total (100), got {level['percent_for_skill_level']!r}"
    )


@pytest.mark.asyncio
async def test_detailed_results_skill_level_percent_restored_after_cancel(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Cancel calibration must put the per-skill-level percent back on the
    raw 40 from the original answer (no leftover override)."""
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
    await service.cancel_calibration(db, tenant.id, ctx["assessment_id"])

    details = await service.get_detailed_results(
        db, tenant.id, ctx["assessment_id"]
    )
    level = details["competences"][0]["skill_levels"][0]
    assert level["percent_for_skill_level"] == 40, (
        "After Cancel the per-skill-level percent must fall back to the "
        f"raw answer weight (40%), got {level['percent_for_skill_level']!r}"
    )
