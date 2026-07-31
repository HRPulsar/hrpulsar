"""R4c comparative analytics (SCR-16, SCR-28, SCR-56).

Read-only aggregations over the recruitment data model. The endpoints
power three frontend surfaces:

* Vacancy detail → Analytics tab — stage funnel + win/loss donut
  (:func:`vacancy_analytics`).
* HR/HRD dashboard — cross-vacancy summary
  (:func:`recruitment_summary`).
* Comparison page → radar chart
  (:func:`comparison_radar`).

Every query filters on ``tenant_id`` and the router carries role-based
permission checks; the service layer never trusts an implicit
``current tenant`` context.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from statistics import median

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.recruitment.common import _get_applicable_stages
from app.modules.recruitment.models import (
    AIAssessment,
    CandidateVacancy,
    Vacancy,
)


async def vacancy_analytics(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> dict:
    vacancy = (
        await db.execute(
            select(Vacancy).where(
                Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if vacancy is None:
        raise AppError("vacancy_not_found", status.HTTP_404_NOT_FOUND)

    stages = await _get_applicable_stages(db, tenant_id, vacancy_id)
    cv_rows = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.vacancy_id == vacancy_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalars().all()

    counts: dict[uuid.UUID | None, int] = {}
    medians: dict[uuid.UUID | None, list[float]] = {}
    for cv in cv_rows:
        counts[cv.stage_id] = counts.get(cv.stage_id, 0) + 1
        # status_history rows are dicts; their ``changed_at`` is iso.
        history = cv.status_history or []
        if history:
            # Compute "time spent in destination stage" — the gap between
            # transitions, plus the gap between the last transition and now.
            prev_ts = cv.created_at
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                try:
                    changed_at = datetime.fromisoformat(entry.get("changed_at", ""))
                except (TypeError, ValueError):
                    continue
                from_stage = entry.get("from_stage_id")
                if isinstance(from_stage, str) and prev_ts:
                    from_uuid = _safe_uuid(from_stage)
                    delta = max(0.0, (changed_at - prev_ts).total_seconds())
                    medians.setdefault(from_uuid, []).append(delta)
                prev_ts = changed_at
            # Time spent in the *current* stage so far.
            if prev_ts:
                delta = max(
                    0.0,
                    (datetime.now(timezone.utc) - prev_ts).total_seconds(),
                )
                medians.setdefault(cv.stage_id, []).append(delta)

    funnel = []
    for stage in stages:
        bucket = counts.get(stage.id, 0)
        ms = medians.get(stage.id, [])
        funnel.append(
            {
                "stage_id": stage.id,
                "stage_name": stage.name,
                "candidate_count": bucket,
                "median_seconds_in_stage": median(ms) if ms else None,
            }
        )

    # Win/loss donut — groups by close_resolution / candidate status.
    win_loss = {"hired": 0, "rejected": 0, "withdrew": 0, "in_progress": 0}
    for cv in cv_rows:
        s = (cv.status or "").lower()
        if s == "hired":
            win_loss["hired"] += 1
        elif s == "rejected":
            win_loss["rejected"] += 1
        elif s == "withdrew":
            win_loss["withdrew"] += 1
        else:
            win_loss["in_progress"] += 1

    return {
        "vacancy_id": vacancy_id,
        "funnel": funnel,
        "win_loss": win_loss,
        "total_candidates": len(cv_rows),
    }


def _safe_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


async def recruitment_summary(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Cross-vacancy view for HR/HRD.

    * Top vacancies by velocity — fewest avg days from create → first
      stage transition.
    * Top vacancies by drop-off — highest fraction of rejected/withdrew.
    * AI variance per recruiter — stddev of ``ai_assessments.score`` per
      vacancy owner (proxy for "are evaluations consistent?").
    """

    vacancies = (
        await db.execute(
            select(Vacancy).where(Vacancy.tenant_id == tenant_id)
        )
    ).scalars().all()
    if not vacancies:
        return {
            "top_velocity": [],
            "top_drop_off": [],
            "ai_variance_by_recruiter": [],
        }

    velocity: list[tuple[Vacancy, float]] = []
    drop_off: list[tuple[Vacancy, float]] = []
    now = datetime.now(timezone.utc)

    cv_rows = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    by_vacancy: dict[uuid.UUID, list[CandidateVacancy]] = {}
    for cv in cv_rows:
        by_vacancy.setdefault(cv.vacancy_id, []).append(cv)

    for vac in vacancies:
        cvs = by_vacancy.get(vac.id, [])
        if not cvs:
            continue
        # velocity: avg seconds from CV.created_at to first history entry
        velocities: list[float] = []
        drops = 0
        for cv in cvs:
            history = cv.status_history or []
            if history and isinstance(history[0], dict):
                ts = history[0].get("changed_at")
                if isinstance(ts, str):
                    try:
                        first = datetime.fromisoformat(ts)
                        velocities.append(
                            (first - cv.created_at).total_seconds()
                        )
                    except ValueError:
                        pass
            if (cv.status or "").lower() in {"rejected", "withdrew"}:
                drops += 1
        if velocities:
            velocity.append((vac, sum(velocities) / len(velocities)))
        drop_off.append((vac, drops / len(cvs)))

    velocity.sort(key=lambda x: x[1])
    drop_off.sort(key=lambda x: x[1], reverse=True)

    top_velocity = [
        {"vacancy_id": v.id, "title": v.title, "metric_value": round(val, 2)}
        for v, val in velocity[:5]
    ]
    top_drop_off = [
        {"vacancy_id": v.id, "title": v.title, "metric_value": round(val, 4)}
        for v, val in drop_off[:5]
        if val > 0
    ]

    # Variance of AI scores per recruiter (= vacancy owner). Walk the
    # rows in Python — postgres window/aggregate with two correlated
    # joins fights SQLAlchemy's auto-correlation logic, and the typical
    # tenant has tens, not millions, of recruiters here.
    score_buckets: dict[uuid.UUID, list[float]] = {}
    if cv_rows:
        ai_rows = (
            await db.execute(
                select(AIAssessment.interview_id, AIAssessment.score)
                .where(
                    AIAssessment.tenant_id == tenant_id,
                    AIAssessment.score.is_not(None),
                )
            )
        ).all()
        ai_by_interview: dict[uuid.UUID, list[float]] = {}
        for interview_id, score in ai_rows:
            if score is None:
                continue
            ai_by_interview.setdefault(interview_id, []).append(float(score))

        from app.modules.recruitment.models import Interview

        if ai_by_interview:
            interview_rows = (
                await db.execute(
                    select(Interview.id, Interview.candidate_vacancy_id).where(
                        Interview.tenant_id == tenant_id,
                        Interview.id.in_(list(ai_by_interview.keys())),
                    )
                )
            ).all()
            interview_to_cv: dict[uuid.UUID, uuid.UUID] = {
                row[0]: row[1] for row in interview_rows
            }
            vacancy_to_owner = {vac.id: vac.owner_id for vac in vacancies}
            cv_to_vacancy = {cv.id: cv.vacancy_id for cv in cv_rows}
            for interview_id, scores in ai_by_interview.items():
                cv_id = interview_to_cv.get(interview_id)
                if cv_id is None:
                    continue
                vac_id = cv_to_vacancy.get(cv_id)
                if vac_id is None:
                    continue
                owner = vacancy_to_owner.get(vac_id)
                if owner is None:
                    continue
                score_buckets.setdefault(owner, []).extend(scores)

    ai_variance = []
    for owner, scores in score_buckets.items():
        if len(scores) >= 2:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            stddev = variance ** 0.5
        else:
            stddev = None
        ai_variance.append(
            {
                "recruiter_id": str(owner),
                "sample_size": len(scores),
                "score_stddev": stddev,
            }
        )

    _ = now  # reserved for future stage-bucket variance.
    return {
        "top_velocity": top_velocity,
        "top_drop_off": top_drop_off,
        "ai_variance_by_recruiter": ai_variance,
    }


async def comparison_radar(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    candidate_ids: list[uuid.UUID] | None = None,
) -> dict:
    """Wrap the existing compare_candidates output into radar-friendly rows.

    If ``candidate_ids`` is omitted the radar covers everyone currently
    linked to the vacancy — that's what the dashboard renders by default
    on the vacancy detail page.
    """
    from app.modules.recruitment import service

    if not candidate_ids:
        rows = (
            await db.execute(
                select(CandidateVacancy.candidate_id).where(
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                )
            )
        ).all()
        candidate_ids = [r[0] for r in rows]
    if not candidate_ids:
        return {"vacancy_id": vacancy_id, "candidates": [], "competences": []}

    base = await service.compare_candidates(
        db, tenant_id, vacancy_id, candidate_ids
    )
    competences = base.get("competences", [])
    candidates = []
    for cand in base.get("candidates", []):
        scores = []
        for comp in competences:
            cell = None
            for c in cand.get("cells", []) or []:
                if str(c.get("competence_id")) == str(comp.get("id")):
                    cell = c
                    break
            scores.append(
                {
                    "competence_id": comp.get("id"),
                    "competence_name": comp.get("name"),
                    "score": (cell or {}).get("ai_score")
                    or (cell or {}).get("human_avg"),
                }
            )
        candidates.append(
            {
                "candidate_id": cand.get("candidate_id"),
                "name": cand.get("name"),
                "scores": scores,
            }
        )

    return {
        "vacancy_id": vacancy_id,
        "candidates": candidates,
        "competences": competences,
    }
