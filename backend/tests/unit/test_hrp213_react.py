"""HRP-213: employee reaction on a Published Talent Market card.

The "React" action is gated to candidate rows whose ``status`` is in
``{matched, not_matched}``. Already-reacted rows are rejected; appointed
candidates can't react. The card-list response surfaces
``reacted_by_me`` so the preview tile can render a chip.
"""

from __future__ import annotations

import pytest
from app.modules.auth.models import Role, User, user_roles
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate
from app.modules.talent_market.schemas import (
    CandidateBulkAdd,
    SearchRequest,
    TalentCardCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import (
    _make_employee,
)


async def _make_card_published(db: AsyncSession, tenant_id, author_id) -> dict:
    card_dict = await service.create_card(
        db,
        tenant_id,
        author_id,
        TalentCardCreate(title="TM-react", card_type="vacancy"),
    )
    from app.modules.talent_market.models import TalentCard

    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None
    card.status = "published"
    await db.commit()
    return card_dict


async def _employee_user(
    db: AsyncSession, tenant_id, emp, *, role_code: str = "employee"
) -> User:
    """Eager-load the user.roles so React's role check has the right shape."""
    role = (
        await db.execute(select(Role).where(Role.code == role_code))
    ).scalar_one_or_none()
    if role is None:
        role = Role(name=role_code.title(), code=role_code, is_system=True)
        db.add(role)
        await db.flush()
    await db.execute(
        user_roles.insert().values(user_id=emp.user_id, role_id=role.id)
    )
    await db.commit()
    from sqlalchemy.orm import selectinload

    return (
        await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == emp.user_id)
        )
    ).scalar_one()


async def test_react_stamps_response_at_and_marks_reacted_by_me(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Reactor")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    out = await service.react_to_card(
        db, tenant.id, card_dict["id"], emp_user
    )
    assert out["response_at"] is not None
    assert out["is_me"] is True

    # Card list surfaces reacted_by_me for the reacting viewer.
    cards, _ = await service.search_cards(
        db,
        tenant.id,
        SearchRequest(),
        viewer_employee_id=emp.id,
    )
    matching = [c for c in cards if c["id"] == card_dict["id"]]
    assert matching and matching[0]["reacted_by_me"] is True


async def test_react_twice_is_rejected(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="DoubleReact")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    await service.react_to_card(db, tenant.id, card_dict["id"], emp_user)
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(
            db, tenant.id, card_dict["id"], emp_user
        )
    assert ex.value.status_code == 409


async def test_react_rejects_non_candidate(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Stranger")
    emp_user = await _employee_user(db, tenant.id, emp)
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(
            db, tenant.id, card_dict["id"], emp_user
        )
    assert ex.value.status_code == 404


async def test_react_rejects_appointed_candidate(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="Appointed")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one()
    row.status = "appointed"
    await db.commit()
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(
            db, tenant.id, card_dict["id"], emp_user
        )
    assert ex.value.status_code == 409


async def test_candidates_ranking_experience_before_reaction(
    db: AsyncSession, tenant, user
) -> None:
    """HRP-213 Task 2 redo: experience is part of "all else being equal".

    Qualifying experience > longer experience > reaction; the reaction
    only breaks ties between rows equal on both percent and experience.
    """
    from datetime import datetime, timezone

    from app.modules.talent_market.common import _card_to_detail
    from app.modules.talent_market.models import TalentCard
    from sqlalchemy.orm import selectinload

    card_dict = await _make_card_published(db, tenant.id, user.id)
    emp_qualifies = await _make_employee(db, tenant.id, name="Qualif")
    emp_longer = await _make_employee(db, tenant.id, name="Longer")
    emp_reacted = await _make_employee(db, tenant.id, name="ZReactor")
    emp_plain = await _make_employee(db, tenant.id, name="ANoexp")
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(
            employee_ids=[
                emp_qualifies.id,
                emp_longer.id,
                emp_reacted.id,
                emp_plain.id,
            ]
        ),
    )
    reacted_row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp_reacted.id,
            )
        )
    ).scalar_one()
    reacted_row.response_at = datetime.now(timezone.utc)
    await db.commit()

    card = (
        await db.execute(
            select(TalentCard)
            .options(
                selectinload(TalentCard.specializations),
                selectinload(TalentCard.competences),
                selectinload(TalentCard.requirements),
                selectinload(TalentCard.candidates),
            )
            .where(TalentCard.id == card_dict["id"])
        )
    ).scalar_one()
    # Equal comp percent everywhere (None); only the experience axis and
    # the reaction differ.
    breakdown = {
        emp_qualifies.id: {"exp_qualifies": True, "exp_months": None},
        emp_longer.id: {"exp_qualifies": False, "exp_months": 14},
        emp_reacted.id: {},
        emp_plain.id: {},
    }
    detail = _card_to_detail(card, breakdown_by_emp=breakdown)
    ordered = [c["employee_id"] for c in detail["candidates"]]
    assert ordered == [
        emp_qualifies.id,  # qualifying experience wins outright
        emp_longer.id,  # longer experience beats the reaction
        emp_reacted.id,  # reaction breaks the tie with the equal row...
        emp_plain.id,  # ...despite the alphabetically earlier name
    ]


async def test_react_rejected_on_unpublished_card(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="Draft", card_type="vacancy"),
    )
    emp = await _make_employee(db, tenant.id, name="Draftee")
    emp_user = await _employee_user(db, tenant.id, emp)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    with pytest.raises(HTTPException) as ex:
        await service.react_to_card(
            db, tenant.id, card_dict["id"], emp_user
        )
    assert ex.value.status_code == 409
