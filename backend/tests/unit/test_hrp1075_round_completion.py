"""HRP-1075: one rule decides whether a round can be marked complete.

Every Critical competence scored by at least one evaluator - internal or a
submitted external one - and at least one competence scored at all. The
caller's own sheet, started but empty, does not take that away. The same
function lights the button (``round_aggregate``) and guards the action.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.manager_assessment_schemas import CompetenceScoreIn
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    CRITICAL_COMPETENCE_ID,
    _external_sheet,
    _make_extra_user,
)
from tests.unit.test_hrp373_round_evaluators import _grant_role
from tests.unit.test_hrp376_round_lifecycle import _round

IMPORTANT_ID = normalize_competence_id("sales")


async def _external_scores(db: AsyncSession, tenant, cv, rd_id, competence_id):
    external = await _external_sheet(db, tenant, cv, rd_id, name="Ext")
    await service.set_competence_score(
        db,
        tenant.id,
        None,
        external.id,
        competence_id,
        CompetenceScoreIn(score_value=1),
    )
    await service.submit_assessment(db, tenant.id, None, external.id)


async def test_an_external_evaluator_scoring_the_critical_ones_is_enough(
    db: AsyncSession, tenant, user
):
    cv, rd_id = await _round(db, tenant, user)
    await _external_scores(db, tenant, cv, rd_id, CRITICAL_COMPETENCE_ID)
    agg = await service.round_aggregate(db, tenant.id, rd_id, viewer_user_id=user.id)
    assert agg["can_complete"] is True
    assert agg["unscored_critical_ids"] == []

    # Start scoring oneself (an empty draft sheet, the gate now up for the
    # caller): still completable - what the external evaluator scored counts.
    await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
    await service.get_or_create_assessment(
        db, tenant.id, rd_id, evaluator_user_id=user.id
    )
    agg = await service.round_aggregate(db, tenant.id, rd_id, viewer_user_id=user.id)
    assert agg["can_complete"] is True

    rd = await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
    assert rd["status"] == "complete"


async def test_a_colleagues_draft_counts_behind_the_anchoring_gate(
    db: AsyncSession, tenant, user, admin_role
):
    cv, rd_id = await _round(db, tenant, user)
    colleague = await _make_extra_user(db, tenant)
    await _grant_role(db, tenant, colleague, "manager")
    await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
    with patch("app.core.events.publish", new=AsyncMock()):
        await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
    theirs = await service.get_or_create_assessment(
        db, tenant.id, rd_id, evaluator_user_id=colleague.id
    )
    await service.set_competence_score(
        db,
        tenant.id,
        colleague.id,
        theirs.id,
        CRITICAL_COMPETENCE_ID,
        CompetenceScoreIn(score_value=3),
    )
    await service.get_or_create_assessment(
        db, tenant.id, rd_id, evaluator_user_id=user.id
    )

    agg = await service.round_aggregate(db, tenant.id, rd_id, viewer_user_id=user.id)
    # The caller's own numbers only (HRP-373) - and still completable.
    assert agg["competences"] == []
    assert agg["can_complete"] is True


async def test_an_unscored_critical_competence_blocks_the_button_and_the_action(
    db: AsyncSession, tenant, user
):
    cv, rd_id = await _round(db, tenant, user)
    agg = await service.round_aggregate(db, tenant.id, rd_id)
    assert agg["can_complete"] is False
    with pytest.raises(HTTPException) as exc:
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
    assert exc.value.status_code == 409

    await _external_scores(db, tenant, cv, rd_id, IMPORTANT_ID)
    agg = await service.round_aggregate(db, tenant.id, rd_id)
    assert agg["can_complete"] is False
    assert agg["unscored_critical_ids"] == [str(CRITICAL_COMPETENCE_ID)]
    with pytest.raises(HTTPException) as exc:
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "Score at least one competence and every Critical competence before completing the round"
    )


async def test_a_revoked_external_sheet_does_not_count(db: AsyncSession, tenant, user):
    cv, rd_id = await _round(db, tenant, user)
    await _external_scores(db, tenant, cv, rd_id, CRITICAL_COMPETENCE_ID)
    invites = await service.list_manager_invites(db, tenant.id, cv.id)
    await service.revoke_invite(
        db, tenant.id, user.id, uuid.UUID(str(invites[0]["id"]))
    )
    agg = await service.round_aggregate(db, tenant.id, rd_id)
    assert agg["can_complete"] is False
