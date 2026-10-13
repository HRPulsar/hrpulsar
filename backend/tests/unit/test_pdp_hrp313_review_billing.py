"""HRP-313: the PDP item checkbox autosaves on every tick and untick, so
billing ``mark_item_passed`` charged the employee per click. Toggles are
free now; ``change_pdp_status`` charges the review cycle through the
``billing_hooks`` seam instead — ``pdp.submit_for_review`` on the Submit
for review button, ``pdp.return`` on Return, and the flat ``pdp.update``
for every other transition.

These tests monkeypatch the seam (community no-ops) with recorders, the
same way ``tests/unit/test_assessment_hrp322_submit_billing.py`` does for
the Submit Answers charge.
"""

from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.modules.assessment import pdp_service as service
from app.modules.assessment.schemas import PDPCreate, PDPItemCreate, PDPMaterialCreate
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

PINNED_COST = 7.0  # sentinel: proves the resolved amount is pinned through


def _install_recorders(monkeypatch):
    """Replace the no-op seam with call recorders, the same way
    ``ee.billing.register_billing()`` rebinds it in SaaS."""
    from app.core import billing_hooks

    prechecks: list[tuple[str, float | None]] = []
    consumes: list[tuple[str, float | None]] = []

    async def _resolve(db, tenant_id, action, *, amount_override=None):
        return PINNED_COST

    async def _precheck(db, tenant_id, action, *, amount_override=None):
        prechecks.append((action, amount_override))

    async def _consume(db, tenant_id, user_id, action, *, amount_override=None):
        consumes.append((action, amount_override))

    monkeypatch.setattr(billing_hooks, "resolve_cost", _resolve)
    monkeypatch.setattr(billing_hooks, "precheck_action", _precheck)
    monkeypatch.setattr(billing_hooks, "consume_action", _consume)
    return prechecks, consumes


async def _plan_with_item(db, tenant, user, employee):
    pdp = await service.create_pdp(
        db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
    )
    item = await service.add_item(db, tenant.id, pdp["id"], PDPItemCreate(title="Task"))
    await service.add_material(
        db,
        tenant.id,
        pdp["id"],
        item["id"],
        PDPMaterialCreate(title="Mat", link="https://example.com"),
    )
    return pdp, item


class TestCheckboxTogglesAreFree:
    async def test_tick_and_untick_never_bill(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        pdp, item = await _plan_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        prechecks, consumes = _install_recorders(monkeypatch)
        for is_passed in (True, False, True, False, True):
            await service.mark_item_passed(
                db, tenant.id, pdp["id"], item["id"], user.id, is_passed=is_passed
            )
        assert prechecks == []
        assert consumes == []


class TestReviewCycleBilledOnItsButtons:
    async def test_submit_for_review_charges_once(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        pdp, item = await _plan_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        # First owner tick auto-promotes sent → in_progress, still free.
        await service.mark_item_passed(db, tenant.id, pdp["id"], item["id"], user.id)

        prechecks, consumes = _install_recorders(monkeypatch)
        result = await service.change_pdp_status(
            db, tenant.id, pdp["id"], "review", user_id=user.id
        )
        assert result["status"] == "review"
        assert prechecks == [("pdp.submit_for_review", PINNED_COST)]
        assert consumes == [("pdp.submit_for_review", PINNED_COST)]

    async def test_return_charges_once(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        pdp, _item = await _plan_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")

        prechecks, consumes = _install_recorders(monkeypatch)
        # The item is unchecked, so the HRP-130 return gate lets this pass.
        result = await service.change_pdp_status(
            db, tenant.id, pdp["id"], "returned", user_id=user.id
        )
        assert result["status"] == "returned"
        assert prechecks == [("pdp.return", PINNED_COST)]
        assert consumes == [("pdp.return", PINNED_COST)]

    async def test_other_transitions_still_charge_update(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        pdp, _item = await _plan_with_item(db, tenant, user, employee)

        prechecks, consumes = _install_recorders(monkeypatch)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert prechecks == [("pdp.update", PINNED_COST)]
        assert consumes == [("pdp.update", PINNED_COST)]

    async def test_refused_transition_bills_nothing(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        pdp, _item = await _plan_with_item(db, tenant, user, employee)

        prechecks, consumes = _install_recorders(monkeypatch)
        with pytest.raises(AppError) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        assert exc.value.code == "pdp_invalid_transition"
        assert prechecks == []
        assert consumes == []
