"""Add on_review assessment status and recompute done results.

Revision ID: asr1a1b2c3d4e5
Revises: cgr1a1b2c3d4e5
Create Date: 2026-05-11 11:00:00.000000

HRP-27: introduces the ``on_review`` status between ``in_progress`` and
``done`` so calibration can happen before an assessment is finalized.
``summarizing`` / ``await_result`` / ``done`` are kept (legacy code paths
still reference ``await_result``) but their sequence numbers shift up by
one to leave room for ``on_review`` at sequence 3.

HRP-62: rewrites ``_recompute_assessment_results`` to the role-mean
algorithm from the spec PDF. Existing assessments in ``done`` were
computed under the old algorithm, so this migration replays the new
algorithm against them in-place. Cancelled assessments are left alone —
their results were never meaningful.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from alembic import op
from sqlalchemy import bindparam, text

revision: str = "asr1a1b2c3d4e5"
down_revision: str | None = "cgr1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Re-sequence existing statuses to leave slot 3 for on_review.
    #    Cancelled keeps its sentinel sequence (99).
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 6 WHERE code = 'done'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 5 WHERE code = 'await_result'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 4 WHERE code = 'summarizing'")
    )

    # 2. Insert on_review. Idempotent so re-running the migration after a
    #    partial failure doesn't crash on the unique code constraint.
    bind.execute(
        text(
            """
            INSERT INTO assessment_statuses (id, code, title, sequence, created_at, updated_at)
            SELECT gen_random_uuid(), 'on_review', 'On Review', 3, now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM assessment_statuses WHERE code = 'on_review'
            )
            """
        )
    )

    # 3. Recompute results for every "done" assessment using the new
    #    role-mean algorithm. This is a one-shot data fix: post-migration,
    #    new assessments take the new path through change_status / the
    #    auto-transition in _maybe_mark_participant_completed.
    _recompute_done_assessments(bind)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DELETE FROM assessment_statuses WHERE code = 'on_review'"))
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 5 WHERE code = 'done'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 4 WHERE code = 'await_result'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET sequence = 3 WHERE code = 'summarizing'")
    )
    # No way to reconstruct the pre-fix percent values; leave the
    # recomputed results in place. Operators wanting the old numbers
    # back can restore from backup.


# --- one-shot recompute (mirrors backend/app/modules/assessment/service.py) ---


def _recompute_done_assessments(bind) -> None:  # type: ignore[no-untyped-def]
    done_q = bind.execute(
        text(
            """
            SELECT a.id, a.scale_id
            FROM assessments a
            JOIN assessment_statuses s ON s.id = a.status_id
            WHERE s.code = 'done'
            """
        )
    )
    done_rows = list(done_q)

    for assessment_id, scale_id in done_rows:
        _recompute_one(bind, assessment_id, scale_id)


def _recompute_one(bind, assessment_id: UUID, scale_id: UUID | None) -> None:  # type: ignore[no-untyped-def]
    if scale_id is None:
        return

    options = list(
        bind.execute(
            text(
                "SELECT id, weight, is_neutral FROM answer_options WHERE scale_id = :sid"
            ),
            {"sid": scale_id},
        )
    )
    options_by_id = {o[0]: o for o in options}
    weights = [o[1] for o in options if o[1] is not None and not o[2]]
    if not weights:
        return
    max_weight = max(weights)

    levels = list(
        bind.execute(
            text(
                """
                SELECT id, percent_from, percent_to
                FROM answer_scale_levels
                WHERE scale_id = :sid
                ORDER BY sort_index, percent_from
                """
            ),
            {"sid": scale_id},
        )
    )

    competences = list(
        bind.execute(
            text(
                "SELECT id, competence_id FROM assessment_competences WHERE assessment_id = :aid"
            ),
            {"aid": assessment_id},
        )
    )
    if not competences:
        return
    competence_ids = [c[1] for c in competences]

    role_by_participant = {
        p[0]: p[1]
        for p in bind.execute(
            text(
                "SELECT id, role FROM assessment_participants WHERE assessment_id = :aid"
            ),
            {"aid": assessment_id},
        )
    }

    indicators = list(
        bind.execute(
            text(
                """
                SELECT id, weight, skill_level_id, competence_id
                FROM indicators
                WHERE competence_id IN :cids
                """
            ).bindparams(bindparam("cids", expanding=True)),
            {"cids": competence_ids},
        )
    )
    indicators_by_id = {i[0]: i for i in indicators}

    answers = list(
        bind.execute(
            text(
                """
                SELECT participant_id, indicator_id, answer_option_id, score
                FROM assessment_answers
                WHERE assessment_id = :aid
                """
            ),
            {"aid": assessment_id},
        )
    )

    # Pull indicators referenced by stray answers but missing from the
    # competence list (defensive parity with the service implementation).
    answered_indicator_ids = {a[1] for a in answers}
    missing = answered_indicator_ids - set(indicators_by_id)
    if missing:
        for row in bind.execute(
            text(
                "SELECT id, weight, skill_level_id, competence_id FROM indicators WHERE id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list(missing)},
        ):
            indicators_by_id[row[0]] = row

    raw: dict = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    for participant_id, indicator_id, answer_option_id, score in answers:
        ind = indicators_by_id.get(indicator_id)
        if ind is None:
            continue
        role = role_by_participant.get(participant_id)
        if role is None:
            continue
        effective: float | None = None
        if answer_option_id is not None:
            opt = options_by_id.get(answer_option_id)
            if opt is None or opt[2] or opt[1] is None:
                continue
            effective = float(opt[1])
        elif score is not None:
            effective = float(score)
        if effective is None:
            continue
        raw[ind[3]][role][ind[2]][indicator_id].append(effective)

    existing = {
        r[1]: r[0]
        for r in bind.execute(
            text(
                "SELECT id, competence_id FROM assessment_results WHERE assessment_id = :aid"
            ),
            {"aid": assessment_id},
        )
    }

    for _, competence_id in competences:
        role_data = raw.get(competence_id, {})
        role_percents: list[float] = []
        for _role, levels_data in role_data.items():
            level_percents: list[float] = []
            for _level_id, indicator_scores in levels_data.items():
                weighted_sum = 0.0
                weight_sum = 0.0
                for indicator_id, scores in indicator_scores.items():
                    if not scores:
                        continue
                    indicator_avg = sum(scores) / len(scores)
                    raw_w = indicators_by_id[indicator_id][1]
                    weight = float(raw_w) if raw_w else 1.0
                    weighted_sum += indicator_avg * weight
                    weight_sum += weight
                if weight_sum == 0:
                    continue
                level_avg = weighted_sum / weight_sum
                level_percents.append(level_avg / max_weight * 100.0)
            if level_percents:
                role_percents.append(sum(level_percents) / len(level_percents))

        if role_percents:
            final_percent = sum(role_percents) / len(role_percents)
            avg = round(final_percent / 100.0, 4)
            percent: int | None = round(final_percent)
        else:
            avg = 0.0
            percent = None

        level_id: UUID | None = None
        if percent is not None and levels:
            for lv_id, p_from, p_to in levels:
                if p_from <= percent <= p_to:
                    level_id = lv_id
                    break

        if competence_id in existing:
            bind.execute(
                text(
                    """
                    UPDATE assessment_results
                    SET avg_score = :avg, percent = :pct, level_id = :lid
                    WHERE id = :rid
                    """
                ),
                {
                    "avg": avg,
                    "pct": percent,
                    "lid": level_id,
                    "rid": existing[competence_id],
                },
            )
        else:
            bind.execute(
                text(
                    """
                    INSERT INTO assessment_results (id, assessment_id, competence_id, avg_score, percent, level_id, created_at, updated_at)
                    VALUES (gen_random_uuid(), :aid, :cid, :avg, :pct, :lid, now(), now())
                    """
                ),
                {
                    "aid": assessment_id,
                    "cid": competence_id,
                    "avg": avg,
                    "pct": percent,
                    "lid": level_id,
                },
            )
