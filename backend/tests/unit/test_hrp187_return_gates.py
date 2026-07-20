"""HRP-187 REDO: returning a plan from review now applies the same
material-completeness contract as Send (Draft → Sent). The QA REDO case 1
showed that adding a bare item during review used to leave Return active
even though the owner would inherit an unactionable card. The deadline gate
stays a backend-only 400 — the UI keeps the button enabled and surfaces the
message in a snackbar (parity with Assessments and Talent market, REDO
case 3).
"""

import pytest
from app.modules.assessment import pdp_service as service
from app.modules.assessment.schemas import (
    PDPCreate,
    PDPItemCreate,
    PDPMaterialCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _plan_in_review(db, tenant, user, employee):
    pdp = await service.create_pdp(
        db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
    )
    item = await service.add_item(
        db, tenant.id, pdp["id"], PDPItemCreate(title="Seed item")
    )
    await service.add_material(
        db,
        tenant.id,
        pdp["id"],
        item["id"],
        PDPMaterialCreate(title="Seed material", link="https://example.com"),
    )
    await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
    await service.change_pdp_status(
        db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
    )
    await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
    return pdp


class TestReturnRequiresMaterials:
    async def test_review_to_returned_blocked_when_item_has_no_material(
        self, db: AsyncSession, tenant, user, employee
    ):
        # Admin adds a fresh item during review; without materials the
        # plan can't be bounced back to the owner — parity with Send.
        pdp = await _plan_in_review(db, tenant, user, employee)
        await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Bare item")
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        assert exc.value.status_code == 409
        assert "material" in exc.value.detail.lower()

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "review"

    async def test_review_to_returned_allowed_when_every_item_has_material(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await _plan_in_review(db, tenant, user, employee)
        extra = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Extra item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            extra["id"],
            PDPMaterialCreate(title="Extra mat", link="https://example.com"),
        )
        result = await service.change_pdp_status(
            db, tenant.id, pdp["id"], "returned"
        )
        assert result["status"] == "returned"
