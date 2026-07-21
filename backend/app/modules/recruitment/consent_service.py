"""Consent service — templates + magic-link request flow + signing.

Extracted from ``service.py`` during the M-5 split (R4d). Audit/billing
hooks target this module; ``service.py`` re-exports via module
``__getattr__`` for legacy callers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.recruitment import audit_service
from app.modules.recruitment.common import _get_candidate, _publish_event
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    ConsentRequest,
    ConsentTemplate,
    Interview,
)
from app.modules.recruitment.schemas import (
    ConsentSendRequest,
    ConsentTemplateCreate,
    ConsentTemplateUpdate,
)


async def list_consent_templates(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict]:
    rows = (
        await db.execute(
            select(ConsentTemplate)
            .where(ConsentTemplate.tenant_id == tenant_id)
            .order_by(ConsentTemplate.created_at.desc())
        )
    ).scalars().all()
    return [_consent_template_to_read(t) for t in rows]


async def create_consent_template(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ConsentTemplateCreate,
) -> dict:
    """Create a consent template; at most one row per tenant is active.

    The partial unique index ``ix_consent_templates_active_unique`` is
    the source of truth — we deactivate first as a courtesy, but if two
    creates race we let the DB throw and surface a 409 instead of a 500.
    """

    from sqlalchemy.exc import IntegrityError

    if data.is_active:
        await _deactivate_consent_templates(db, tenant_id)

    template = ConsentTemplate(
        tenant_id=tenant_id,
        name=data.name,
        body=data.body,
        language=data.language,
        is_active=data.is_active,
        version=1,
    )
    db.add(template)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another active consent template was created concurrently",
        ) from None
    await db.refresh(template)
    return _consent_template_to_read(template)


async def update_consent_template(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    data: ConsentTemplateUpdate,
) -> dict:
    from sqlalchemy.exc import IntegrityError

    template = (
        await db.execute(
            select(ConsentTemplate).where(
                ConsentTemplate.id == template_id,
                ConsentTemplate.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not template:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Consent template not found"
        )

    if data.is_active and not template.is_active:
        await _deactivate_consent_templates(
            db, tenant_id, exclude_id=template_id
        )

    if data.name is not None:
        template.name = data.name
    if data.body is not None:
        template.body = data.body
        template.version = template.version + 1
    if data.language is not None:
        template.language = data.language
    if data.is_active is not None:
        template.is_active = data.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another active consent template was created concurrently",
        ) from None
    await db.refresh(template)
    return _consent_template_to_read(template)


async def _deactivate_consent_templates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
) -> None:
    from sqlalchemy import update as sa_update

    stmt = (
        sa_update(ConsentTemplate)
        .where(
            ConsentTemplate.tenant_id == tenant_id,
            ConsentTemplate.is_active.is_(True),
        )
        .values(is_active=False)
    )
    if exclude_id is not None:
        stmt = stmt.where(ConsentTemplate.id != exclude_id)
    await db.execute(stmt)


def _consent_template_to_read(t: ConsentTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "body": t.body,
        "language": t.language,
        "is_active": t.is_active,
        "version": t.version,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


async def send_consent_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
    data: ConsentSendRequest,
) -> dict:
    """Issue a magic-link consent request and email it to the candidate."""

    import logging
    import secrets
    from datetime import timedelta

    logger = logging.getLogger(__name__)

    candidate = await _get_candidate(db, tenant_id, candidate_id)

    if data.template_id is None:
        template = (
            await db.execute(
                select(ConsentTemplate).where(
                    ConsentTemplate.tenant_id == tenant_id,
                    ConsentTemplate.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
    else:
        template = (
            await db.execute(
                select(ConsentTemplate).where(
                    ConsentTemplate.id == data.template_id,
                    ConsentTemplate.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

    if not template:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No active consent template; create one first",
        )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)

    # Mark previous pending requests for this candidate as superseded so a
    # candidate cannot accidentally sign an old token.
    pending = (
        await db.execute(
            select(ConsentRequest).where(
                ConsentRequest.candidate_id == candidate_id,
                ConsentRequest.tenant_id == tenant_id,
                ConsentRequest.status == "pending",
            )
        )
    ).scalars().all()
    for prev in pending:
        prev.status = "superseded"

    request = ConsentRequest(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        template_id=template.id,
        token=token,
        email=data.email,
        expires_at=expires_at,
        status="pending",
        requested_by=user_id,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_recruitment_consent_email

        person = candidate.person if candidate else None
        candidate_name = (
            f"{person.first_name} {person.last_name}".strip()
            if person
            else "(unnamed)"
        )
        subject, html_body = render_recruitment_consent_email(
            token,
            candidate_name,
            template.body,
            expires_in_days=data.expires_in_days,
        )
        enqueue_email(
            data.email,
            subject,
            html_body,
            tenant_id=str(tenant_id),
            template_code="recruitment.consent_request",
        )
    except Exception:
        logger.exception(
            "Failed to enqueue recruitment consent email for candidate=%s",
            candidate_id,
        )

    return _consent_request_to_read(request)


async def get_consent_by_token(
    db: AsyncSession, token: str
) -> dict:
    """Public endpoint helper — resolve a consent token to its template view."""

    request = await _resolve_consent_request(db, token)
    template = (
        await db.execute(
            select(ConsentTemplate).where(ConsentTemplate.id == request.template_id)
        )
    ).scalar_one_or_none()
    candidate = (
        await db.execute(
            select(Candidate)
            .options(selectinload(Candidate.person))
            .where(Candidate.id == request.candidate_id)
        )
    ).scalar_one_or_none()

    person = candidate.person if candidate else None
    candidate_name = (
        f"{(person.first_name or '').strip()} {(person.last_name or '').strip()}".strip()
        if person
        else ""
    ) or "(unnamed)"

    return {
        "candidate_id": request.candidate_id,
        "candidate_name": candidate_name,
        "template_name": template.name if template else "",
        "template_body": template.body if template else "",
        "template_language": template.language if template else "en",
        "status": request.status,
        "expires_at": request.expires_at,
        "signed_at": request.signed_at,
    }


async def sign_consent(
    db: AsyncSession,
    token: str,
    *,
    signed_ip: str | None = None,
    signed_user_agent: str | None = None,
) -> dict:
    """Public endpoint — mark a token as signed and propagate to interviews.

    Uses ``SELECT … FOR UPDATE`` so two parallel taps on the same magic
    link can't both pass the early-return check, end up with two writes
    racing to set ``signed_at`` and lose the audit metadata of one of
    them.
    """

    request = (
        await db.execute(
            select(ConsentRequest)
            .where(ConsentRequest.token == token)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not request:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Consent link not found"
        )
    if request.status == "signed":
        return {"signed_at": request.signed_at, "status": "signed"}
    if request.status == "expired" or request.expires_at < datetime.now(
        timezone.utc
    ):
        request.status = "expired"
        await db.commit()
        raise HTTPException(
            status.HTTP_410_GONE, "Consent link has expired"
        )

    now = datetime.now(timezone.utc)
    request.status = "signed"
    request.signed_at = now
    request.signed_ip = (signed_ip or "")[:45] or None
    request.signed_user_agent = (signed_user_agent or "")[:500] or None

    # Propagate to all this candidate's existing interviews that have not
    # yet captured a consent timestamp. Future interviews simply read the
    # candidate's most recent signed request via the `_get_…` helpers.
    cv_ids = [
        cv.id
        for cv in (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.candidate_id == request.candidate_id,
                    CandidateVacancy.tenant_id == request.tenant_id,
                )
            )
        ).scalars().all()
    ]
    if cv_ids:
        interviews = (
            await db.execute(
                select(Interview).where(
                    Interview.candidate_vacancy_id.in_(cv_ids),
                    Interview.tenant_id == request.tenant_id,
                    Interview.consent_signed_at.is_(None),
                )
            )
        ).scalars().all()
        for iv in interviews:
            iv.consent_signed_at = now
            iv.consent_template_id = request.template_id

    await db.commit()

    # FR-28: record an audit row for the signing event. The token-based
    # signature has no tenant_id arg so the generic decorator can't reach
    # this function — we resolve the tenant from the consent row instead.
    # user_id is None because the signer is the candidate, not a tenant
    # user; ip/user_agent already live on the consent row itself but
    # mirroring them into payload_diff keeps the audit timeline scannable.
    await audit_service.record_event(
        db,
        tenant_id=request.tenant_id,
        user_id=None,
        action="consent.sign",
        entity_type="consent",
        entity_id=request.id,
        payload_diff={
            "signed_at": now.isoformat(),
            "signed_ip": request.signed_ip,
        },
    )

    candidate_obj = (
        await db.execute(
            select(Candidate)
            .options(selectinload(Candidate.person))
            .where(Candidate.id == request.candidate_id)
        )
    ).scalar_one_or_none()
    candidate_name = None
    if candidate_obj and candidate_obj.person:
        p = candidate_obj.person
        candidate_name = f"{p.first_name} {p.last_name}".strip()
    await _publish_event(
        "recruitment.consent.signed",
        {
            "tenant_id": str(request.tenant_id),
            "consent_request_id": str(request.id),
            "candidate_id": str(request.candidate_id),
            "candidate_name": candidate_name,
            "requested_by": str(request.requested_by) if request.requested_by else None,
            "signed_at": now.isoformat(),
        },
    )

    return {"signed_at": now, "status": "signed"}


async def _resolve_consent_request(
    db: AsyncSession, token: str
) -> ConsentRequest:
    request = (
        await db.execute(
            select(ConsentRequest).where(ConsentRequest.token == token)
        )
    ).scalar_one_or_none()
    if not request:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Consent link not found"
        )
    return request


def _consent_request_to_read(r: ConsentRequest) -> dict:
    return {
        "id": r.id,
        "candidate_id": r.candidate_id,
        "template_id": r.template_id,
        "email": r.email,
        "status": r.status,
        "expires_at": r.expires_at,
        "signed_at": r.signed_at,
        "created_at": r.created_at,
    }


async def get_latest_consent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> dict | None:
    """Return the most recent consent request for the candidate, if any.

    Used by the candidate page to show a consent banner / status badge.
    Returns ``None`` (200) when the candidate has never been sent a
    consent link — the UI handles the empty state explicitly so a 404
    isn't conflated with a missing candidate.
    """

    await _get_candidate(db, tenant_id, candidate_id)
    request = (
        await db.execute(
            select(ConsentRequest)
            .where(
                ConsentRequest.candidate_id == candidate_id,
                ConsentRequest.tenant_id == tenant_id,
            )
            .order_by(ConsentRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not request:
        return None
    return _consent_request_to_read(request)
