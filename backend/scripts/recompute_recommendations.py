"""HRP-170 — Backfill the Recommended grade chart for legacy assessments.

The chart formula and visibility rules changed (see migration
``hrp170_recompute_recommendations.py``). The migration drops the cached
payload so stale numbers disappear immediately; this script recomputes
the cache for every assessment that is currently eligible:

  * criteria_type ∈ {target_position, current_positions}
  * passing_score IS NOT NULL
  * status ∈ {on_review, done, cancelled-with-results}

Idempotent — re-running is safe. Per-assessment failures are isolated:
one bad assessment (orphaned indicator, missing position) only rolls
back its own transaction and the run carries on.

Usage:
    python -m scripts.recompute_recommendations [--dry-run] [--limit N]

Capture stdout into ``docs/ops/migrations/HRP_170_recompute_<date>.md``
for the audit trail.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone

from app.database import async_session
from app.modules.assessment.models import Assessment, AssessmentStatus
from app.modules.assessment.recommendation import (
    ELIGIBLE_STATUSES,
    compute_grade_recommendation,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def recompute(*, dry_run: bool = False, limit: int | None = None) -> int:
    processed = 0
    skipped = 0
    failed = 0

    async with async_session() as db:
        query = (
            select(Assessment.id, Assessment.tenant_id)
            .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
            .where(
                AssessmentStatus.code.in_(ELIGIBLE_STATUSES),
                Assessment.criteria_type.in_(
                    ("target_position", "current_positions")
                ),
                Assessment.passing_score.is_not(None),
            )
            .order_by(Assessment.created_at)
        )
        if limit is not None:
            query = query.limit(limit)
        rows = await db.execute(query)
        ids: list[tuple[uuid.UUID, uuid.UUID]] = [(r[0], r[1]) for r in rows.all()]

    print(
        f"# HRP-170 recompute — {datetime.now(timezone.utc).isoformat()}"
    )
    print(f"# eligible assessments: {len(ids)}, dry_run={dry_run}")
    print()

    for assessment_id, tenant_id in ids:
        async with async_session() as inner:
            assessment = await inner.get(
                Assessment,
                assessment_id,
                options=[selectinload(Assessment.status)],
            )
            if assessment is None:
                skipped += 1
                continue
            try:
                result = await compute_grade_recommendation(
                    inner, tenant_id, assessment
                )
                if dry_run:
                    await inner.rollback()
                    state = "would-update" if result is not None else "no-change"
                else:
                    await inner.commit()
                    state = "updated" if result is not None else "no-change"
                if result is None:
                    skipped += 1
                else:
                    processed += 1
                print(
                    f"{state} assessment_id={assessment_id} tenant_id={tenant_id}"
                )
            except Exception as exc:  # noqa: BLE001 — log & move on
                await inner.rollback()
                failed += 1
                print(
                    f"failed assessment_id={assessment_id} tenant_id={tenant_id} "
                    f"error={exc!r}"
                )

    print()
    print(f"# processed: {processed}")
    print(f"# skipped (no payload): {skipped}")
    print(f"# failed: {failed}")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    failed = asyncio.run(recompute(dry_run=args.dry_run, limit=args.limit))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
