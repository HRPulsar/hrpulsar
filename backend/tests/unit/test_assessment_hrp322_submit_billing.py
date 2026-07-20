"""HRP-322: the survey Sheet autosaves every option change through
``record_answer``, so billing that function charged the participant per
answer (and again per re-pick of the same indicator). The charge now
goes through the ``billing_hooks`` seam in ``record_answer`` — exactly
once, when ``_maybe_mark_participant_completed`` reports the
participant's completion flip.

These tests monkeypatch the seam (community no-ops) with recorders and
walk a two-indicator self-assessment through partial answers, re-picks,
completion and post-completion edits.
"""

from __future__ import annotations

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import AssessmentParticipant
from app.modules.assessment.schemas import AnswerRecord
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_assessment_hrp146_draft_answers import (
    _make_self_assessment_ready,
)

pytestmark = pytest.mark.asyncio


def _install_recorders(monkeypatch):
    """Replace the no-op seam with call recorders, the same way
    ``ee.billing.register_billing()`` rebinds it in SaaS."""
    from app.core import billing_hooks

    prechecks: list[tuple[str, float | None]] = []
    consumes: list[tuple[str, float | None]] = []

    async def _resolve(db, tenant_id, action, *, amount_override=None):
        return 3.0

    async def _precheck(db, tenant_id, action, *, amount_override=None):
        prechecks.append((action, amount_override))

    async def _consume(db, tenant_id, user_id, action, *, amount_override=None):
        consumes.append((action, amount_override))

    monkeypatch.setattr(billing_hooks, "resolve_cost", _resolve)
    monkeypatch.setattr(billing_hooks, "precheck_action", _precheck)
    monkeypatch.setattr(billing_hooks, "consume_action", _consume)
    return prechecks, consumes


async def _answer(db, tenant, user, ctx, indicator, option):
    await service.record_answer(
        db,
        tenant.id,
        user.id,
        ctx["assessment_id"],
        AnswerRecord(
            participant_id=ctx["participant_id"],
            indicator_id=indicator.id,
            answer_option_id=option.id,
        ),
    )


class TestSurveyBilledOnceOnCompletion:
    async def test_partial_answers_and_repicks_are_free(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        monkeypatch,
    ):
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        prechecks, consumes = _install_recorders(monkeypatch)
        ind = ctx["indicators"][0]

        await _answer(db, tenant, user, ctx, ind, ctx["opt_by_weight"][1])
        # Re-pick the same indicator — the exact case QA flagged:
        # changing an already-given answer must not charge either.
        await _answer(db, tenant, user, ctx, ind, ctx["opt_by_weight"][4])

        assert consumes == [], "an unfinished survey must not charge"
        assert prechecks == [], "autosave must not even precheck"

    async def test_completion_charges_exactly_once(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        monkeypatch,
    ):
        ctx = await _make_self_assessment_ready(db, tenant, user, employee)
        prechecks, consumes = _install_recorders(monkeypatch)
        ind_a, ind_b = ctx["indicators"]
        opt = ctx["opt_by_weight"][3]

        await _answer(db, tenant, user, ctx, ind_a, opt)
        assert consumes == []

        # The last unanswered indicator completes the survey → one charge,
        # with the resolved cost pinned for both precheck and consume.
        await _answer(db, tenant, user, ctx, ind_b, opt)
        assert prechecks == [("assessment.submit_answers", 3.0)]
        assert consumes == [("assessment.submit_answers", 3.0)]

        participant = await db.get(AssessmentParticipant, ctx["participant_id"])
        assert participant.is_completed is True

        # Editing an answer after completion stays free — the completed
        # participant short-circuits before the flip.
        await _answer(db, tenant, user, ctx, ind_a, ctx["opt_by_weight"][2])
        assert consumes == [("assessment.submit_answers", 3.0)]
