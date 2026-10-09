from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.sections import matrix_levels
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User


async def require_company_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """HRP-622: the company profile and the position / specialization
    drill-downs are not for a plain employee - someone holding no role but
    ``employee`` - unless the tenant raised that role to ``manage`` on
    ``company``. The pickers (``SHARED_READS``) stay open to everyone.
    Mirrored by ``canViewCompanyDetails`` in
    frontend/src/hooks/use-permissions.ts."""
    plain = {r.code for r in current_user.roles} <= {"employee"}
    if plain and (await matrix_levels(db, current_user))["company"] != "manage":
        raise AppError("auth_insufficient_permissions", 403)
    return current_user
