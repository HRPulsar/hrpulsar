"""In-product feedback endpoint (HRP-586, HRP-587)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.feedback.schemas import FeedbackCreate
from app.modules.feedback.service import submit_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def create_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Accept a rating / comment from the signed-in user."""
    await submit_feedback(db, current_user, payload)
