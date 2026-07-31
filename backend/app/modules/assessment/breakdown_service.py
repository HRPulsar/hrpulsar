"""Per-(competence, skill-level) breakdown math, split out of ``assessment.service``.

Leaf module: depends on ``assessment.models`` + ``answer_scale_service`` (for
``_load_scale_full``) + a lazy ``competence.models`` import. ``compute_per_level_breakdowns_batch``
is the public entry point shared by the Competence Overview (``employee``) and
Talent Market pages — it lives here (rather than as a private helper deep-imported
from ``assessment.service``) so cross-module callers import a public, leaf function.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.answer_scale_service import _load_scale_full
from app.modules.assessment.models import (
    AnswerOption,
    Assessment,
    AssessmentAnswer,
    AssessmentCalibratedTotal,
    AssessmentCompetence,
    AssessmentParticipant,
)


async def _compute_per_level_breakdown(
    db: AsyncSession, assessment: Assessment
) -> dict[uuid.UUID, list[dict]]:
    """HRP-90: aggregate answers per (competence, skill_level) so the Results
    block can render a per-level popup next to each competence.

    Returns ``{competence_id: [{skill_level_id, skill_level_title,
    sort_index, percent}, ...]}`` ordered by ``sort_index``. Levels with
    no usable answers are omitted. When the ``AssessmentCompetence`` row
    declares a target ``skill_level_id``, levels above it are dropped so
    the popup mirrors the questionnaire's cascade (Basic / Basic+Inter /
    Basic+Inter+Adv depending on the required level).

    Mirrors the per-competence aggregation in
    ``_recompute_assessment_results`` but stops at the per-level step
    instead of averaging across levels — same scale, same weight rules,
    same neutral-option filtering, so popup percents stay consistent
    with the stored Percent column.

    Thin wrapper over ``compute_per_level_breakdowns_batch`` so single-
    assessment callers (``get_detailed_results`` + tests) keep working
    while the multi-assessment paths (HRP-153 Competence Overview) drop
    the per-call SQL fan-out.
    """
    out = await compute_per_level_breakdowns_batch(db, [assessment])
    return out.get(assessment.id, {})


async def compute_per_level_breakdowns_batch(
    db: AsyncSession, assessments: list[Assessment]
) -> dict[uuid.UUID, dict[uuid.UUID, list[dict]]]:
    """Batched variant of ``_compute_per_level_breakdown``.

    Same math, ~6 SQL statements regardless of input size — versus the
    single-assessment version's 5 statements *per* assessment. HRP-153
    Competence Overview can call this once for a 20-assessment employee
    instead of issuing 100+ round-trips.

    Returns ``{assessment_id: {competence_id: [rows...]}}``. Assessments
    that contributed no usable rows are simply absent from the outer map
    — callers should treat missing keys as ``{}``.
    """
    from app.modules.competence.models import Indicator, SkillLevel

    if not assessments:
        return {}

    assessment_ids = [a.id for a in assessments]
    assessment_by_id: dict[uuid.UUID, Assessment] = {a.id: a for a in assessments}

    competences_q = await db.execute(
        select(AssessmentCompetence).where(
            AssessmentCompetence.assessment_id.in_(assessment_ids)
        )
    )
    competences_all = list(competences_q.scalars().all())
    if not competences_all:
        return {}

    competences_by_assessment: dict[uuid.UUID, list[AssessmentCompetence]] = {}
    for ac in competences_all:
        competences_by_assessment.setdefault(ac.assessment_id, []).append(ac)

    # Load each distinct scale once — most batches share the tenant's
    # default scale, so this typically collapses to a single load.
    scale_ids = {a.scale_id for a in assessments if a.scale_id is not None}
    options_by_scale: dict[uuid.UUID, dict[uuid.UUID, AnswerOption]] = {}
    max_weight_by_scale: dict[uuid.UUID, float] = {}
    for sid in scale_ids:
        scale = await _load_scale_full(db, sid)
        if scale is None:
            continue
        options_by_scale[sid] = {o.id: o for o in scale.options}
        weights = [
            o.weight for o in scale.options if not o.is_neutral and o.weight is not None
        ]
        max_weight_by_scale[sid] = max(weights) if weights else 0

    participants_q = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id.in_(assessment_ids)
        )
    )
    role_by_participant: dict[uuid.UUID, str] = {
        p.id: p.role for p in participants_q.scalars().all()
    }
    answers_q = await db.execute(
        select(AssessmentAnswer).where(
            AssessmentAnswer.assessment_id.in_(assessment_ids)
        )
    )
    answers_all = list(answers_q.scalars().all())
    answers_by_assessment: dict[uuid.UUID, list[AssessmentAnswer]] = {}
    for ans in answers_all:
        answers_by_assessment.setdefault(ans.assessment_id, []).append(ans)

    competence_ids = {ac.competence_id for ac in competences_all}
    ind_q = await db.execute(
        select(Indicator).where(Indicator.competence_id.in_(competence_ids))
    )
    indicators_by_id: dict[uuid.UUID, Indicator] = {
        ind.id: ind for ind in ind_q.scalars().all()
    }
    answered_ids = {ans.indicator_id for ans in answers_all}
    missing = answered_ids - set(indicators_by_id)
    if missing:
        extra_q = await db.execute(select(Indicator).where(Indicator.id.in_(missing)))
        for ind in extra_q.scalars().all():
            indicators_by_id[ind.id] = ind

    skill_level_ids: set[uuid.UUID] = set()
    for ind in indicators_by_id.values():
        if ind.skill_level_id:
            skill_level_ids.add(ind.skill_level_id)
    for ac in competences_all:
        if ac.skill_level_id:
            skill_level_ids.add(ac.skill_level_id)
    skill_levels_by_id: dict[uuid.UUID, SkillLevel] = {}
    if skill_level_ids:
        sl_q = await db.execute(
            select(SkillLevel).where(SkillLevel.id.in_(skill_level_ids))
        )
        skill_levels_by_id = {sl.id: sl for sl in sl_q.scalars().all()}

    # HRP-185 REDO: load calibrated totals so the per-level popup reflects
    # manual overrides the same way the Results table does. One query for
    # the whole batch keeps the breakdown call N+1-free.
    calibrated_rows = await db.execute(
        select(AssessmentCalibratedTotal).where(
            AssessmentCalibratedTotal.assessment_id.in_(assessment_ids)
        )
    )
    calibrated_by_assessment: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
    for row in calibrated_rows.scalars().all():
        calibrated_by_assessment.setdefault(row.assessment_id, {})[
            row.indicator_id
        ] = row.answer_option_id

    out_all: dict[uuid.UUID, dict[uuid.UUID, list[dict]]] = {}
    for asmt_id, competences in competences_by_assessment.items():
        assessment = assessment_by_id[asmt_id]
        scale_id = assessment.scale_id
        if scale_id is None or scale_id not in options_by_scale:
            continue
        options_by_id = options_by_scale[scale_id]
        max_weight = max_weight_by_scale.get(scale_id, 0)
        if max_weight <= 0:
            continue

        answers = answers_by_assessment.get(asmt_id, [])
        if not answers:
            continue

        out = _compute_breakdown_for_assessment(
            competences=competences,
            answers=answers,
            options_by_id=options_by_id,
            max_weight=max_weight,
            role_by_participant=role_by_participant,
            indicators_by_id=indicators_by_id,
            skill_levels_by_id=skill_levels_by_id,
            calibrated_by_indicator=calibrated_by_assessment.get(asmt_id, {}),
        )
        if out:
            out_all[asmt_id] = out

    return out_all


def _compute_breakdown_for_assessment(
    *,
    competences: list[AssessmentCompetence],
    answers: list[AssessmentAnswer],
    options_by_id: dict[uuid.UUID, AnswerOption],
    max_weight: float,
    role_by_participant: dict[uuid.UUID, str],
    indicators_by_id: dict[uuid.UUID, Any],
    skill_levels_by_id: dict[uuid.UUID, Any],
    calibrated_by_indicator: dict[uuid.UUID, uuid.UUID] | None = None,
) -> dict[uuid.UUID, list[dict]]:
    """Pure per-assessment math factored out of the batch loop.

    Takes pre-loaded reference data and runs the role-weighted aggregation
    + cascade trimming that the original single-assessment function did
    inline. Lives at module level so the batch path doesn't repeat the
    inner-loop body.
    """

    calibrated_by_indicator = calibrated_by_indicator or {}
    # HRP-185 REDO: when a reviewer has pinned an indicator's Total, the
    # per-level breakdown should mirror what the Results table uses —
    # otherwise the popup keeps showing the original answer average even
    # after calibration. Collapse the indicator's score list to a single
    # synthetic value (the calibrated option's weight) so downstream
    # math runs against the override.

    # raw[competence][role][skill_level][indicator] = list of scores
    raw: dict[uuid.UUID, dict[str, dict[uuid.UUID, dict[uuid.UUID, list[float]]]]] = {}
    for ans in answers:
        answer_ind = indicators_by_id.get(ans.indicator_id)
        if answer_ind is None or answer_ind.skill_level_id is None:
            continue
        role = role_by_participant.get(ans.participant_id)
        if role is None:
            continue
        if answer_ind.id in calibrated_by_indicator:
            # The calibrated value is applied below, post-aggregation —
            # skip the per-role answer here so it doesn't dilute the
            # synthetic score.
            continue
        score: float | None = None
        if ans.answer_option_id is not None:
            opt = options_by_id.get(ans.answer_option_id)
            if opt is None or opt.is_neutral or opt.weight is None:
                continue
            score = float(opt.weight)
        elif ans.score is not None:
            score = float(ans.score)
        if score is None:
            continue
        (
            raw.setdefault(answer_ind.competence_id, {})
            .setdefault(role, {})
            .setdefault(answer_ind.skill_level_id, {})
            .setdefault(answer_ind.id, [])
            .append(score)
        )

    # Layer calibrated overrides on top. Use a synthetic "calibrated"
    # role so each override contributes exactly one weighted sample per
    # (competence, skill_level, indicator) — averaging across multiple
    # roles for the same calibrated indicator would re-introduce the
    # original answers via the divisor.
    for ind_id, option_id in calibrated_by_indicator.items():
        ind = indicators_by_id.get(ind_id)
        if ind is None or ind.skill_level_id is None:
            continue
        opt = options_by_id.get(option_id)
        if opt is None or opt.weight is None:
            continue
        (
            raw.setdefault(ind.competence_id, {})
            .setdefault("__calibrated__", {})
            .setdefault(ind.skill_level_id, {})
            .setdefault(ind.id, [])
            .append(float(opt.weight))
        )

    out: dict[uuid.UUID, list[dict]] = {}
    for ac in competences:
        comp_id = ac.competence_id
        target_sort: int | None = None
        if ac.skill_level_id and ac.skill_level_id in skill_levels_by_id:
            target_sort = skill_levels_by_id[ac.skill_level_id].sort_index

        per_level_role_percents: dict[uuid.UUID, list[float]] = {}
        for _role, levels_data in raw.get(comp_id, {}).items():
            for sl_id, indicator_scores in levels_data.items():
                weighted_sum = 0.0
                weight_sum = 0.0
                for indicator_id, scores in indicator_scores.items():
                    if not scores:
                        continue
                    indicator_avg = sum(scores) / len(scores)
                    raw_weight = indicators_by_id[indicator_id].weight
                    weight = float(raw_weight) if raw_weight else 1.0
                    weighted_sum += indicator_avg * weight
                    weight_sum += weight
                if weight_sum == 0:
                    continue
                level_avg = weighted_sum / weight_sum
                per_level_role_percents.setdefault(sl_id, []).append(
                    level_avg / max_weight * 100.0
                )

        rows: list[dict] = []
        for sl_id, role_pcts in per_level_role_percents.items():
            sl = skill_levels_by_id.get(sl_id)
            if sl is None or not role_pcts:
                continue
            if target_sort is not None and sl.sort_index > target_sort:
                continue
            rows.append(
                {
                    "skill_level_id": sl.id,
                    "skill_level_title": sl.title,
                    # HRP-479: origin levels localize on the frontend.
                    "skill_level_i18n_key": sl.i18n_key,
                    "sort_index": sl.sort_index,
                    "percent": round(sum(role_pcts) / len(role_pcts)),
                }
            )
        rows.sort(key=lambda r: r["sort_index"])
        if rows:
            out[comp_id] = rows
    return out
