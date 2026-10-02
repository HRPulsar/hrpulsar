"""HRP-827: who writes the competence catalogue.

``manage`` on the tenant's ``competences`` row authors it - the whole of
it, since no division owns a catalogue row (HRP-631). Deleting from it,
the skill-level ladder and the AI generation of the tree stay the admin
role's as well: they were admin-only before the matrix, so a tenant that
hands ``manage`` to another role hands it the authoring, not those.
"""

import uuid

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.sections import matrix_levels, require_section
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User
from app.modules.competence.models import Competence

manage_competences = require_section("competences", "manage")


async def admin_manages_competences(
    _: User = Depends(manage_competences),
    current_user: User = Depends(require_role("admin")),
) -> User:
    return current_user


async def writes_personal_drafts(db: AsyncSession, current_user: User) -> bool:
    """HRP-632: whether the caller writes personal drafts only.

    ``manage`` authors the catalogue (``False``). Below it a division head -
    the ``manager`` role, at ``view`` - adds a draft of a competence into an
    existing group and edits and deletes their own draft; HR or an admin
    publishes it (Vladimir, Maxim 29.09). Anyone else is refused.
    """
    level = (await matrix_levels(db, current_user))["competences"]
    if level == "manage":
        return False
    if level == "view" and any(r.code == "manager" for r in current_user.roles):
        return True
    raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)


async def hide_anothers_draft(
    db: AsyncSession, current_user: User, competence_id: uuid.UUID
) -> None:
    """HRP-632: someone else's personal draft is not there below ``manage`` -
    the card and every read hanging off it answer the same 404."""
    owner = await db.scalar(
        select(Competence.draft_owner_id).where(Competence.id == competence_id)
    )
    if (
        owner is not None
        and owner != current_user.id
        and (await matrix_levels(db, current_user))["competences"] != "manage"
    ):
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
