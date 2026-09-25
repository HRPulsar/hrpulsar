"""HRP-776: evidence and confidence per capability - the tentative flag of
a coverage verdict, the outcome of every proposed code (confirmed by a
chip click, by the picker, by accept; removed; added by hand) and the
statistics drawn from those outcomes."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from app.modules.ai import llm_client
from app.modules.primitives.models import Primitive
from app.modules.work import coverage, edits, service
from app.modules.work.models import WorkStep, WorkStepPrimitive
from app.modules.work.schemas import ReclassifyRequest, StepCreate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_coverage_matching import _container, seeded  # noqa: F401

pytestmark = pytest.mark.usefixtures("seeded")


async def _applied(db: AsyncSession, tenant, user, steps: list[dict]):
    """A container whose steps came from an applied session with the given
    payload steps (each: title, primitives, evidence)."""
    c = await _container(db, tenant, user, description="A described process.")
    sess = await service.create_session(db, tenant.id, user.id, c.id)
    sess.status = "ready"
    sess.payload = {"steps": steps}
    await db.commit()
    await service.apply_session(db, tenant.id, sess.id, idempotency_key="k1")
    return c, await service.list_steps(db, tenant.id, c.id)


def _ev(code: str, confidence: float) -> dict:
    return {"code": code, "quote": f"fragment for {code}", "confidence": confidence}


class TestTentative:
    async def test_flag_follows_state_and_confidence(self, db, tenant, user):
        c, steps = await _applied(
            db,
            tenant,
            user,
            [
                {"title": "Sure", "primitives": ["P1"], "evidence": [_ev("P1", 0.95)]},
                {
                    "title": "Unsure",
                    "primitives": ["P1", "P2"],
                    "evidence": [_ev("P1", 0.9), _ev("P2", 0.55)],
                },
            ],
        )
        sure, unsure = steps
        # Not accepted yet: every verdict is preliminary.
        flags = await _flags(db, tenant.id, c.id)
        assert flags == {sure["id"]: True, unsure["id"]: True}

        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        flags = await _flags(db, tenant.id, c.id)
        assert flags[sure["id"]] is False
        assert flags[unsure["id"]] is True  # P2 at 0.55, nobody confirmed

        updated = await service.confirm_step_primitive(
            db, tenant.id, unsure["id"], "P2"
        )
        assert [c["confirmed"] for c in updated["capabilities"]] == [False, True]
        assert updated["state"] == "accepted"  # not a content change
        flags = await _flags(db, tenant.id, c.id)
        assert flags[unsure["id"]] is False

    async def test_hand_made_links_are_never_unsure(self, db, tenant, user):
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Manual", primitive_codes=["P1"])
        )
        # HRP-945: a code the company typed in with the step is its word,
        # confirmed like one saved in the picker (decision T13b).
        assert step["capabilities"] == [
            {"code": "P1", "confidence": None, "quote": None, "confirmed": True}
        ]
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        assert (await _flags(db, tenant.id, c.id)) == {step["id"]: False}

    async def test_confirm_unknown_code_is_404(self, db, tenant, user):
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Manual", primitive_codes=["P1"])
        )
        with pytest.raises(HTTPException) as exc:
            await service.confirm_step_primitive(db, tenant.id, step["id"], "P5")
        assert exc.value.status_code == 404


async def _flags(db, tenant_id, container_id) -> dict[uuid.UUID, bool]:
    result = await coverage.compute(db, tenant_id, container_id)
    return {r["step_id"]: r["tentative"] for r in result["steps"]}


class TestOutcomes:
    async def test_outcomes_and_stats(self, db, tenant, user):
        c, steps = await _applied(
            db,
            tenant,
            user,
            [
                {
                    "title": "Edited",
                    "primitives": ["P1", "P2", "P5"],
                    "evidence": [_ev("P1", 0.9), _ev("P2", 0.6), _ev("P5", 0.7)],
                },
                {
                    "title": "Untouched",
                    "primitives": ["P3"],
                    "evidence": [_ev("P3", 0.8)],
                },
                {"title": "Rejected", "primitives": ["P4"], "evidence": []},
            ],
        )
        edited, untouched, rejected = steps
        # A chip click confirms P1; the picker removes P2 and adds P9 - and
        # confirms what it kept (P1, P5); the third step is deleted.
        await service.confirm_step_primitive(db, tenant.id, edited["id"], "P1")
        await service.set_step_primitives(
            db, tenant.id, edited["id"], ["P1", "P5", "P9"]
        )
        await service.delete_step(db, tenant.id, rejected["id"])
        # The chip's remove button drops one code and vouches for nothing:
        # P3 is put back through the picker (confirmed) and unstamped again.
        removed = await service.remove_step_primitive(
            db, tenant.id, untouched["id"], "P3"
        )
        assert removed["primitive_codes"] == []
        assert removed["state"] == "tenant_edited"
        back = await service.set_step_primitives(db, tenant.id, untouched["id"], ["P3"])
        assert back["capabilities"][0]["confirmed"] is True
        await db.execute(
            WorkStepPrimitive.__table__.update()
            .where(WorkStepPrimitive.step_id == untouched["id"])
            .values(confirmed_at=None)
        )
        await db.commit()

        rows = await edits.outcomes(db, tenant.id)
        by = {(r["step_id"], r["code"]): r for r in rows}
        assert by[(edited["id"], "P1")]["outcome"] == "confirmed"
        assert by[(edited["id"], "P1")]["confidence"] == 0.9
        assert by[(edited["id"], "P2")]["outcome"] == "removed"
        assert by[(edited["id"], "P5")]["outcome"] == "confirmed"
        assert by[(edited["id"], "P9")] == {
            "tenant_id": tenant.id,
            "container_id": c.id,
            "step_id": edited["id"],
            "code": "P9",
            "outcome": "added",
            "confidence": None,
            "reclassified": False,
        }
        assert by[(untouched["id"], "P3")]["outcome"] == "pending"
        assert not any(r["step_id"] == rejected["id"] for r in rows)

        # Accept is not a confirmation: what was pending stays pending, as
        # the coverage flag says.
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        rows = await edits.outcomes(db, tenant.id)
        by = {(r["step_id"], r["code"]): r for r in rows}
        assert by[(untouched["id"], "P3")]["outcome"] == "pending"

        stats = edits.stats(rows)
        assert stats["P1"] == {
            "proposed": 1,
            "kept": 1,
            "confirmed": 1,
            "pending": 0,
            "removed": 0,
            "added": 0,
            "reclassified": 0,
        }
        assert stats["P2"]["removed"] == 1 and stats["P2"]["kept"] == 0
        assert stats["P3"]["pending"] == 1 and stats["P3"]["kept"] == 1
        assert stats["P9"] == {
            "proposed": 0,
            "kept": 0,
            "confirmed": 0,
            "pending": 0,
            "removed": 0,
            "added": 1,
            "reclassified": 0,
        }
        per_container = edits.stats(rows, by="container_id")
        assert per_container[c.id]["proposed"] == 4
        # Another tenant's rows are not in this tenant's view, but are in
        # the platform's.
        assert await edits.outcomes(db, uuid.uuid4()) == []
        assert len(await edits.outcomes(db, None)) >= len(rows)

    async def test_a_reclassified_step_is_counted_apart(self, db, tenant, user):
        """HRP-945: after a reclassification the step's codes are the
        model's second opinion - a code it added is ``model_added``, not the
        company's ``added``, and the statistics keep the whole step out of
        the company's corrections."""
        c, steps = await _applied(
            db,
            tenant,
            user,
            [
                {"title": "Asked again", "primitives": ["P1"], "evidence": []},
                {"title": "Left alone", "primitives": ["P2"], "evidence": []},
            ],
        )
        asked, alone = steps

        def _answer(_prompt, *_a, schema=None, **_k):
            return schema.model_validate(
                {
                    "steps": [
                        {
                            "primitives": ["P1", "P7"],
                            "responsibility": "none",
                            "output_type": "draft",
                            "evidence": [],
                        }
                    ]
                }
            )

        with patch.object(llm_client, "generate_json", side_effect=_answer):
            await service.reclassify_step(
                db, tenant.id, asked["id"], ReclassifyRequest(comment="a supplier talk")
            )
        rows = await edits.outcomes(db, tenant.id)
        by = {(r["step_id"], r["code"]): r for r in rows}
        assert (
            by[(asked["id"], "P1")]["outcome"],
            by[(asked["id"], "P1")]["reclassified"],
        ) == ("pending", True)
        assert (
            by[(asked["id"], "P7")]["outcome"],
            by[(asked["id"], "P7")]["reclassified"],
        ) == ("model_added", True)
        assert by[(alone["id"], "P2")]["reclassified"] is False

        stats = edits.stats(rows)
        assert stats["P7"]["added"] == 0 and stats["P7"]["reclassified"] == 1
        assert stats["P1"]["proposed"] == 0 and stats["P1"]["reclassified"] == 1
        assert stats["P2"]["proposed"] == 1 and stats["P2"]["reclassified"] == 0

    async def test_a_code_from_the_model_marks_a_step_reclassified_before_the_column(
        self, db, tenant, user
    ):
        """Review of HRP-945: a step reclassified before v2work11 has no
        ``reclassified_at``, but a code the model added can only come from a
        reclassification - the whole step is the model's second opinion, and
        every counted proposal still lands in exactly one outcome."""
        _c, steps = await _applied(
            db,
            tenant,
            user,
            [
                {"title": "Asked before", "primitives": ["P1"], "evidence": []},
                {"title": "Kept", "primitives": ["P2", "P3"], "evidence": []},
            ],
        )
        asked, kept = steps

        def _answer(_prompt, *_a, schema=None, **_k):
            return schema.model_validate(
                {
                    "steps": [
                        {
                            "primitives": ["P1", "P7"],
                            "responsibility": "none",
                            "output_type": "draft",
                            "evidence": [],
                        }
                    ]
                }
            )

        with patch.object(llm_client, "generate_json", side_effect=_answer):
            await service.reclassify_step(
                db, tenant.id, asked["id"], ReclassifyRequest(comment="before")
            )
        # As a reclassification made before the column existed looks.
        await db.execute(
            WorkStep.__table__.update()
            .where(WorkStep.id == asked["id"])
            .values(reclassified_at=None)
        )
        await db.commit()

        rows = await edits.outcomes(db, tenant.id)
        by = {(r["step_id"], r["code"]): r for r in rows}
        assert by[(asked["id"], "P1")]["reclassified"] is True
        assert by[(asked["id"], "P7")]["outcome"] == "model_added"
        assert by[(asked["id"], "P7")]["reclassified"] is True
        assert by[(kept["id"], "P2")]["reclassified"] is False

        for row in edits.stats(rows).values():
            assert row["proposed"] == row["confirmed"] + row["pending"] + row["removed"]

    async def test_a_code_retired_after_apply_is_not_a_reclassification(
        self, db, tenant, user
    ):
        """Re-review of HRP-945: a retired code keeps its links, still with
        the model's source; it left the catalog, the model did not add it -
        the step is not reclassified and the code is neither added nor
        model_added."""
        _c, steps = await _applied(
            db,
            tenant,
            user,
            [{"title": "Two codes", "primitives": ["P1", "P2"], "evidence": []}],
        )
        [step] = steps
        retire = Primitive.__table__.update().where(Primitive.code == "P2")
        await db.execute(retire.values(retired_in="v9.9"))
        await db.commit()
        try:
            rows = await edits.outcomes(db, tenant.id)
        finally:
            await db.execute(retire.values(retired_in=None))
            await db.commit()
        mine = [r for r in rows if r["step_id"] == step["id"]]
        assert [(r["code"], r["outcome"], r["reclassified"]) for r in mine] == [
            ("P1", "pending", False)
        ]

    async def test_newest_applied_session_wins(self, db, tenant, user):
        c, _steps = await _applied(
            db, tenant, user, [{"title": "Old", "primitives": ["P1"], "evidence": []}]
        )
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        sess.status = "ready"
        sess.payload = {
            "steps": [{"title": "New", "primitives": ["P2"], "evidence": []}]
        }
        await db.commit()
        await service.apply_session(db, tenant.id, sess.id, idempotency_key="k2")
        rows = await edits.outcomes(db, tenant.id)
        assert [(r["code"], r["outcome"]) for r in rows] == [("P2", "pending")]


class TestRouter:
    async def test_confirm_endpoint_and_role_gate(self, auth_client, db, tenant, user):
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Manual", primitive_codes=["P1"])
        )
        ok = await auth_client.post(
            f"/api/work/steps/{step['id']}/primitives/P1/confirm"
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["capabilities"][0]["confirmed"] is True
        missing = await auth_client.post(
            f"/api/work/steps/{step['id']}/primitives/P5/confirm"
        )
        assert missing.status_code == 404
        gone = await auth_client.delete(f"/api/work/steps/{step['id']}/primitives/P1")
        assert gone.status_code == 200 and gone.json()["primitive_codes"] == []
        assert (
            await auth_client.delete(f"/api/work/steps/{step['id']}/primitives/P1")
        ).status_code == 404

        from tests.unit.test_work_containers import _user_with_role

        await db.refresh(tenant)
        # HRP-810: open to the company, so the manager reads and is refused
        # the write rather than told the step does not exist.
        from app.modules.work.models import WorkContainer
        from sqlalchemy import update

        await db.execute(
            update(WorkContainer)
            .where(WorkContainer.id == step["container_id"])
            .values(visibility="company")
        )
        await db.commit()
        _, manager_token = await _user_with_role(db, tenant, "manager")
        auth_client.headers["Authorization"] = f"Bearer {manager_token}"
        assert (
            await auth_client.post(
                f"/api/work/steps/{step['id']}/primitives/P1/confirm"
            )
        ).status_code == 403
        assert (
            await auth_client.delete(f"/api/work/steps/{step['id']}/primitives/P1")
        ).status_code == 403
