"""HRP-732: HR metrics over a period for the analytics page.

Every metric carries how trustworthy it is, because on this data they are
not equal:

* ``exact``   — read from dated rows nothing rewrites later.
* ``approx``  — reconstructed from mutable current state, or measuring a
  proxy for what was asked. Rendered with a visible "estimate" mark and
  the formula behind it.
* ``no_data`` — the signal does not exist in this workspace. Named out
  loud rather than quietly omitted, so nobody reads a short list as "all
  our numbers are good".

Read-only: no mutating function here, so nothing to register in BILLABLE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentParticipant,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee import issues
from app.modules.employee.models import Employee, EmployeeEvent
from app.modules.talent_market.models import TalentCandidate, TalentCard

EXACT = "exact"
APPROX = "approx"
NO_DATA = "no_data"

# Codes the UI localises. The service never returns user-facing text.
METRIC_CODES = (
    "plans_closed",
    "at_risk",
    "promoted",
    "turnover",
    "time_to_promote",
    "avg_match",
    "engagement",
)


def _change_pct(before: float | None, now: float | None) -> int | None:
    """Relative change, or ``None`` when there is no baseline to divide by."""
    if before is None or now is None or before == 0:
        return None
    return round((now - before) / before * 100)


def _metric(
    code: str,
    kind: str,
    *,
    before: float | None = None,
    now: float | None = None,
    unit: str = "count",
) -> dict:
    return {
        "code": code,
        "kind": kind,
        "before": before,
        "now": now,
        "change_pct": _change_pct(before, now),
        "unit": unit,
    }


def _promotions(
    events: list[EmployeeEvent], grade_rank: dict[str, int]
) -> list[EmployeeEvent]:
    """Position changes that moved the grade up the ladder.

    Reads the ids HRP-732 started recording in the diff; ``grade_rank`` is
    the tenant's grade dictionary keyed the way the JSON stores the id. A
    title-only row written before that, a move to an ungraded position, a
    demotion, or a grade the dictionary no longer knows cannot prove a
    promotion, so none of them is counted — over-reporting promotions is
    worse than admitting the old rows are thin.
    """
    out = []
    for e in events:
        old = (e.old_value or {}).get("grade_id")
        new = (e.new_value or {}).get("grade_id")
        if old not in grade_rank or new not in grade_rank:
            continue
        if grade_rank[new] > grade_rank[old]:
            out.append(e)
    return out


async def hr_metrics(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    visible_employee_ids: set[uuid.UUID] | None,
    *,
    days: int,
    now: datetime | None = None,
) -> dict:
    """Metrics for the last ``days``, against the preceding window of equal length."""
    now = now or datetime.now(UTC)
    start = now - timedelta(days=days)
    prev = now - timedelta(days=days * 2)

    facts = await issues.collect_issue_facts(
        db, tenant_id, visible_employee_ids=visible_employee_ids, now=now
    )
    active = set(facts.active_by_id)
    headcount = len(active)

    metrics: list[dict] = []

    # --- Plans closed. Exact, and free: the plan rows are already loaded.
    def _plans_done(lo: datetime, hi: datetime) -> int:
        return sum(
            1
            for r in facts.pdp_rows
            if r.status == "done"
            and r.finished_at is not None
            and lo <= r.finished_at < hi
            and r.employee_id in active
        )

    metrics.append(
        _metric(
            "plans_closed",
            EXACT,
            before=_plans_done(prev, start),
            now=_plans_done(start, now),
        )
    )

    # --- At risk: a gap nobody has planned for. "Now" is the dashboard's own
    # cohort; "before" replays the same rule against the assessments and plans
    # that existed then — approximate because scores get recalculated and the
    # bar can move without leaving a trace.
    at_risk_now = len(issues.issue_cohorts(facts)["gaps_without_plan"])
    planned_then = {
        r.employee_id
        for r in facts.pdp_rows
        if r.created_at <= start and (r.finished_at is None or r.finished_at > start)
    }
    gapped_then: set[uuid.UUID] = set()
    seen: set[uuid.UUID] = set()
    for row in facts.done_rows:  # newest first
        if row.employee_id in seen or row.employee_id not in active:
            continue
        if row.finished_at is None or row.finished_at >= start:
            continue
        seen.add(row.employee_id)
        bar = issues.passing_bar(row.passing_score)
        if any(
            issues.is_gap(res.percent, bar)
            for res in facts.results_by_assessment.get(row.id, [])
        ):
            gapped_then.add(row.employee_id)
    metrics.append(
        _metric(
            "at_risk", APPROX, before=len(gapped_then - planned_then), now=at_risk_now
        )
    )

    # --- Promotions / turnover / time to promote: the employee event log is
    # the only place a change of role or an exit is dated.
    ev_q = (
        select(EmployeeEvent)
        .join(Employee, Employee.id == EmployeeEvent.employee_id)
        .where(
            Employee.tenant_id == tenant_id,
            EmployeeEvent.event_type.in_(("position_change", "termination")),
        )
    )
    if visible_employee_ids is not None:
        ev_q = ev_q.where(Employee.id.in_(visible_employee_ids))
    events = list((await db.execute(ev_q)).scalars().all())

    if not events:
        # No log at all: say so instead of reporting three confident zeroes.
        metrics.append(_metric("promoted", NO_DATA))
        metrics.append(_metric("turnover", NO_DATA, unit="percent"))
        metrics.append(_metric("time_to_promote", NO_DATA, unit="months"))
    else:
        # Grade ladder: the larger ``sort_index`` is the higher rung — the
        # origin dictionary seeds Junior 0 … Principal 4, the demo Junior 10
        # / Senior 30, and the specialization matrix cascades levels "up"
        # toward the larger index. Origin grades (tenant NULL) sit beside
        # the tenant's own. Equal indexes are a tie, not a promotion.
        grade_rank = {
            str(gid): idx
            for gid, idx in (
                await db.execute(
                    select(DictionaryItem.id, DictionaryItem.sort_index).where(
                        DictionaryItem.type == "grade",
                        (DictionaryItem.tenant_id == tenant_id)
                        | DictionaryItem.tenant_id.is_(None),
                    )
                )
            ).all()
        }
        today = now.date()
        moves = _promotions(
            [e for e in events if e.event_type == "position_change"], grade_rank
        )
        # Closed on today: a move or an exit dated ahead is not a fact yet.
        in_window = [e for e in moves if start.date() <= e.event_date <= today]
        in_prev = [e for e in moves if prev.date() <= e.event_date < start.date()]
        # No ladder at all (neither tenant nor origin grades): nothing can
        # rank a move, so the count is unknown rather than a confident zero.
        metrics.append(
            _metric("promoted", APPROX, before=len(in_prev), now=len(in_window))
            if grade_rank
            else _metric("promoted", NO_DATA)
        )

        exits = [e for e in events if e.event_type == "termination"]

        def _turnover(lo: date, hi: date) -> int | None:
            # Exits dated in [lo, hi] over the people on the books at ``lo``:
            # today's headcount plus everyone who has left since. Dividing
            # both buckets by today's headcount alone made the earlier rate,
            # and the trend between the two, drift with every later exit —
            # and reconstructing the base from today's state is what makes
            # this an estimate rather than a reading.
            on_books = headcount + sum(1 for e in exits if lo <= e.event_date <= today)
            if not on_books:
                return None
            left = sum(1 for e in exits if lo <= e.event_date <= hi)
            return round(left / on_books * 100)

        metrics.append(
            _metric(
                "turnover",
                APPROX,
                before=_turnover(prev.date(), start.date() - timedelta(days=1)),
                now=_turnover(start.date(), today),
                unit="percent",
            )
        )

        # Time to promote: months between one promotion and the next, for
        # the people who have two. One move alone says nothing about pace.
        # A gap belongs to the bucket its later move landed in.
        by_employee: dict[uuid.UUID, list[date]] = {}
        for e in moves:
            by_employee.setdefault(e.employee_id, []).append(e.event_date)
        gaps_now: list[float] = []
        gaps_before: list[float] = []
        for dates in by_employee.values():
            ordered = sorted(dates)
            for a, b in zip(ordered, ordered[1:], strict=False):
                months = (b - a).days / 30.44
                if start.date() <= b <= today:
                    gaps_now.append(months)
                elif prev.date() <= b < start.date():
                    gaps_before.append(months)

        def _mean(xs: list[float]) -> float | None:
            return round(sum(xs) / len(xs), 1) if xs else None

        metrics.append(
            _metric(
                "time_to_promote",
                APPROX if gaps_now or gaps_before else NO_DATA,
                before=_mean(gaps_before),
                now=_mean(gaps_now),
                unit="months",
            )
        )

    # --- Average match on the talent market. Current state only: the score is
    # overwritten on every recount and dropped candidates are deleted, so there
    # is no earlier value to compare against — not lost, never written.
    match_q = (
        select(func.round(func.avg(TalentCandidate.match_score)))
        .join(TalentCard, TalentCard.id == TalentCandidate.card_id)
        .where(
            TalentCard.tenant_id == tenant_id, TalentCandidate.match_score.is_not(None)
        )
    )
    if visible_employee_ids is not None:
        match_q = match_q.where(TalentCandidate.employee_id.in_(visible_employee_ids))
    avg_match = (await db.execute(match_q)).scalar()
    metrics.append(
        _metric(
            "avg_match",
            APPROX,
            now=int(avg_match) if avg_match is not None else None,
            unit="percent",
        )
    )

    # --- Engagement: there is no last-login and no "completed at", so this
    # counts the share of people who answered something in an assessment.
    # A proxy, and labelled as one.
    #
    # The numerator is pinned to the same population as the denominator —
    # active employees inside the read scope, which is exactly what
    # ``facts.active_by_id`` holds. Counting every answerer against a headcount
    # of the active ones let a leaver who answered before going push the share
    # over 100%.
    def _answered(lo: datetime, hi: datetime):
        q = (
            select(func.count(func.distinct(Employee.id)))
            .select_from(AssessmentAnswer)
            .join(
                AssessmentParticipant,
                AssessmentParticipant.id == AssessmentAnswer.participant_id,
            )
            .join(Assessment, Assessment.id == AssessmentParticipant.assessment_id)
            .join(Employee, Employee.user_id == AssessmentParticipant.user_id)
            .where(
                Assessment.tenant_id == tenant_id,
                Employee.tenant_id == tenant_id,
                Employee.status == "active",
                AssessmentAnswer.created_at >= lo,
                AssessmentAnswer.created_at < hi,
            )
        )
        if visible_employee_ids is not None:
            q = q.where(Employee.id.in_(visible_employee_ids))
        return q

    eng_now = (await db.execute(_answered(start, now))).scalar() or 0
    eng_before = (await db.execute(_answered(prev, start))).scalar() or 0
    metrics.append(
        _metric(
            "engagement",
            APPROX,
            before=round(eng_before / headcount * 100) if headcount else None,
            now=round(eng_now / headcount * 100) if headcount else None,
            unit="percent",
        )
    )

    return {"days": days, "metrics": metrics}
