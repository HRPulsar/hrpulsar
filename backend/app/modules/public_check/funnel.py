"""The funnel of the public check (HRP-931): opened the input page -> started
typing -> got a result -> shared -> left an email -> confirmed it -> moved
the check into HRPulsar, by ``utm_source`` and by period.

Two sources, never the same step twice:

* the check rows - a ``ready`` check is a result, ``email_id`` an email,
  a saved check without a term a confirmation (the click of its own
  letter), ``moved_at`` a move - by
  the day the check was created;
* daily counters (``PublicCheckEvent``) - the page beacons of the client
  steps, and the row steps of checks that are gone: the purge and a
  visitor's "delete my data" fold a check into the counters in the
  transaction that deletes it (``roll_up``), so history outlives the
  10-day term of an unsaved result.

Nothing about the visitor is kept: no IP, no token, no email - a counter
per UTC day, step and normalised source.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.public_check.models import PublicCheck, PublicCheckEvent

# The funnel in order. The client steps are the only ones a beacon may send
# (``schemas.FunnelEvent``); the rest come from the check rows.
STEPS = ("opened", "started", "result", "shared", "email", "confirmed", "moved")

# Per visitor IP, on the beacon route: a live visitor sends a handful a
# minute; a script inflating the funnel from one address is cut off.
EVENT_RATE_LIMIT = "30/minute"

SOURCE_MAX = 64
DIRECT = "direct"
# Where a beacon's source goes once the day has no room for a new one.
OTHER = "other"
# New sources a day's beacons may open. The beacon has no captcha, so a
# script cycling random ``utm_source`` values would otherwise add a row per
# value and day forever; a source already counted that day, or carried by a
# check, is always credited (``_beacon_source``).
DAILY_NEW_SOURCES = 100

# What a deleted check takes into ``roll_up``: the ``RETURNING`` of the
# delete (``container_id`` is what the deleting caller itself needs).
ROLLUP_COLUMNS = (
    PublicCheck.container_id,
    PublicCheck.created_at,
    PublicCheck.status,
    PublicCheck.utm,
    PublicCheck.email_id,
    PublicCheck.expires_at,
    PublicCheck.moved_at,
)


def normalise_source(value: str | None) -> str:
    """One spelling per source: trimmed, lowercase, cut to ``SOURCE_MAX``;
    none is ``direct``. A stray capital or space in a link must not split
    a source into two rows."""
    return (value or "").strip().lower()[:SOURCE_MAX].strip() or DIRECT


def _row_steps(
    status: str, has_email: bool, confirmed: bool, moved: bool
) -> Iterable[str]:
    """The steps one check row counts for - the only definition of them,
    for the live rows and for the deleted ones alike."""
    for step, reached in (
        ("result", status == "ready"),
        ("email", has_email),
        ("confirmed", confirmed),
        ("moved", moved),
    ):
        if reached:
            yield step


async def _bump(db: AsyncSession, hits: Counter[tuple[date, str, str]]) -> None:
    """Add ``hits`` to the counters, one upsert. Keys sorted: two writers
    lock the rows in the same order."""
    if not hits:
        return
    stmt = insert(PublicCheckEvent).values(
        [
            {"day": day, "event": event, "source": source, "hits": n}
            for (day, event, source), n in sorted(hits.items())
        ]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["day", "event", "source"],
            set_={"hits": PublicCheckEvent.hits + stmt.excluded.hits},
        )
    )


async def _beacon_source(db: AsyncSession, day: date, source: str) -> str:
    """``source`` if the day already counts it, has room for a new one, or a
    check carries it; else ``OTHER``.

    ponytail: the cap is read before the write, so concurrent beacons may
    open a few sources past it - bounded by concurrency, not by a script.
    The check lookup scans ``public_checks`` and runs only for a source the
    full day has not seen; an index on the normalised source if it shows."""
    if source in (DIRECT, OTHER):
        return source
    today = PublicCheckEvent.day == day
    if await db.scalar(
        select(PublicCheckEvent.source)
        .where(today, PublicCheckEvent.source == source)
        .limit(1)
    ):
        return source
    opened = await db.scalar(
        select(func.count(func.distinct(PublicCheckEvent.source))).where(today)
    )
    if (opened or 0) < DAILY_NEW_SOURCES:
        return source
    # The SQL twin of ``normalise_source`` (``btrim`` trims spaces only).
    raw = PublicCheck.utm["source"].astext
    normalised = func.btrim(func.left(func.lower(func.btrim(raw)), SOURCE_MAX))
    if await db.scalar(select(PublicCheck.id).where(normalised == source).limit(1)):
        return source
    return OTHER


async def record_event(db: AsyncSession, event: str, source: str | None) -> None:
    """One page beacon: today's (UTC) counter of ``event`` for ``source``."""
    day = datetime.now(UTC).date()
    source = await _beacon_source(db, day, normalise_source(source))
    await _bump(db, Counter({(day, event, source): 1}))
    await db.commit()


async def roll_up(db: AsyncSession, checks: Iterable[Any]) -> None:
    """Fold checks a caller is deleting into the counters - rows of
    ``ROLLUP_COLUMNS`` from its ``DELETE ... RETURNING``, so a check is
    folded exactly once whoever deletes it. The caller commits."""
    hits: Counter[tuple[date, str, str]] = Counter()
    for c in checks:
        day = c.created_at.astimezone(UTC).date()
        source = normalise_source((c.utm or {}).get("source"))
        for step in _row_steps(
            c.status,
            c.email_id is not None,
            c.email_id is not None and c.expires_at is None,
            c.moved_at is not None,
        ):
            hits[(day, step, source)] += 1
    await _bump(db, hits)


async def counts(
    db: AsyncSession, date_from: date, date_to: date
) -> dict[str, dict[str, int]]:
    """Every step of the funnel per source, over the UTC days
    ``date_from``..``date_to``: ``{source: {step: count}}``, all of
    ``STEPS`` in each."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STEPS, 0))
    start = datetime.combine(date_from, time.min, tzinfo=UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
    # Grouped by the raw source: few groups, normalised and merged here.
    keys = (
        PublicCheck.utm["source"].astext.label("source"),
        PublicCheck.status,
        PublicCheck.email_id.is_not(None).label("has_email"),
        (PublicCheck.email_id.is_not(None) & PublicCheck.expires_at.is_(None)).label(
            "confirmed"
        ),
        PublicCheck.moved_at.is_not(None).label("moved"),
    )
    rows = await db.execute(
        select(*keys, func.count())
        .where(PublicCheck.created_at >= start, PublicCheck.created_at < end)
        .group_by(*keys)
    )
    for source, status, email, verified, gone, n in rows:
        for step in _row_steps(status, email, verified, gone):
            out[normalise_source(source)][step] += n
    kept = await db.execute(
        select(
            PublicCheckEvent.source,
            PublicCheckEvent.event,
            func.sum(PublicCheckEvent.hits),
        )
        .where(PublicCheckEvent.day >= date_from, PublicCheckEvent.day <= date_to)
        .group_by(PublicCheckEvent.source, PublicCheckEvent.event)
    )
    for source, event, n in kept:
        out[source][event] += int(n)
    return dict(out)
