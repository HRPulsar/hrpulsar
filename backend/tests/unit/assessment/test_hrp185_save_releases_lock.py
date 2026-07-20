"""HRP-329 (supersedes HRP-185 REDO #3): Save calibration keeps the
questionnaire closed.

HRP-185 REDO #3 originally made Save release the lock so unfinished
participants could still answer. QA reversed that decision in HRP-329:
once calibrated results are saved they are final — a late survey would
shift the baseline underneath them. The in-progress flag still drops on
Save (the reviewer is no longer editing), but submissions stay rejected
while calibrated Totals exist; Cancel calibration wipes them and reopens
the questionnaire (pinned in test_hrp185_calibrate_totals).
"""

from __future__ import annotations

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.assessment.schemas import AnswerRecord, CalibratedTotalItem

from tests.unit.test_hrp185_calibrate_totals import _opt_by_weight, _setup_in_review


@pytest.mark.asyncio
async def test_record_answer_blocked_after_save_calibration(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
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

    a = await db.get(Assessment, ctx["assessment_id"])
    assert a.calibration_in_progress is False

    # HRP-329: saved calibration is final — submissions stay closed.
    with pytest.raises(Exception) as exc:
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            ctx["assessment_id"],
            AnswerRecord(
                participant_id=ctx["participant_id"],
                indicator_id=ctx["indicator_id"],
                answer_option_id=_opt_by_weight(ctx["scale"], 3).id,
            ),
        )
    assert getattr(exc.value, "status_code", None) == 409
