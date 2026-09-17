"""Read side of the primitive catalog.

The catalog is platform reference data: nothing here mutates it. Seeding
happens in migration ``v2prim01``; retirements and verdict revisions are
migrations too.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.primitives.models import Primitive


async def list_primitives(
    db: AsyncSession, *, include_retired: bool = False
) -> list[Primitive]:
    stmt = select(Primitive).order_by(Primitive.sort_index, Primitive.code)
    if not include_retired:
        stmt = stmt.where(Primitive.retired_in.is_(None))
    return list((await db.execute(stmt)).scalars().all())
