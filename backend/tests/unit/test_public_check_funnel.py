"""HRP-931: the funnel of the public check - the page beacons, the daily
counters, the count over check rows, and the fold of deleted checks into
the counters so history outlives the purge.

The test DB is shared and never rolled back: the counts run over a period
long before anything the suite writes "now", beacons use a source of their
own, and every test deletes what it wrote.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from app.config import settings
from app.modules.public_check import funnel, router, service
from app.modules.public_check.models import (
    PublicCheck,
    PublicCheckEmail,
    PublicCheckEvent,
)
from sqlalchemy import delete, func, select

pytestmark = pytest.mark.asyncio

URL = "/api/public-check/events"
D0, D1 = date(2001, 3, 1), date(2001, 3, 31)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "public_check_enabled", True)
    monkeypatch.setattr(router.limiter, "enabled", False)


def _src() -> str:
    return f"src-{uuid.uuid4().hex[:12]}"


async def _hits(db, source: str) -> dict[tuple[date, str], int]:
    rows = await db.execute(
        select(PublicCheckEvent.day, PublicCheckEvent.event, PublicCheckEvent.hits)
        .where(PublicCheckEvent.source == source)
        .execution_options(populate_existing=True)
    )
    return {(day, event): hits for day, event, hits in rows}


@pytest.fixture
async def written(db):
    """Sources, checks and addresses a test wrote, deleted after it."""
    book: dict[str, list] = {"sources": [], "checks": [], "emails": []}
    try:
        yield book
    finally:
        await db.rollback()
        await db.execute(
            delete(PublicCheckEvent).where(
                PublicCheckEvent.source.in_(book["sources"])
                | (PublicCheckEvent.day < date(2002, 1, 1))
            )
        )
        await db.execute(delete(PublicCheck).where(PublicCheck.id.in_(book["checks"])))
        await db.execute(
            delete(PublicCheckEmail).where(PublicCheckEmail.id.in_(book["emails"]))
        )
        await db.commit()


class TestBeacon:
    async def test_a_beacon_is_204_and_counts_once_today(self, client, db, written):
        source = _src()
        written["sources"].append(source)
        today = datetime.now(UTC).date()
        for _ in range(2):
            resp = await client.post(
                URL, json={"event": "opened", "utm": {"source": source}}
            )
            assert resp.status_code == 204, resp.text
            assert resp.content == b""
        await client.post(URL, json={"event": "started", "utm": {"source": source}})
        assert await _hits(db, source) == {(today, "opened"): 2, (today, "started"): 1}

    async def test_nothing_but_the_counter_is_written(self, client, db, written):
        """No check, no visitor data: a token the page sends is dropped."""
        source = _src()
        written["sources"].append(source)
        checks = select(func.count()).select_from(PublicCheck)
        before = await db.scalar(checks)
        resp = await client.post(
            URL,
            json={
                "event": "shared",
                "utm": {"source": source, "medium": "social"},
                "token": "the-check-link-token",
            },
            headers={"X-Forwarded-For": "203.0.113.31"},
        )
        assert resp.status_code == 204
        rows = (
            (
                await db.execute(
                    select(PublicCheckEvent).where(PublicCheckEvent.source == source)
                )
            )
            .scalars()
            .all()
        )
        assert [(r.event, r.hits) for r in rows] == [("shared", 1)]
        assert {c.name for c in PublicCheckEvent.__table__.columns} == {
            "day",
            "event",
            "source",
            "hits",
        }
        assert await db.scalar(checks) == before

    async def test_the_source_is_normalised(self, client, db, written):
        source = _src()
        long = source + "x" * 100
        written["sources"] += [source, long[: funnel.SOURCE_MAX]]
        for raw in (f"  {source.upper()} ", source, long, long + "y"):
            resp = await client.post(
                URL, json={"event": "opened", "utm": {"source": raw}}
            )
            assert resp.status_code == 204
        today = datetime.now(UTC).date()
        assert await _hits(db, source) == {(today, "opened"): 2}
        assert await _hits(db, long[: funnel.SOURCE_MAX]) == {(today, "opened"): 2}

    @pytest.mark.parametrize("utm", [None, {}, {"source": ""}, {"source": "  "}])
    async def test_no_source_is_direct(self, client, db, utm):
        today = datetime.now(UTC).date()
        before = (await _hits(db, "direct")).get((today, "started"), 0)
        resp = await client.post(URL, json={"event": "started", "utm": utm})
        assert resp.status_code == 204
        assert (await _hits(db, "direct"))[(today, "started")] == before + 1
        # Shared with every other source-less beacon: give the hit back.
        await funnel._bump(db, funnel.Counter({(today, "started", "direct"): -1}))
        await db.commit()

    def test_normalise_source(self):
        assert funnel.normalise_source(" Mail\t") == "mail"
        assert funnel.normalise_source(None) == funnel.normalise_source(" ") == "direct"
        # Cut, then trimmed: a space at the cut is no new spelling.
        assert funnel.normalise_source("a" * 63 + " b") == "a" * 63

    @pytest.mark.parametrize("event", ["result", "email", "moved", "clicked", ""])
    async def test_an_unknown_or_row_counted_step_is_422(self, client, event):
        resp = await client.post(URL, json={"event": event})
        assert resp.status_code == 422

    async def test_over_the_limit_is_still_204_and_not_counted(
        self, client, db, written, monkeypatch
    ):
        source = _src()
        written["sources"].append(source)
        monkeypatch.setattr(router.limiter, "enabled", True)
        monkeypatch.setattr(funnel, "EVENT_RATE_LIMIT", "2/minute")
        router.limiter.reset()
        visitor = {"X-Forwarded-For": "203.0.113.41"}
        try:
            codes = [
                (
                    await client.post(
                        URL,
                        json={"event": "opened", "utm": {"source": source}},
                        headers=visitor,
                    )
                ).status_code
                for _ in range(4)
            ]
            # Another visitor has a budget of their own.
            other = await client.post(
                URL,
                json={"event": "opened", "utm": {"source": source}},
                headers={"X-Forwarded-For": "198.51.100.41"},
            )
        finally:
            router.limiter.reset()
        assert codes == [204, 204, 204, 204]
        assert other.status_code == 204
        today = datetime.now(UTC).date()
        assert await _hits(db, source) == {(today, "opened"): 3}

    async def test_a_flood_of_new_sources_folds_into_other(
        self, client, db, written, monkeypatch
    ):
        """No captcha on a beacon: random sources must not add a row each
        (review of HRP-931). Room for three new ones today, ten sent."""
        today = datetime.now(UTC).date()
        distinct = select(func.count(func.distinct(PublicCheckEvent.source))).where(
            PublicCheckEvent.day == today
        )
        monkeypatch.setattr(funnel, "DAILY_NEW_SOURCES", await db.scalar(distinct) + 3)
        other_before = (await _hits(db, funnel.OTHER)).get((today, "opened"), 0)
        flood = [_src() for _ in range(10)]
        carried = _src()
        written["sources"] += [*flood, carried]
        _check(db, written, day=3, source=carried.upper())  # a check carries it
        await db.commit()

        async def beacon(source):
            resp = await client.post(
                URL, json={"event": "opened", "utm": {"source": source}}
            )
            assert resp.status_code == 204

        try:
            for source in flood:
                await beacon(source)
            await beacon(flood[0])  # counted today already: credited past the cap
            await beacon(carried)  # a check's source: credited past the cap
            credited = {src: await _hits(db, src) for src in [*flood, carried]}
            assert [src for src, hits in credited.items() if hits] == [
                *flood[:3],
                carried,
            ]
            assert credited[flood[0]] == {(today, "opened"): 2}
            # The cap, the check's source and ``other`` - not ten new rows.
            assert await db.scalar(distinct) <= funnel.DAILY_NEW_SOURCES + 2
            other = (await _hits(db, funnel.OTHER))[(today, "opened")]
            assert other == other_before + 7
        finally:
            await db.rollback()
            if other_before:
                await funnel._bump(
                    db, funnel.Counter({(today, "opened", funnel.OTHER): -7})
                )
            else:
                await db.execute(
                    delete(PublicCheckEvent).where(
                        PublicCheckEvent.day == today,
                        PublicCheckEvent.source == funnel.OTHER,
                    )
                )
            await db.commit()

    async def test_a_service_switched_off_has_no_beacon(self, client, monkeypatch):
        monkeypatch.setattr(settings, "public_check_enabled", False)
        resp = await client.post(URL, json={"event": "opened"})
        assert resp.status_code == 404


def _at(day: int) -> datetime:
    return datetime(2001, 3, day, 12, tzinfo=UTC)


async def _address(db, written, *, verified: bool) -> PublicCheckEmail:
    address = PublicCheckEmail(
        id=uuid.uuid4(),
        email=f"funnel-{uuid.uuid4().hex[:10]}@example.com",
        locale="en",
        consent_at=_at(1),
        verified_at=_at(2) if verified else None,
        unsubscribe_token_hash=uuid.uuid4().hex,
        magic_token_hash=service.hash_token("magic-" + uuid.uuid4().hex),
        magic_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(address)
    written["emails"].append(address.id)
    return address


def _check(
    db,
    written,
    *,
    day: int,
    source: str | None,
    status: str = "ready",
    email: PublicCheckEmail | None = None,
    moved: bool = False,
    expires_at: datetime | None = None,
) -> PublicCheck:
    check = PublicCheck(
        id=uuid.uuid4(),
        token_hash=uuid.uuid4().hex,
        status=status,
        description="A funnel fixture.",
        answers={},
        locale="en",
        utm={"source": source} if source is not None else None,
        created_at=_at(day),
        email_id=email.id if email else None,
        moved_at=_at(day) if moved else None,
        expires_at=expires_at,
    )
    db.add(check)
    written["checks"].append(check.id)
    return check


async def _fixture(db, written):
    """March 2001: LinkedIn - three results, an error, two emails of one
    confirmed address (one check confirmed and moved), a beacon day of 10 opened / 8 started / 1 shared;
    a direct result; a result on April 1st, out of the period."""
    confirmed = await _address(db, written, verified=True)
    pending = await _address(db, written, verified=False)
    await db.flush()
    _check(db, written, day=3, source="LinkedIn", email=confirmed, moved=True)
    # Saved to the confirmed address, its own letter not clicked: an email,
    # not a confirmation.
    _check(
        db,
        written,
        day=4,
        source="linkedin ",
        email=confirmed,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    _check(db, written, day=5, source="linkedin")
    _check(db, written, day=5, source="linkedin", status="error")
    _check(db, written, day=6, source=None)
    late = _check(db, written, day=1, source="linkedin")
    late.created_at = datetime(2001, 4, 1, 0, 0, tzinfo=UTC)
    await funnel._bump(
        db,
        funnel.Counter(
            {
                (D0, "opened", "linkedin"): 10,
                (D0, "started", "linkedin"): 8,
                (date(2001, 3, 5), "shared", "linkedin"): 1,
                (date(2001, 3, 6), "opened", "direct"): 4,
                (date(2001, 4, 1), "opened", "linkedin"): 99,
            }
        ),
    )
    await db.commit()
    return confirmed, pending


def _steps(**counts) -> dict[str, int]:
    return {**dict.fromkeys(funnel.STEPS, 0), **counts}


class TestCounts:
    async def test_steps_by_source_from_rows_and_counters(self, db, written):
        await _fixture(db, written)
        assert await funnel.counts(db, D0, D1) == {
            "linkedin": _steps(
                opened=10, started=8, result=3, shared=1, email=2, confirmed=1, moved=1
            ),
            "direct": _steps(opened=4, result=1),
        }

    async def test_the_period_cuts_by_utc_day(self, db, written):
        await _fixture(db, written)
        assert await funnel.counts(db, date(2001, 3, 4), date(2001, 3, 5)) == {
            "linkedin": _steps(result=2, shared=1, email=1)
        }
        april = await funnel.counts(db, date(2001, 4, 1), date(2001, 4, 1))
        assert april == {"linkedin": _steps(opened=99, result=1)}

    async def test_the_purge_keeps_what_the_rows_counted(self, db, written):
        await _fixture(db, written)
        before = await funnel.counts(db, D0, D1)
        expired = datetime.now(UTC) - timedelta(seconds=1)
        for check in (
            await db.scalars(
                select(PublicCheck).where(PublicCheck.id.in_(written["checks"]))
            )
        ).all():
            if check.moved_at is None:  # all but the confirmed, moved one
                check.expires_at = expired
        await db.commit()

        await service.purge_expired(db)

        left = (
            await db.scalars(
                select(PublicCheck.id).where(PublicCheck.id.in_(written["checks"]))
            )
        ).all()
        assert len(left) == 1
        assert await funnel.counts(db, D0, D1) == before
        # A second run folds nothing twice.
        await service.purge_expired(db)
        assert await funnel.counts(db, D0, D1) == before

    async def test_delete_my_data_keeps_the_counts(self, db, written):
        confirmed, _ = await _fixture(db, written)
        before = await funnel.counts(db, D0, D1)
        token = "magic-" + uuid.uuid4().hex
        confirmed.magic_token_hash = service.hash_token(token)
        await db.commit()

        await service.delete_saved(db, token)

        assert await db.get(PublicCheckEmail, confirmed.id) is None
        assert await funnel.counts(db, D0, D1) == before


async def test_a_check_read_names_its_campaign(client, db, written):
    """ "Try again" carries the source into the new check (review of HRP-925)."""
    token = "funnel-" + uuid.uuid4().hex
    check = _check(db, written, day=3, source="newsletter", status="error")
    check.created_at = datetime.now(UTC)
    check.expires_at = datetime.now(UTC) + timedelta(days=1)
    check.token_hash = service.hash_token(token)
    check.utm = {"source": "newsletter", "campaign": "launch"}
    await db.commit()
    resp = await client.get(f"/api/public-check/checks/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["utm"] == {
        "source": "newsletter",
        "medium": None,
        "campaign": "launch",
        "content": None,
        "term": None,
    }
