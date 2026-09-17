"""HRP-776: evidence and confidence per capability - the tentative flag of
a coverage verdict, the outcome of every proposed code (confirmed by a
chip click, by the picker, by accept; removed; added by hand) and the
statistics drawn from those outcomes."""

from __future__ import annotations

import uuid

import pytest
from app.modules.work import coverage, edits, service
from app.modules.work.models import WorkStepPrimitive
from app.modules.work.schemas import StepCreate
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
        assert step["capabilities"] == [
            {"code": "P1", "confidence": None, "quote": None, "confirmed": False}
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
        }
        per_container = edits.stats(rows, by="container_id")
        assert per_container[c.id]["proposed"] == 4
        # Another tenant's rows are not in this tenant's view, but are in
        # the platform's.
        assert await edits.outcomes(db, uuid.uuid4()) == []
        assert len(await edits.outcomes(db, None)) >= len(rows)

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
