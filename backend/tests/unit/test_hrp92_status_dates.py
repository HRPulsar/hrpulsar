"""HRP-92 REDO: terminal transitions stamp completed_at / cancelled_at.

The list & detail page swap "Closed at: <date>" for
"Completed: yyyy-mm-dd" or "Cancelled: yyyy-mm-dd" to match the
Assessments section. The label is computed in the UI from the new
status-specific columns; this test pins the backend half of the
contract — Complete writes ``completed_at`` and Cancel writes
``cancelled_at``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate
from app.modules.talent_market.schemas import TalentCardCreate
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def published_card_with_appointed(
    db: AsyncSession, tenant, user
) -> dict:
    """A Published card with one Appointed candidate.

    Complete requires at least one appointed row — we set that up here so
    the test focuses on the date-stamping, not the publish/appoint
    machinery.
    """
    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="T", card_type="vacancy"),
    )

    # Fresh employee + linked user, simpler than reusing the conftest one.
    u = User(
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="C",
        last_name="X",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        tenant_id=tenant.id,
        user_id=u.id,
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.flush()

    cand = TalentCandidate(
        card_id=card["id"],
        employee_id=emp.id,
        status="appointed",
        appointed_at=datetime.now(timezone.utc),
    )
    db.add(cand)
    await db.commit()

    # Force the card into `published` directly — the dedicated publish
    # transition also checks Required-competence rows, which this fixture
    # intentionally skips.
    from app.modules.talent_market.models import TalentCard

    db_card = await db.get(TalentCard, card["id"])
    assert db_card is not None
    db_card.status = "published"
    db_card.is_published = True
    db_card.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_card)
    return {"id": db_card.id}


class TestStatusDates:
    async def test_complete_sets_completed_at(
        self, db: AsyncSession, tenant, published_card_with_appointed
    ) -> None:
        result = await service.complete_card(
            db, tenant.id, published_card_with_appointed["id"]
        )
        assert result["status"] == "completed"
        assert result["completed_at"] is not None
        assert result["cancelled_at"] is None
        # Legacy column stays in sync for backwards-compat clients.
        assert result["closed_at"] is not None

    async def test_cancel_sets_cancelled_at(
        self, db: AsyncSession, tenant, user
    ) -> None:
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="T", card_type="vacancy"),
        )
        result = await service.cancel_card(db, tenant.id, card["id"])
        assert result["status"] == "cancelled"
        assert result["cancelled_at"] is not None
        assert result["completed_at"] is None
        assert result["closed_at"] is not None
