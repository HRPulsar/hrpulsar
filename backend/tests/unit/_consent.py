"""HRP-979: AI processing of a candidate needs their signed consent.

Test setups that exercise analysis, question generation, transcripts or
uploads sign it here, the same way demo candidates are consented.
"""

from __future__ import annotations

import uuid

from app.modules.recruitment.consent_service import _record_signed_consent
from app.modules.recruitment.models import Candidate
from sqlalchemy.ext.asyncio import AsyncSession


async def sign_consent(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID | str
) -> None:
    candidate = await db.get(Candidate, uuid.UUID(str(candidate_id)))
    assert candidate is not None
    await _record_signed_consent(db, tenant_id, candidate)
    await db.commit()
