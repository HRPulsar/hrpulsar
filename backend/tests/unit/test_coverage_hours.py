"""The hours arithmetic of the coverage (HRP-858 wave): what a reviewed step
leaves with the person who checks it (HRP-861), and the hours an agent of the
tenant already does, on the process and - through the summary stored on the
container - in the list (HRP-862), and the money as a sum over the steps, each
at its own rate or the tenant's (HRP-868). Pure arithmetic over the breakdown, like
the matching suite whose fixtures it shares."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.modules.work import coverage, service
from app.modules.work.schemas import StepUpdate
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from tests.unit.test_coverage_matching import (  # noqa: F401 - pytest fixtures
    _agent,
    _container,
    _step,
    no_mapping_enqueue,
    seeded,
)

# Every test here reads the catalog and the packs.
pytestmark = pytest.mark.usefixtures("seeded")

# P1 alone is automatable, P1 + P5 is drafted and reviewed, P6 is a judgement.
MOVES, REVIEW, STAYS = ["P1"], ["P1", "P5"], ["P6"]


def _hours(total: float) -> dict[str, float | int]:
    """One run a year, so the yearly hours are the number itself."""
    return {"hours_per_run": total, "runs_per_year": 1}


async def _step_with(db, tenant, container, codes, patch, **attrs):
    """A step, then the fields only a PATCH takes - the way the hours
    editor sets them."""
    step = await _step(db, tenant, container, codes, **attrs)
    return await service.update_step(db, tenant.id, step["id"], StepUpdate(**patch))


class TestReviewShare:
    async def test_a_reviewed_step_frees_what_the_checker_does_not_keep(
        self, db, tenant, user
    ):
        """The process of the feedback thread: 131 h a year, 124 of them in
        review, and only the 3 h of the agent bucket counted as freed."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(3))
        await _step(db, tenant, c, REVIEW, **_hours(124))
        await _step(db, tenant, c, STAYS, **_hours(4))
        # No estimate: in no bucket, so it frees nothing either.
        await _step(db, tenant, c, REVIEW)
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["review_human_share_default"] == 50
        assert result["hours"] == {
            "total": 131.0,
            "moves": 3.0,
            "to_review": 124.0,
            "to_review_after": 62.0,
            "stays": 4.0,
            "freed": 65.0,
            "automated": 0.0,
            "unestimated": 1,
        }
        hours = result["hours"]
        assert hours["freed"] > 3
        assert hours["freed"] == hours["moves"] + (
            hours["to_review"] - hours["to_review_after"]
        )
        # "Before" keeps its meaning: the shares are still of the full hours.
        assert result["shares"]["to_review"] == pytest.approx(124 * 100 / 131)

    async def test_the_share_of_the_step_outranks_the_default(self, db, tenant, user):
        c = await _container(db, tenant, user)
        nothing_left = await _step_with(
            db, tenant, c, REVIEW, {"review_human_share": 0}, **_hours(10)
        )
        all_left = await _step_with(
            db, tenant, c, REVIEW, {"review_human_share": 100}, **_hours(20)
        )
        default = await _step(db, tenant, c, REVIEW, **_hours(40))
        moves = await _step_with(
            db, tenant, c, MOVES, {"review_human_share": 10}, **_hours(8)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["to_review"] == 70
        # 10 x 0 % + 20 x 100 % + 40 x 50 %
        assert result["hours"]["to_review_after"] == 40
        assert result["hours"]["freed"] == 8 + 30
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[nothing_left["id"]]["review_human_share"] == 0
        assert by_id[all_left["id"]]["review_human_share"] == 100
        assert by_id[default["id"]]["review_human_share"] == 50
        # A share stored on a step outside the review bucket means nothing.
        assert by_id[moves["id"]]["review_human_share"] is None

        await service.update_step(
            db, tenant.id, default["id"], StepUpdate(review_human_share=25)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["to_review_after"] == 30
        # Cleared: back to the default.
        await service.update_step(
            db, tenant.id, default["id"], StepUpdate(review_human_share=None)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["to_review_after"] == 40

    async def test_a_full_share_frees_nothing_and_never_less(self, db, tenant, user):
        """A checker who keeps all of it frees nothing. On fractional hours
        the subtraction lands on -1e-16 instead, and the screen read
        "frees up -0 h/year"."""
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        await _step_with(
            db,
            tenant,
            c,
            REVIEW,
            {"review_human_share": 100},
            hours_per_run=0.07,
            runs_per_year=12,
        )
        result = await coverage.compute(db, tenant.id, c.id)
        # ``-0.0 == 0.0``, so the sign is what has to be asserted.
        assert repr(result["hours"]["freed"]) == "0.0"
        assert repr(result["money"]["freed"]) == "0.0"

    async def test_a_review_required_step_is_in_the_bucket_too(self, db, tenant, user):
        c = await _container(db, tenant, user)
        signed = await _step(
            db, tenant, c, MOVES, responsibility="formal", **_hours(12)
        )
        row = next(
            s
            for s in (await coverage.compute(db, tenant.id, c.id))["steps"]
            if s["step_id"] == signed["id"]
        )
        assert row["mode"] == "review_required"
        assert row["review_human_share"] == 50

    async def test_changing_the_share_does_not_reopen_the_breakdown(
        self, db, tenant, user
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, REVIEW, **_hours(10))
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        updated = await service.update_step(
            db, tenant.id, step["id"], StepUpdate(review_human_share=30)
        )
        assert updated["review_human_share"] == 30
        assert updated["state"] == "accepted"
        await db.refresh(c)
        assert c.status == "active"

    async def test_the_route_carries_the_new_figures(
        self, db, tenant, user, auth_client
    ):
        c = await _container(db, tenant, user)
        await _step_with(
            db, tenant, c, REVIEW, {"review_human_share": 20}, **_hours(10)
        )
        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["review_human_share_default"] == 50
        assert body["hours"]["to_review_after"] == 2
        assert body["hours"]["freed"] == 8
        assert body["steps"][0]["review_human_share"] == 20


class TestAlreadyAutomated:
    async def test_counts_the_hours_a_registered_agent_does(self, db, tenant, user):
        """A pack that could take the step is potential; "I already use
        this" registers an agent, and only then are the hours automated."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await _step(db, tenant, c, STAYS, **_hours(96))
        await _step(db, tenant, c, MOVES)  # no estimate: no hours to count
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["total"] == 156
        assert result["hours"]["automated"] == 0

        await _agent(db, tenant, user, "extraction")
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["automated"] == 60
        assert result["hours"]["total"] == 156

    async def test_a_step_the_mode_keeps_with_a_person_is_not_automated(
        self, db, tenant, user
    ):
        """(a) A judgement step is in ``stays`` however well a registered
        agent matches it, so its hours are not automated as well, and (b) the
        card stops reading "120 of 156 already automated" over 44 that stay.
        """
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        judgement = await _step(db, tenant, c, STAYS, **_hours(96))
        # One agent for both steps: the pack of the first, P6 added by hand.
        await _agent(db, tenant, user, "extraction", add=["P6"])
        result = await coverage.compute(db, tenant.id, c.id)
        row = next(s for s in result["steps"] if s["step_id"] == judgement["id"])
        assert row["mode"] == "blocked_judgment"
        assert row["verdict"] == "agent"
        assert row["agent"]["agent_id"] is not None

        hours = result["hours"]
        assert hours["stays"] == 96
        assert hours["automated"] == 60
        assert hours["automated"] + hours["stays"] <= hours["total"]

    async def test_an_assigned_person_outranks_the_agent(self, db, tenant, user):
        # HRP-809: the company named a person, so the verdict is "human" and
        # the agent on the row is only what could take the step.
        from tests.unit.test_coverage_matching import _employee

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, MOVES, **_hours(60))
        await _agent(db, tenant, user, "extraction")
        doer = await _employee(db, tenant)
        await service.update_step(
            db, tenant.id, step["id"], StepUpdate(executor_employee_id=doer.id)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["agent"]["agent_id"] is not None
        assert result["hours"]["automated"] == 0


class TestStoredSummary:
    async def test_the_summary_is_hours_and_shares_only(self, db, tenant, user):
        """One summary is stored for every reader of the list: no money in
        it and nobody's name, whatever the coverage itself carries."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await _step(db, tenant, c, REVIEW, **_hours(40))
        await _step(db, tenant, c, STAYS, **_hours(50))
        await _step(db, tenant, c, STAYS, **_hours(50))
        await _agent(db, tenant, user, "extraction")
        result = await coverage.compute(db, tenant.id, c.id)
        assert coverage.summary_of(result) == {
            "hours": {
                "total": 200.0,
                "moves": 60.0,
                "to_review": 40.0,
                "to_review_after": 20.0,
                "stays": 100.0,
                "freed": 80.0,
                "automated": 60.0,
                "unestimated": 0,
            },
            "shares": {"moves": 30.0, "to_review": 20.0, "stays": 50.0},
            "automated_share": 30.0,
        }

    async def test_no_estimated_hours_means_no_share(self, db, tenant, user):
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES)
        summary = coverage.summary_of(await coverage.compute(db, tenant.id, c.id))
        assert summary["automated_share"] is None
        assert summary["shares"] is None

    async def test_written_on_change_only_and_never_reorders_the_list(
        self, db, tenant, user
    ):
        """The list is ordered by ``updated_at``: a figure recomputed on a
        read is not an edit and must not lift the container to the top."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await db.refresh(c)
        assert c.coverage_summary is None
        touched = c.updated_at

        result = await coverage.compute(db, tenant.id, c.id)
        assert await coverage.remember_summary(db, tenant.id, c.id, result) is True
        await db.refresh(c)
        assert c.coverage_summary["hours"]["automated"] == 0
        assert c.updated_at == touched

        # The same figures again: nothing to write.
        result = await coverage.compute(db, tenant.id, c.id)
        assert await coverage.remember_summary(db, tenant.id, c.id, result) is False

        await _agent(db, tenant, user, "extraction")
        result = await coverage.compute(db, tenant.id, c.id)
        assert await coverage.remember_summary(db, tenant.id, c.id, result) is True
        await db.refresh(c)
        assert c.coverage_summary["hours"]["automated"] == 60.0
        assert c.updated_at == touched

    async def test_a_cache_that_cannot_be_written_is_not_a_failed_read(
        self, db, tenant, user, monkeypatch
    ):
        """The summary is a cache of one list column: a write that fails is
        rolled back and logged, never raised at the reader of the process."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        result = await coverage.compute(db, tenant.id, c.id)

        async def refuse(*args, **kwargs):
            raise OperationalError("UPDATE work_containers", {}, Exception("gone"))

        monkeypatch.setattr(db, "execute", refuse)
        assert await coverage.remember_summary(db, tenant.id, c.id, result) is False

    async def test_a_rolled_back_write_does_not_fail_the_route(
        self, db, tenant, user, auth_client, monkeypatch
    ):
        """A failed write is rolled back, and a rollback expires the reader:
        the route reads the reader's HR scope before it, or the lazy load of
        their roles answers the process page with a 500."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))

        async def rolled_back(session, *args):
            await session.rollback()
            return False

        monkeypatch.setattr(coverage, "remember_summary", rolled_back)
        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.status_code == 200, res.text

    async def test_the_summary_needs_no_people(self, db, tenant, user):
        """The demo seed computes it without the human layer: the hours and
        the shares follow the modes and the agents alone."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await _step(db, tenant, c, STAYS, **_hours(96))
        await _agent(db, tenant, user, "extraction")
        full = await coverage.compute(db, tenant.id, c.id)
        bare = await coverage.compute(db, tenant.id, c.id, people=False)
        assert coverage.summary_of(bare) == coverage.summary_of(full)

    async def test_only_the_coverage_read_writes_it(self, db, tenant, user):
        """``gaps`` runs the same computation - for the To do tab and for the
        hire guard - and must not be a second writer."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await coverage.gaps(db, tenant.id, c.id)
        await coverage.compute(db, tenant.id, c.id)
        await db.refresh(c)
        assert c.coverage_summary is None

    async def test_the_list_percent_follows_the_gate_of_the_page(
        self, db, tenant, user
    ):
        """Under four steps in scope the process page shows no percentages -
        and then the list column shows none either, rather than its own."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await _step(db, tenant, c, STAYS, **_hours(96))
        await _agent(db, tenant, user, "extraction")
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["shares"] is None
        assert result["hours"]["automated"] == 60
        assert coverage.summary_of(result)["automated_share"] is None

    async def test_registering_an_agent_reaches_the_list(
        self, db, tenant, user, auth_client
    ):
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(60))
        await _step(db, tenant, c, STAYS, **_hours(96))
        # Four steps in scope, or the percentages stay off the whole screen.
        await _step(db, tenant, c, STAYS)
        await _step(db, tenant, c, STAYS)

        async def listed():
            res = await auth_client.get("/api/work/containers")
            assert res.status_code == 200, res.text
            return next(i for i in res.json()["items"] if i["id"] == str(c.id))

        # Never computed: the list has nothing to show, and does not compute.
        assert (await listed())["coverage_summary"] is None

        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.json()["hours"]["automated"] == 0
        assert (await listed())["coverage_summary"]["automated_share"] == 0

        await _agent(db, tenant, user, "extraction")
        # Registered, but the list follows the next computation, not the agent.
        assert (await listed())["coverage_summary"]["automated_share"] == 0
        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.json()["hours"]["automated"] == 60
        summary = (await listed())["coverage_summary"]
        assert summary["hours"]["automated"] == 60
        assert summary["automated_share"] == pytest.approx(60 * 100 / 156, abs=0.01)


async def _tenant_rate(db, tenant, rate, currency="EUR"):
    tenant.hourly_rate = None if rate is None else Decimal(rate)
    tenant.hourly_rate_currency = currency
    await db.commit()


class TestStepRate:
    @pytest.mark.parametrize(
        ("own", "of_tenant", "expected"),
        [
            (Decimal("80.00"), Decimal("50.00"), 80.0),
            (None, Decimal("50.00"), 50.0),
            (Decimal("80.00"), None, 80.0),
            (None, None, None),
            # A tenant may price its hour at nothing; that is a rate, not "unset".
            (None, Decimal("0"), 0.0),
        ],
    )
    def test_the_step_then_the_tenant(self, own, of_tenant, expected):
        step = SimpleNamespace(hourly_rate=own)
        assert coverage.step_rate(step, of_tenant) == expected

    def test_a_rate_below_a_cent_is_refused(self):
        """The column is Numeric(10, 2): anything smaller was stored as 0.00,
        priced the step at nothing without counting it among the steps that
        carry no rate, and blocked every save of the editor afterwards."""
        assert StepUpdate(hourly_rate=0.01).hourly_rate == 0.01
        with pytest.raises(ValidationError):
            StepUpdate(hourly_rate=0.004)


class TestMoney:
    async def test_money_is_a_sum_over_the_steps_not_hours_times_one_rate(
        self, db, tenant, user
    ):
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(10))
        await _step_with(db, tenant, c, MOVES, {"hourly_rate": 200}, **_hours(10))
        await _step_with(
            db,
            tenant,
            c,
            REVIEW,
            {"hourly_rate": 100, "review_human_share": 25},
            **_hours(40),
        )
        await _step(db, tenant, c, STAYS, **_hours(20))
        await _step(db, tenant, c, MOVES)  # no estimate: no hours, no money
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["money"] == {
            "total": 7500.0,  # 500 + 2000 + 4000 + 1000
            "moves": 2500.0,
            "to_review": 4000.0,
            "to_review_after": 1000.0,
            "stays": 1000.0,
            "freed": 5500.0,  # 2500 + (4000 - 1000)
            "unpriced": 0,
        }
        # Not what one rate over the total hours would give.
        assert result["money"]["total"] != result["hours"]["total"] * 50
        # The tenant's rate still travels as before.
        assert result["hourly_rate"] == 50.0
        assert result["hourly_rate_currency"] == "EUR"

    async def test_no_rate_anywhere_means_no_money(self, db, tenant, user):
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(10))
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hourly_rate"] is None
        assert result["money"] is None

    async def test_a_step_without_any_rate_is_left_out_and_counted(
        self, db, tenant, user
    ):
        # No tenant rate: only the step that names its own is priced, and the
        # total says how many estimated steps it does not cover.
        c = await _container(db, tenant, user)
        await _step_with(db, tenant, c, MOVES, {"hourly_rate": 100}, **_hours(10))
        await _step(db, tenant, c, MOVES, **_hours(30))
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["money"]["total"] == 1000.0
        assert result["money"]["unpriced"] == 1

    async def test_clearing_the_step_rate_falls_back_to_the_tenant(
        self, db, tenant, user
    ):
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        step = await _step_with(
            db, tenant, c, MOVES, {"hourly_rate": 200}, **_hours(10)
        )
        assert (await coverage.compute(db, tenant.id, c.id))["money"]["total"] == 2000
        await service.update_step(
            db, tenant.id, step["id"], StepUpdate(hourly_rate=None)
        )
        assert (await coverage.compute(db, tenant.id, c.id))["money"]["total"] == 500

    async def test_changing_the_rate_does_not_reopen_the_breakdown(
        self, db, tenant, user
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, MOVES, **_hours(10))
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        updated = await service.update_step(
            db, tenant.id, step["id"], StepUpdate(hourly_rate=120)
        )
        assert updated["hourly_rate"] == 120
        assert updated["state"] == "accepted"
        await db.refresh(c)
        assert c.status == "active"

    async def test_the_stored_summary_carries_no_money(self, db, tenant, user):
        """HRP-862 meets HRP-868: the list summary is one for every reader."""
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(10))
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["money"] is not None
        assert set(coverage.summary_of(result)) == {
            "hours",
            "shares",
            "automated_share",
        }

    async def test_the_route_carries_the_money(self, db, tenant, user, auth_client):
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, MOVES, **_hours(10))
        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.status_code == 200, res.text
        assert res.json()["money"]["freed"] == 500


class TestTheModeOfTheRow:
    """The aggregation reads ``row["mode"]`` and nothing else, so a mode the
    company sets by hand (HRP-863, the neighbouring branch of the wave) moves
    the step's hours and its money together, with no change here."""

    @pytest.mark.parametrize(
        ("mode", "bucket", "hours_freed", "money_freed"),
        [
            ("automatable", "moves", 10.0, 500.0),
            ("review_required", "to_review", 5.0, 250.0),
            ("blocked_judgment", "stays", 0.0, 0.0),
        ],
    )
    async def test_hours_and_money_follow_it(
        self, db, tenant, user, monkeypatch, mode, bucket, hours_freed, money_freed
    ):
        await _tenant_rate(db, tenant, "50")
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, MOVES, **_hours(10))
        # HRP-863 makes ``manual_mode`` outrank the computed mode inside the
        # loop; in this branch the column is stored and not yet read, so the
        # computed mode is forced to the same value here. Whichever of the two
        # decides the row after the merge, the assertions are the same.
        await service.update_step(
            db, tenant.id, step["id"], StepUpdate(manual_mode=mode)
        )
        monkeypatch.setattr(coverage, "automation_mode", lambda *a, **kw: mode)

        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["mode"] == mode
        assert result["hours"]["total"] == 10.0
        assert result["money"]["total"] == 500.0
        assert result["hours"][bucket] == 10.0
        assert result["money"][bucket] == 500.0
        assert result["hours"]["freed"] == hours_freed
        assert result["money"]["freed"] == money_freed
