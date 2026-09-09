"""Whose talent card is it (HRP-639).

The board is company-wide by design — a published card is an internal job
ad and everyone is meant to read it. Authoring one is not: eighteen
mutating routes stood on ``require_role("admin", "manager")`` alone, so a
division head could publish, re-scope, close and staff a neighbouring
department's card, and could read every department's drafts besides.

Same shape as ``recruitment.scope`` (HRP-629), because a talent card
carries the same two axes as a vacancy — ``division_id`` and
``author_id``:

* ``admin`` / ``hr`` / ``platform_admin`` keep the whole workspace;
* everyone else may write a card that sits in a division they manage, or
  that they created themselves.

Authorship is in the condition for the same reason it is in hiring: a
card can be created without a division and would otherwise belong to
nobody. It is safe here only because ``assert_division_in_scope`` fences
``division_id`` on the way in — without that, "I created it" would be a
way to author a card into somebody else's department and keep editing it.

Reading is wider than writing: the write condition, plus every published
card, plus the cards the viewer is a candidate on. That is the rule the
employee-only path already followed; managers had no rule at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import Depends, status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    ADMIN_ROLE_CODES,
    get_current_employee,
    get_managed_division_ids,
)
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.talent_market.models import TalentCandidate, TalentCard


@dataclass(frozen=True)
class TalentScope:
    """Resolved answer to "which cards may this caller touch"."""

    unrestricted: bool
    division_ids: tuple[uuid.UUID, ...]
    user_id: uuid.UUID
    employee_id: uuid.UUID | None

    def card_filter(self) -> ColumnElement[bool]:
        """Write condition on ``TalentCard``; only valid when restricted.

        A condition rather than a set of ids: every caller narrows a query
        that already selects from ``TalentCard``.
        """
        clauses: list[ColumnElement[bool]] = [TalentCard.author_id == self.user_id]
        if self.division_ids:
            clauses.append(TalentCard.division_id.in_(self.division_ids))
        return or_(*clauses)

    def writable(self, card: TalentCard) -> bool:
        """``card_filter`` for a card already in hand — feeds the
        ``can_manage`` flag the UI gates its buttons on, so a button that
        would 403 is never rendered (HRP-622's rule)."""
        if self.unrestricted or card.author_id == self.user_id:
            return True
        return card.division_id is not None and card.division_id in self.division_ids

    def readable(self, card: TalentCard) -> bool:
        """``read_filter`` for a card already in hand.

        Kept next to the SQL twin above so the two cannot drift: the list
        route narrows a query, the detail route holds one row with its
        candidates eager-loaded and has nothing to narrow.
        """
        if self.unrestricted or card.is_published:
            return True
        if card.author_id == self.user_id:
            return True
        if card.division_id is not None and card.division_id in self.division_ids:
            return True
        return self.employee_id is not None and any(
            ca.employee_id == self.employee_id for ca in card.candidates
        )

    def read_filter(self) -> ColumnElement[bool]:
        """Write condition widened by the board itself."""
        clauses = [self.card_filter(), TalentCard.is_published.is_(True)]
        if self.employee_id is not None:
            clauses.append(
                TalentCard.id.in_(
                    select(TalentCandidate.card_id).where(
                        TalentCandidate.employee_id == self.employee_id
                    )
                )
            )
        return or_(*clauses)


def employee_read_filter(employee_id: uuid.UUID | None) -> ColumnElement[bool]:
    """HRP-765: which cards a rank-and-file employee may read.

    Narrower than :meth:`TalentScope.read_filter` — the board is not a
    catalogue for the people on it. An employee sees a card when

    (a) they are on its candidate list and the card has left Draft, or
    (b) they are on its candidate list as ``appointed`` — a pre-publish
        nomination, so the card's own status does not matter.

    One condition rather than two hand-written checks: the list narrows a
    query with it and the detail route re-asks the same question about one
    row, so the two cannot drift (they did — the list let a role-employee
    user with no Employee row read every published card, the detail route
    refused them).
    """
    if employee_id is None:
        return sa.false()
    return TalentCard.id.in_(
        select(TalentCandidate.card_id)
        .join(TalentCard, TalentCard.id == TalentCandidate.card_id)
        .where(
            TalentCandidate.employee_id == employee_id,
            or_(
                TalentCard.status != "draft",
                TalentCandidate.status == "appointed",
            ),
        )
        .scalar_subquery()
    )


async def assert_employee_card_visible(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    employee_id: uuid.UUID | None,
) -> None:
    """404 unless :func:`employee_read_filter` lets this employee read the card.

    Every employee-reachable read of one card asks through here — the
    detail route and the match breakdown behind it. The breakdown used to
    check only "is this row mine", so an employee could hand it their own
    id with any card id and read the requirements, levels, specializations
    and threshold of a draft they were never on.

    "Not found" rather than 403, the way this module has always hidden a
    card: the answer must not confirm that somebody else's draft exists.
    """
    allowed = await db.scalar(
        select(TalentCard.id).where(
            TalentCard.id == card_id,
            TalentCard.tenant_id == tenant_id,
            employee_read_filter(employee_id),
        )
    )
    if allowed is None:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)


async def resolve_talent_scope(db: AsyncSession, current_user: User) -> TalentScope:
    # ``employee_id`` is resolved even for unrestricted callers: the search
    # route reads it for the per-card "Reacted" chip (HRP-213), and admins
    # are often employees too.
    emp = await get_current_employee(db, current_user)
    employee_id = emp.id if emp is not None else None
    if any(r.code in ADMIN_ROLE_CODES for r in current_user.roles):
        return TalentScope(
            unrestricted=True,
            division_ids=(),
            user_id=current_user.id,
            employee_id=employee_id,
        )
    division_ids: tuple[uuid.UUID, ...] = ()
    if emp is not None:
        division_ids = tuple(
            await get_managed_division_ids(db, current_user.tenant_id, emp.id)
        )
    return TalentScope(
        unrestricted=False,
        division_ids=division_ids,
        user_id=current_user.id,
        employee_id=employee_id,
    )


def _refuse() -> None:
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


def assert_division_in_scope(
    scope: TalentScope, division_id: uuid.UUID | None
) -> None:
    """403 unless the caller may file a card under this division.

    ``None`` passes: a card with no division belongs to its author, and
    the author arm of ``card_filter`` is what keeps hold of it.

    Takes the resolved scope rather than resolving its own: the routes
    that call it already carry ``talent_scope``, and resolving twice
    walks the tenant's whole division tree twice.
    """
    if division_id is None or scope.unrestricted:
        return
    if division_id in scope.division_ids:
        return
    _refuse()


async def talent_scope(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TalentScope:
    """Shared so a request resolves the division tree once."""
    return await resolve_talent_scope(db, current_user)


async def card_scope(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TalentScope = Depends(talent_scope),
) -> None:
    """403 unless the caller may write this card.

    A card that does not exist is refused rather than reported missing —
    the rule HRP-629 already applies to hiring.
    """
    if scope.unrestricted:
        return
    found = (
        await db.execute(
            select(TalentCard.id)
            .where(
                TalentCard.id == card_id,
                TalentCard.tenant_id == current_user.tenant_id,
                scope.card_filter(),
            )
            .limit(1)
        )
    ).first()
    if found is None:
        _refuse()
