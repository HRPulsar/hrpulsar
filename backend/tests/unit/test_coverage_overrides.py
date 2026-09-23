"""HRP-863: the company's manual override of a step's mode and agent pack.
The override replaces the computed value where that value is born, so the
buckets, the shares, the To do list and the skill gate all follow it."""

from __future__ import annotations

import uuid

import pytest
from app.modules.ai_workforce.models import AIAgentPack
from app.modules.company.models import Tenant
from app.modules.work import coverage, service
from app.modules.work.models import WorkContainer, WorkStep, WorkStepSkill
from app.modules.work.schemas import DecomposedStep, StepUpdate
from fastapi import HTTPException
from sqlalchemy import select, update

from tests.unit.test_coverage_matching import (
    _agent,
    _container,
    _employee,
    _pack_id,
    _row,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded

# Re-exported under the names the tests below ask for: pytest resolves a
# fixture by the name it is bound to in this module.
no_mapping_enqueue = _quiet
seeded = _seeded


def _own_pack(tenant_id) -> AIAgentPack:
    """A tenant's own pack; no primitive codes, so nothing matches it."""
    code = f"own_{uuid.uuid4().hex[:6]}"
    return AIAgentPack(
        code=code, title_en="Own", i18n_key=f"agentPack.{code}", tenant_id=tenant_id
    )


async def _patch(db, tenant, step, **fields):
    return await service.update_step(db, tenant.id, step["id"], StepUpdate(**fields))


class TestManualMode:
    async def test_override_moves_the_step_between_buckets(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        moved = await _step(db, tenant, c, ["P6"], hours_per_run=3, runs_per_year=100)
        for _ in range(3):
            await _step(db, tenant, c, ["P6"], hours_per_run=1, runs_per_year=100)
        row, result = await _row(db, tenant, c, moved["id"])
        assert (row["mode"], row["mode_manual"]) == ("blocked_judgment", False)
        assert result["hours"]["stays"] == 600
        assert result["candidate_step_ids"] == []
        assert result["shares"] is None  # no candidate carries an estimate

        await _patch(db, tenant, moved, manual_mode="automatable")
        row, result = await _row(db, tenant, c, moved["id"])
        assert (row["mode"], row["mode_manual"]) == ("automatable", True)
        # Hours, shares and the candidate list are read off the effective mode.
        assert result["hours"]["moves"] == 300
        assert result["hours"]["stays"] == 300
        assert result["shares"]["moves"] == pytest.approx(50.0)
        assert result["candidate_step_ids"] == [moved["id"]]

    async def test_reset_returns_the_computed_mode(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await _patch(db, tenant, step, manual_mode="blocked_judgment")
        row, _ = await _row(db, tenant, c, step["id"])
        assert (row["mode"], row["mode_manual"]) == ("blocked_judgment", True)
        await _patch(db, tenant, step, manual_mode=None)
        row, _ = await _row(db, tenant, c, step["id"])
        assert (row["mode"], row["mode_manual"]) == ("automatable", False)

    async def test_override_is_not_content(self, db, tenant, user, seeded):
        """Like an assignment, it does not reopen an accepted breakdown."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        patched = await _patch(db, tenant, step, manual_mode="review_required")
        assert patched["state"] == "accepted"
        assert patched["manual_mode"] == "review_required"

    async def test_to_do_follows_the_effective_mode(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        assert [g["kind"] for g in await coverage.gaps(db, tenant.id, c.id)] == [
            "not_automated_yet"
        ]
        # The company keeps the step with people: nothing left to automate.
        await _patch(db, tenant, step, manual_mode="blocked_judgment")
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_needs_accountable_follows_the_effective_mode(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["needs_accountable"] is False
        await _patch(db, tenant, step, manual_mode="draft_then_review")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["needs_accountable"] is True

    async def test_a_step_out_of_scope_ignores_the_override(
        self, db, tenant, user, seeded
    ):
        """No cognitive capability, no bucket: nothing for it to move."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["B2"])
        await _patch(db, tenant, step, manual_mode="automatable")
        row, result = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "out_of_scope"
        assert (row["mode"], row["mode_manual"]) == ("blocked_physical", False)
        assert result["candidate_step_ids"] == []

    async def test_the_skill_gate_follows_the_override(self, db, tenant, user, seeded):
        """The row offers a skill for a candidate step, so the service must
        agree with the row - both ways."""
        c = await _container(db, tenant, user)
        judged = await _step(db, tenant, c, ["P6"])
        plain = await _step(db, tenant, c, ["P1"])
        with pytest.raises(HTTPException) as exc:
            await service.start_step_skill(db, tenant.id, judged["id"], user_id=user.id)
        assert exc.value.code == "work_skill_not_applicable"

        await _patch(db, tenant, judged, manual_mode="draft_then_review")
        row = await service.start_step_skill(
            db, tenant.id, judged["id"], user_id=user.id
        )
        assert row.status == "generating"

        await _patch(db, tenant, plain, manual_mode="blocked_judgment")
        with pytest.raises(HTTPException) as exc:
            await service.start_step_skill(db, tenant.id, plain["id"], user_id=user.id)
        assert exc.value.code == "work_skill_not_applicable"


class TestStoredSummary:
    async def test_an_override_reaches_the_summary_the_list_reads(
        self, db, tenant, user, seeded
    ):
        """HRP-858 (the seam of HRP-862 and HRP-863): the list column is the
        summary the coverage read stores. A mode set by hand moves the
        hours, so the next read has to store the new figures - otherwise the
        list keeps the shares the process had before the override."""
        c = await _container(db, tenant, user)
        moved = await _step(db, tenant, c, ["P6"], hours_per_run=3, runs_per_year=100)

        result = await coverage.compute(db, tenant.id, c.id, schedule_mapping=False)
        assert await coverage.remember_summary(db, tenant.id, c.id, result)
        before = (await db.get(WorkContainer, c.id)).coverage_summary
        assert before["hours"]["stays"] == 300

        await _patch(db, tenant, moved, manual_mode="automatable")
        result = await coverage.compute(db, tenant.id, c.id, schedule_mapping=False)
        assert await coverage.remember_summary(db, tenant.id, c.id, result)
        after = (await db.get(WorkContainer, c.id)).coverage_summary
        assert (after["hours"]["moves"], after["hours"]["stays"]) == (300, 0)

    async def test_every_step_of_the_container_gets_a_row(
        self, db, tenant, user, seeded
    ):
        """``compute`` zips the rows it built with the steps it read, strict:
        a step that produced no row would answer 500 instead of a coverage.
        Mixed on purpose - in scope, out of scope and a boundary step."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P6"], hours_per_run=1, runs_per_year=10)
        await _step(db, tenant, c, ["P1"], hours_per_run=1, runs_per_year=10)
        await _step(db, tenant, c, ["B2"])  # boundary: out of scope
        await _step(db, tenant, c, [], responsibility="regulatory")

        result = await coverage.compute(db, tenant.id, c.id, schedule_mapping=False)
        steps = (
            (
                await db.execute(
                    select(WorkStep).where(WorkStep.container_id == c.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(result["steps"]) == len(steps)


class TestManualPack:
    async def test_the_named_pack_reads_as_the_match(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        # P5+P9 spans two packs: a gap until the company names one.
        step = await _step(db, tenant, c, ["P5", "P9"])
        row, _ = await _row(db, tenant, c, step["id"])
        assert (row["verdict"], row["agent"]) == ("gap", None)

        await _patch(db, tenant, step, manual_pack_code="drafting")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "agent"
        assert row["gap_label"] is None
        assert row["agent"] == {
            "pack_id": await _pack_id(db, "drafting"),
            "pack_code": "drafting",
            "pack_manual": True,
            "agent_id": None,
            "agent_name": None,
        }
        # Covered by a pack, not automated yet: it changed To do sections.
        gaps = await coverage.gaps(db, tenant.id, c.id)
        assert [(g["kind"], g["agent"]["pack_code"]) for g in gaps] == [
            ("not_automated_yet", "drafting")
        ]

    async def test_the_tenants_agent_of_the_named_pack_is_named(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        other = await _agent(db, tenant, user, "extraction", name="Matcher")
        mine = await _agent(db, tenant, user, "drafting", name="Writer")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["agent"]["agent_id"] == other["id"]
        assert row["agent"]["pack_manual"] is False

        await _patch(db, tenant, step, manual_pack_code="drafting")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["agent"]["agent_id"] == mine["id"]
        assert row["agent"]["agent_name"] == "Writer"
        assert row["agent"]["pack_manual"] is True

        await _patch(db, tenant, step, manual_pack_code=None)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["agent"]["agent_id"] == other["id"]
        assert row["agent"]["pack_manual"] is False

    async def test_a_blocked_step_keeps_the_named_pack_out_of_the_match(
        self, db, tenant, user, seeded
    ):
        """An agent produces nothing in a blocked mode, so naming a pack
        there must not empty the step out of To do while its hours stay
        with people - it would be covered by nobody."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"], hours_per_run=2, runs_per_year=100)
        await _patch(db, tenant, step, manual_pack_code="drafting")
        row, result = await _row(db, tenant, c, step["id"])
        assert (row["mode"], row["verdict"], row["agent"]) == (
            "blocked_judgment",
            "gap",
            None,
        )
        assert result["hours"]["stays"] == 200
        assert [g["kind"] for g in await coverage.gaps(db, tenant.id, c.id)] == [
            "no_owner"
        ]

        # The mode makes the step a candidate: now the pack is its match.
        await _patch(db, tenant, step, manual_mode="draft_then_review")
        row, result = await _row(db, tenant, c, step["id"])
        assert row["agent"]["pack_code"] == "drafting"
        assert result["hours"]["to_review"] == 200
        assert [g["kind"] for g in await coverage.gaps(db, tenant.id, c.id)] == [
            "not_automated_yet"
        ]

    async def test_a_named_executor_still_outranks_the_agent(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        emp = await _employee(db, tenant)
        await _patch(
            db,
            tenant,
            step,
            manual_pack_code="drafting",
            executor_employee_id=emp.id,
        )
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["label"] == "assigned"
        assert row["agent"]["pack_code"] == "drafting"  # what could take it

    async def test_a_vanished_pack_is_ignored(self, db, tenant, user, seeded):
        own = _own_pack(tenant.id)
        db.add(own)
        await db.commit()
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await _patch(db, tenant, step, manual_pack_code=own.code)
        row, _ = await _row(db, tenant, c, step["id"])
        assert (row["agent"]["pack_code"], row["agent"]["pack_manual"]) == (
            own.code,
            True,
        )

        await db.execute(
            update(AIAgentPack).where(AIAgentPack.id == own.id).values(is_active=False)
        )
        await db.commit()
        # The step keeps the company's word; coverage reads as without it.
        row, _ = await _row(db, tenant, c, step["id"])
        assert (row["agent"]["pack_code"], row["agent"]["pack_manual"]) == (
            "extraction",
            False,
        )
        assert await coverage.gaps(db, tenant.id, c.id)  # and nothing raises

    async def test_patch_refuses_a_pack_the_tenant_cannot_see(
        self, db, tenant, user, seeded
    ):
        stranger = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(stranger)
        await db.flush()
        theirs = _own_pack(stranger.id)
        db.add(theirs)
        await db.commit()
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        for code in ("no_such_pack", theirs.code, ""):
            with pytest.raises(HTTPException) as exc:
                await _patch(db, tenant, step, manual_pack_code=code)
            assert exc.value.status_code == 422
            assert exc.value.code == "work_step_pack_invalid"
        stored = await db.scalar(
            select(WorkStep.manual_pack_code).where(WorkStep.id == step["id"])
        )
        assert stored is None

    async def test_a_skill_of_another_pack_is_not_ready_for_the_named_one(
        self, db, tenant, user, seeded
    ):
        """The file was written for the pack the step had before: under the
        named pack the step is not automated yet, and naming the old pack
        back makes the same file ready again."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        db.add(
            WorkStepSkill(
                tenant_id=tenant.id,
                step_id=step["id"],
                catalog_version=service.CATALOG_VERSION,
                pack_id=await _pack_id(db, "extraction"),
                status="ready",
                content="# skill",
            )
        )
        await db.commit()
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["skill_status"] == "ready"

        await _patch(db, tenant, step, manual_pack_code="drafting")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["skill_status"] == "none"
        gaps = await coverage.gaps(db, tenant.id, c.id)
        assert [g["kind"] for g in gaps] == ["not_automated_yet"]

        await _patch(db, tenant, step, manual_pack_code="extraction")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["skill_status"] == "ready"

    async def test_the_skill_is_written_for_the_named_pack(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await _patch(db, tenant, step, manual_pack_code="drafting")
        row = await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        assert row.pack_id == await _pack_id(db, "drafting")


class TestApply:
    def test_the_draft_schema_carries_no_override(self):
        """``apply_session`` copies every ``STEP_FIELDS`` key the draft has,
        unfiltered, so what keeps an override out of a new step is that the
        worker's schema has no field to put one in. Adding one there needs a
        filter at the apply."""
        assert not {"manual_mode", "manual_pack_code"} & set(
            DecomposedStep.model_fields
        )

    async def test_apply_leaves_no_override_behind(self, db, tenant, user, seeded):
        """A new breakdown replaces every step: the overrides go with the
        rows they sat on, and coverage of the new steps is computed."""
        c = await _container(db, tenant, user, description="Close the month.")
        old = await _step(db, tenant, c, ["P6"])
        await _patch(
            db, tenant, old, manual_mode="automatable", manual_pack_code="drafting"
        )
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        sess.status = "ready"
        sess.payload = {
            "steps": [
                # As the worker writes it: the draft schemas have no override
                # field, so a new step can only start without one.
                {"title": "Judge", "primitives": ["P6"]},
                {"title": "Extract", "primitives": ["P1"]},
            ]
        }
        await db.commit()
        await service.apply_session(
            db, tenant.id, sess.id, idempotency_key="k1", force=True
        )

        steps = (
            (await db.execute(select(WorkStep).where(WorkStep.container_id == c.id)))
            .scalars()
            .all()
        )
        assert old["id"] not in {s.id for s in steps}
        assert [(s.manual_mode, s.manual_pack_code) for s in steps] == [
            (None, None)
        ] * 2
        result = await coverage.compute(db, tenant.id, c.id)
        by_title = {s["title"]: s for s in result["steps"]}
        assert by_title["Judge"]["mode"] == "blocked_judgment"
        assert by_title["Judge"]["mode_manual"] is False
        assert by_title["Extract"]["agent"]["pack_manual"] is False
