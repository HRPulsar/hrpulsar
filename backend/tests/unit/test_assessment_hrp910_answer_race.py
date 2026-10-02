"""HRP-910: two saves of one question - one after the other or at the same
time - leave one answer row and both succeed; the migration's repair keeps
the latest duplicate."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from pathlib import Path

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import AssessmentAnswer
from app.modules.assessment.schemas import AnswerRecord
from sqlalchemy import select, text

from tests.unit.test_assessment_hrp146_draft_answers import (
    _make_self_assessment_ready,
)

pytestmark = pytest.mark.asyncio

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/v2work13_answer_unique.py"
)


def _save(session, tenant, user, ctx, option):
    return service.record_answer(
        session,
        tenant.id,
        user.id,
        ctx["assessment_id"],
        AnswerRecord(
            participant_id=ctx["participant_id"],
            indicator_id=ctx["indicators"][0].id,
            answer_option_id=option.id,
            score=option.weight,
        ),
    )


async def _rows(db, ctx):
    return (
        (
            await db.execute(
                select(AssessmentAnswer).where(
                    AssessmentAnswer.participant_id == ctx["participant_id"],
                    AssessmentAnswer.indicator_id == ctx["indicators"][0].id,
                )
            )
        )
        .scalars()
        .all()
    )


async def test_second_save_succeeds_and_is_the_current_answer(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    ctx = await _make_self_assessment_ready(db, tenant, user, employee)
    low, high = ctx["opt_by_weight"][1], ctx["opt_by_weight"][4]
    first = await _save(db, tenant, user, ctx, low)
    second = await _save(db, tenant, user, ctx, high)
    assert second["id"] == first["id"]
    assert second["score"] == high.weight
    rows = await _rows(db, ctx)
    assert len(rows) == 1 and rows[0].answer_option_id == high.id


async def test_concurrent_saves_of_one_question_keep_one_row(
    db, session_factory, tenant, user, employee, assessment_statuses, assessment_types
):
    """Two sessions save the same question at once - the race that used to
    leave two rows. Both calls succeed and agree on the single row."""
    ctx = await _make_self_assessment_ready(db, tenant, user, employee)
    a, b = ctx["opt_by_weight"][2], ctx["opt_by_weight"][3]
    async with session_factory() as s1, session_factory() as s2:
        r1, r2 = await asyncio.gather(
            _save(s1, tenant, user, ctx, a), _save(s2, tenant, user, ctx, b)
        )
    assert r1["id"] == r2["id"]
    rows = await _rows(db, ctx)
    assert len(rows) == 1
    assert rows[0].answer_option_id in {a.id, b.id}


async def test_migration_repair_keeps_the_latest_duplicate(db):
    spec = importlib.util.spec_from_file_location("v2work13", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # A temp table with the real table's name shadows it for this session
    # only (pg_temp leads search_path), so the migration's exact SQL runs
    # against duplicates the live unique constraint would refuse.
    await db.execute(
        text(
            "CREATE TEMP TABLE assessment_answers "
            "(id uuid, participant_id uuid, indicator_id uuid, updated_at timestamptz)"
        )
    )
    p, q = uuid.uuid4(), uuid.uuid4()
    older, latest, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO assessment_answers VALUES "
            "(:older, :p, :q, '2026-09-20T10:00:00Z'), "
            "(:latest, :p, :q, '2026-09-20T10:00:05Z'), "
            "(:other, :p, gen_random_uuid(), '2026-09-20T09:00:00Z')"
        ),
        {"older": older, "latest": latest, "other": other, "p": p, "q": q},
    )
    await db.execute(text(mod.DEDUPE_SQL))
    ids = set((await db.execute(text("SELECT id FROM assessment_answers"))).scalars())
    assert ids == {latest, other}
    await db.rollback()
