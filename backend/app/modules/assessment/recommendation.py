"""Grade recommendation engine.

HRP-170: the Recommended grade chart is computed for assessments whose
criteria type is ``target_position`` (specific grade or all grades) or
``current_positions`` (specialization derived from the employee's current
position). The chart becomes visible once the assessment reaches the
``On Review`` checkpoint and stays available for terminal statuses
(``done`` or ``cancelled`` when it was cancelled out of ``on_review``).

Per-grade math (HRP-170 spec):

  1. For every (grade, competence) link compute the per-skill-level
     percent across the levels at or below the competence's required
     skill level (Basic → Basic; Intermediate → mean(Basic, Intermediate);
     Advanced → mean(Basic, Intermediate, Advanced)).
  2. Per-skill-level percent: weighted average of per-indicator role
     means inside that level, divided by the maximum scale weight.
  3. Competence percent = mean of included level percents.
     A competence with no usable answers at any included level
     contributes 0%.
  4. Grade percent = mean of competence percents.

The recommendation payload is cached on the ``Assessment`` row
(``recommended_grade_id`` + ``recommendation_payload``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentAnswer,
    AssessmentParticipant,
    AssessmentResult,
)
from app.modules.assessment.schemas import (
    AssessmentRecommendation,
    GradeRecommendationItem,
)
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)

# HRP-170: statuses where the recommendation chart is available. ``on_review``
# unlocks the preliminary view, ``done`` is the final value; ``cancelled``
# qualifies only when AssessmentResult rows exist (i.e. the assessment had
# already entered ``on_review`` before being closed).
ELIGIBLE_STATUSES = ("on_review", "done", "cancelled")


def _status_code(assessment: Assessment) -> str | None:
    return assessment.status.code if assessment.status is not None else None


async def _resolve_specialization_id(
    db: AsyncSession, assessment: Assessment
) -> uuid.UUID | None:
    """Return the specialization to evaluate against.

    For ``target_position`` the value is stored on the assessment row.
    For ``current_positions`` it is derived from the assessee's current
    ``Position.specialization_id`` — keeps the recommendation in sync with
    the matrix the questionnaire walked at evaluation time.
    """
    if assessment.criteria_type == "target_position":
        return assessment.specialization_id
    if assessment.criteria_type == "current_positions":
        from app.modules.employee.models import Employee
        from app.modules.position.models import Position

        emp = await db.get(Employee, assessment.employee_id)
        if emp is None or emp.position_id is None:
            return None
        pos = await db.get(Position, emp.position_id)
        if pos is None:
            return None
        return pos.specialization_id
    return None


async def _has_results(db: AsyncSession, assessment_id: uuid.UUID) -> bool:
    row = await db.execute(
        select(AssessmentResult.id).where(
            AssessmentResult.assessment_id == assessment_id
        ).limit(1)
    )
    return row.first() is not None


async def compute_grade_recommendation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment: Assessment,
) -> AssessmentRecommendation | None:
    """Compute (and cache) the grade recommendation for an assessment.

    Returns ``None`` when the assessment is not eligible:
      * ``criteria_type`` is not ``target_position`` / ``current_positions``
      * the specialization could not be resolved
      * ``passing_score`` is unset (legacy / no threshold)
      * status code is not in :data:`ELIGIBLE_STATUSES`
      * status is ``cancelled`` and no ``AssessmentResult`` rows exist
        (the assessment was cancelled before On Review)
    """
    if assessment.criteria_type not in ("target_position", "current_positions"):
        return None
    if assessment.passing_score is None:
        return None
    code = _status_code(assessment)
    if code not in ELIGIBLE_STATUSES:
        return None
    if code == "cancelled" and not await _has_results(db, assessment.id):
        return None

    specialization_id = await _resolve_specialization_id(db, assessment)
    if specialization_id is None:
        return None

    grade_specs_q = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
    )
    grade_specs = list(grade_specs_q.scalars().all())
    if not grade_specs:
        return None

    grade_ids = [gs.grade_id for gs in grade_specs]
    grade_titles_q = await db.execute(
        select(DictionaryItem).where(DictionaryItem.id.in_(grade_ids))
    )
    grade_title_by_id = {g.id: g.title for g in grade_titles_q.scalars().all()}

    links_q = await db.execute(
        select(GradeCompetenceLink).where(
            GradeCompetenceLink.grade_specialization_id.in_(
                [gs.id for gs in grade_specs]
            )
        )
    )
    links_by_spec: dict[uuid.UUID, list[GradeCompetenceLink]] = {}
    for link in links_q.scalars().all():
        links_by_spec.setdefault(link.grade_specialization_id, []).append(link)

    # All distinct skill_level ids referenced by any link — used to look up
    # ``sort_index`` so we can pick "levels at or below target" for each
    # competence.
    required_sl_ids = {
        link.skill_level_id for links in links_by_spec.values() for link in links
        if link.skill_level_id is not None
    }
    skill_levels_by_id: dict[uuid.UUID, SkillLevel] = {}
    if required_sl_ids:
        sl_q = await db.execute(
            select(SkillLevel).where(SkillLevel.id.in_(required_sl_ids))
        )
        skill_levels_by_id = {sl.id: sl for sl in sl_q.scalars().all()}

    scale: AnswerScale | None = None
    options_by_id: dict[uuid.UUID, AnswerOption] = {}
    max_scale_weight: float = 0.0
    if assessment.scale_id is not None:
        scale_q = await db.execute(
            select(AnswerScale)
            .options(selectinload(AnswerScale.options))
            .where(AnswerScale.id == assessment.scale_id)
        )
        scale = scale_q.scalar_one_or_none()
        if scale is not None:
            options_by_id = {o.id: o for o in scale.options}
            scoring_weights = [
                float(o.weight)
                for o in scale.options
                if not o.is_neutral and o.weight is not None
            ]
            max_scale_weight = max(scoring_weights) if scoring_weights else 0.0

    participants_q = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment.id
        )
    )
    role_by_participant: dict[uuid.UUID, str] = {
        p.id: p.role for p in participants_q.scalars().all()
    }

    answers_q = await db.execute(
        select(AssessmentAnswer).where(AssessmentAnswer.assessment_id == assessment.id)
    )
    answers = list(answers_q.scalars().all())

    indicator_ids = {a.indicator_id for a in answers}
    indicators_by_id: dict[uuid.UUID, Indicator] = {}
    if indicator_ids:
        ind_q = await db.execute(
            select(Indicator).where(Indicator.id.in_(indicator_ids))
        )
        indicators_by_id = {i.id: i for i in ind_q.scalars().all()}

    # Indicator skill_levels (separate from required_sl_ids — we need their
    # sort_index too for cascade filtering).
    indicator_sl_ids = {
        ind.skill_level_id for ind in indicators_by_id.values()
        if ind.skill_level_id is not None
    }
    missing_sl = indicator_sl_ids - set(skill_levels_by_id)
    if missing_sl:
        sl_extra_q = await db.execute(
            select(SkillLevel).where(SkillLevel.id.in_(missing_sl))
        )
        for sl in sl_extra_q.scalars().all():
            skill_levels_by_id[sl.id] = sl

    # raw[(competence_id, skill_level_id, role, indicator_id)] = [weight, ...]
    raw: dict[
        tuple[uuid.UUID, uuid.UUID | None, str, uuid.UUID], list[float]
    ] = {}
    for ans in answers:
        ind = indicators_by_id.get(ans.indicator_id)
        if ind is None:
            continue
        role = role_by_participant.get(ans.participant_id)
        if role is None:
            continue
        value: float | None = None
        if ans.answer_option_id is not None:
            opt = options_by_id.get(ans.answer_option_id)
            if opt is None or opt.is_neutral or opt.weight is None:
                continue
            value = float(opt.weight)
        elif ans.score is not None:
            value = float(ans.score)
        if value is None:
            continue
        key = (ind.competence_id, ind.skill_level_id, role, ind.id)
        raw.setdefault(key, []).append(value)

    def _percent_for_level(
        competence_id: uuid.UUID, skill_level_id: uuid.UUID
    ) -> float | None:
        """Mean role percent for a single (competence, skill_level)."""
        if max_scale_weight <= 0:
            return None
        role_percents: list[float] = []
        roles_with_data = {
            role
            for (cid, sl_id, role, _ind_id) in raw
            if cid == competence_id and sl_id == skill_level_id
        }
        for role in roles_with_data:
            weighted_sum = 0.0
            weight_sum = 0.0
            for (cid, sl_id, role_key, ind_id), values in raw.items():
                if cid != competence_id or sl_id != skill_level_id or role_key != role:
                    continue
                if not values:
                    continue
                ind_avg = sum(values) / len(values)
                ind = indicators_by_id.get(ind_id)
                weight = float(ind.weight) if ind and ind.weight else 1.0
                weighted_sum += ind_avg * weight
                weight_sum += weight
            if weight_sum == 0:
                continue
            role_percents.append(weighted_sum / weight_sum / max_scale_weight * 100.0)
        if not role_percents:
            return None
        return sum(role_percents) / len(role_percents)

    # HRP-170 redo: drop grades the assessment never covered. The
    # questionnaire only carries indicators up to the target grade's
    # skill level — anything above that ceiling has zero data and used
    # to render a misleading bar built only out of the lower levels.
    # Compare the highest indicator sort_index actually answered against
    # each grade's deepest required link.
    answered_sl_ids = {sl_id for (_cid, sl_id, _r, _i) in raw if sl_id is not None}
    answered_sl_sorts = [
        skill_levels_by_id[sl_id].sort_index
        for sl_id in answered_sl_ids
        if sl_id in skill_levels_by_id
    ]
    max_answered_sort: int | None = (
        max(answered_sl_sorts) if answered_sl_sorts else None
    )

    items: list[GradeRecommendationItem] = []
    grade_specs_sorted = sorted(grade_specs, key=lambda gs: gs.sort_index)

    for gs in grade_specs_sorted:
        title = grade_title_by_id.get(gs.grade_id)
        links = links_by_spec.get(gs.id, [])
        if not links:
            items.append(
                GradeRecommendationItem(
                    grade_id=gs.grade_id,
                    grade_title=title,
                    sort_index=gs.sort_index,
                    percent=0.0,
                    passed=False,
                    missing_percent=None,
                    excluded=True,
                )
            )
            continue

        # HRP-170 redo: skip this grade entirely when its deepest
        # required skill level sits above everything the assessment
        # actually answered — the operator told us "must not be
        # displayed" rather than "show as excluded".
        if max_answered_sort is not None:
            link_sl_sorts = [
                skill_levels_by_id[link.skill_level_id].sort_index
                for link in links
                if link.skill_level_id is not None
                and link.skill_level_id in skill_levels_by_id
            ]
            if link_sl_sorts and max(link_sl_sorts) > max_answered_sort:
                continue

        competence_percents: list[float] = []
        for link in links:
            target_sl = (
                skill_levels_by_id.get(link.skill_level_id)
                if link.skill_level_id is not None
                else None
            )
            target_sort = target_sl.sort_index if target_sl is not None else None
            included_level_ids = {
                sl_id
                for (cid, sl_id, _role, _ind_id) in raw
                if cid == link.competence_id
                and sl_id is not None
                and (
                    target_sort is None
                    or (
                        sl_id in skill_levels_by_id
                        and skill_levels_by_id[sl_id].sort_index <= target_sort
                    )
                )
            }
            level_percents: list[float] = []
            for sl_id in included_level_ids:
                pct = _percent_for_level(link.competence_id, sl_id)
                if pct is not None:
                    level_percents.append(pct)
            # HRP-170 spec example: a competence with no usable answers
            # still feeds the grade average as 0% (see "Working with
            # professional software" row in the spec table).
            competence_percents.append(
                sum(level_percents) / len(level_percents) if level_percents else 0.0
            )

        if not competence_percents:
            items.append(
                GradeRecommendationItem(
                    grade_id=gs.grade_id,
                    grade_title=title,
                    sort_index=gs.sort_index,
                    percent=0.0,
                    passed=False,
                    missing_percent=None,
                    excluded=True,
                )
            )
            continue

        grade_percent = round(
            sum(competence_percents) / len(competence_percents), 2
        )
        passed = grade_percent >= assessment.passing_score
        missing = (
            None
            if passed
            else round(float(assessment.passing_score) - grade_percent, 2)
        )
        items.append(
            GradeRecommendationItem(
                grade_id=gs.grade_id,
                grade_title=title,
                sort_index=gs.sort_index,
                percent=grade_percent,
                passed=passed,
                missing_percent=missing,
                excluded=False,
            )
        )

    eligible = [i for i in items if not i.excluded]
    passed_items = [i for i in eligible if i.passed]
    if passed_items:
        rec = max(passed_items, key=lambda x: x.sort_index)
        rec_passed = True
    elif eligible:
        rec = max(eligible, key=lambda x: x.percent)
        rec_passed = False
    else:
        rec = None
        rec_passed = False

    recommendation = AssessmentRecommendation(
        passing_score=assessment.passing_score,
        recommended_grade_id=rec.grade_id if rec else None,
        recommended_grade_title=rec.grade_title if rec else None,
        recommended_grade_passed=rec_passed,
        grades=items,
        computed_at=datetime.now(timezone.utc),
    )

    assessment.recommended_grade_id = rec.grade_id if rec else None
    assessment.recommendation_payload = recommendation.model_dump(mode="json")
    await db.flush()

    return recommendation
