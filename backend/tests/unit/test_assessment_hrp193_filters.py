"""HRP-193: ``list_assessments_grouped`` accepts search / type / status
filters and computes ``total`` over the filtered set so the X-Y of N
counter and the paginator stay in sync (previously the filter was
applied client-side, which only re-rendered the rows already on the
current page).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.modules.assessment import service
from app.modules.assessment.schemas import AssessmentCreate
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)


async def _make_assessment(db, tenant, user, employee, **kwargs) -> dict:
    data = AssessmentCreate(
        title=kwargs.get("title", f"hrp193-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"hrp193-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestListAssessmentsGroupedFilters:
    async def test_filter_by_status_returns_only_matching_rows(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Three singles in three different lifecycle states. Filtering
        by status=cancelled keeps only the cancelled one, and the total
        reported back is 1 (not 3)."""
        emp2 = await _make_extra_employee(db, tenant, "fa")
        emp3 = await _make_extra_employee(db, tenant, "fb")

        a_draft = await _make_assessment(db, tenant, user, employee, title="Draft one")
        a_done = await _make_assessment(db, tenant, user, emp2, title="Done one")
        a_cancel = await _make_assessment(db, tenant, user, emp3, title="Cancel one")

        await seed_send_prereqs(db, tenant.id, a_done["id"])
        await service.change_status(db, tenant.id, a_done["id"], "sent")
        await advance_to_in_progress(db, tenant.id, a_done["id"])
        await advance_to_done(db, tenant.id, a_done["id"])

        await service.change_status(db, tenant.id, a_cancel["id"], "cancelled")

        items, total = await service.list_assessments_grouped(
            db, tenant.id, status_codes=["cancelled"]
        )
        assert total == 1
        assert len(items) == 1
        assert items[0]["assessment"]["status_code"] == "cancelled"
        assert items[0]["assessment"]["title"] == "Cancel one"
        # And the unrelated draft is excluded.
        _ = a_draft  # silence unused-warning

    async def test_filter_by_type_excludes_other_types(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "tf")
        _self = await _make_assessment(db, tenant, user, employee, type_code="self")
        _360 = await _make_assessment(db, tenant, user, emp2, type_code="360")

        items, total = await service.list_assessments_grouped(
            db, tenant.id, type_codes=["360"]
        )
        assert total == 1
        assert items[0]["assessment"]["type_code"] == "360"

    async def test_search_matches_title_case_insensitively(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_extra_employee(db, tenant, "sr")
        await _make_assessment(db, tenant, user, employee, title="Quarterly Review")
        await _make_assessment(db, tenant, user, emp2, title="Annual Sync")

        items, total = await service.list_assessments_grouped(db, tenant.id, search="quarterly")
        assert total == 1
        assert items[0]["assessment"]["title"] == "Quarterly Review"

    async def test_filter_total_drives_pagination_not_unfiltered_total(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """With 5 cancelled assessments (and 5 unrelated drafts), filtering
        by cancelled must report total=5 — not 10 — so the paginator's
        "X-Y of N" line and last-page button reflect the filtered slice."""
        # 5 cancelled
        for i in range(5):
            emp = await _make_extra_employee(db, tenant, f"c{i}")
            a = await _make_assessment(db, tenant, user, emp, title=f"Cancel-{i}")
            await service.change_status(db, tenant.id, a["id"], "cancelled")
        # 5 drafts (unrelated)
        for i in range(5):
            emp = await _make_extra_employee(db, tenant, f"d{i}")
            await _make_assessment(db, tenant, user, emp, title=f"Draft-{i}")

        items, total = await service.list_assessments_grouped(
            db, tenant.id, skip=0, limit=3, status_codes=["cancelled"]
        )
        assert total == 5, "Filtered total must reflect only the cancelled rows"
        assert len(items) == 3, "First page returns at most `limit` rows"
        assert all(
            it["assessment"]["status_code"] == "cancelled" for it in items
        )
