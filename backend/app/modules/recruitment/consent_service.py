"""Consent service — templates + magic-link request flow + signing.

Extracted from ``service.py`` during the M-5 split (R4d). Audit/billing
hooks target this module; ``service.py`` re-exports via module
``__getattr__`` for legacy callers.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core import billing_hooks
from app.core.errors import AppError
from app.modules.recruitment import audit_service
from app.modules.recruitment.common import (
    _get_candidate,
    _publish_event,
    candidate_display_name,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
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


async def list_consent_templates(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(ConsentTemplate)
                .where(ConsentTemplate.tenant_id == tenant_id)
                .order_by(ConsentTemplate.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
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
        raise AppError(
            "consent_template_created_concurrently",
            status.HTTP_409_CONFLICT,
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
        raise AppError("consent_template_not_found", status.HTTP_404_NOT_FOUND)

    if data.is_active and not template.is_active:
        await _deactivate_consent_templates(db, tenant_id, exclude_id=template_id)

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
        raise AppError(
            "consent_template_created_concurrently",
            status.HTTP_409_CONFLICT,
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
        raise AppError(
            "no_active_consent_template",
            status.HTTP_409_CONFLICT,
        )

    # Mark previous pending requests for this candidate as superseded so a
    # candidate cannot accidentally sign an old token.
    pending = (
        (
            await db.execute(
                select(ConsentRequest).where(
                    ConsentRequest.candidate_id == candidate_id,
                    ConsentRequest.tenant_id == tenant_id,
                    ConsentRequest.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for prev in pending:
        prev.status = "superseded"

    request = _issue_consent_request(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        template=template,
        email=data.email,
        expires_in_days=data.expires_in_days,
        user_id=user_id,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    await _deliver_consent_email(
        db,
        tenant_id,
        candidate=candidate,
        template=template,
        request=request,
        expires_in_days=data.expires_in_days,
        logger=logger,
    )

    return _consent_request_to_read(request)


def _issue_consent_request(
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    template: ConsentTemplate,
    email: str,
    expires_in_days: int,
    user_id: uuid.UUID,
) -> ConsentRequest:
    """A fresh pending request with its own token.

    Shared by the first send and by HRP-684's reissue of an expired link,
    so both mint the token and the lifetime the same way.
    """
    now = datetime.now(timezone.utc)
    return ConsentRequest(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        template_id=template.id,
        token=secrets.token_urlsafe(32),
        email=email,
        expires_at=now + timedelta(days=expires_in_days),
        status="pending",
        requested_by=user_id,
        last_sent_at=now,
    )


def _utc(value: datetime) -> datetime:
    """Postgres may hand a timestamp back naive; compare everything in UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _deliver_consent_email(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    candidate: Candidate,
    template: ConsentTemplate,
    request: ConsentRequest,
    expires_in_days: int,
    logger,
) -> None:
    """Render and enqueue the candidate-facing consent email.

    Shared by the first send and by HRP-684's resend so both put the same
    letter in the mailbox. Failures are logged, never raised: the request
    row is already committed and a dead SMTP provider must not turn a
    successful mutation into a 500.
    """

    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_recruitment_consent_email
        from app.core.i18n import resolve_locale, translate
        from app.modules.company.models import Tenant

        # HRP-834: the letter is in the recipient's language. The candidate
        # has no account, so the company's locale stands in for it — the
        # same rule every other candidate-facing letter of this module
        # applies. ``ConsentTemplate.language`` describes the consent
        # body, not the reader: it defaults to "en" and used to win here,
        # so a Russian company mailed an English wrapper on both the first
        # send and Resend.
        tenant = await db.get(Tenant, tenant_id)
        locale = resolve_locale(
            tenant_default=tenant.default_locale if tenant else None,
        )
        candidate_name = candidate_display_name(
            candidate, fallback=translate("email.fallback.unnamed", locale)
        )
        subject, html_body = render_recruitment_consent_email(
            request.token,
            candidate_name,
            template.body,
            expires_in_days=expires_in_days,
            locale=locale,
        )
        enqueue_email(
            request.email,
            subject,
            html_body,
            tenant_id=str(tenant_id),
            template_code="recruitment.consent_request",
        )
    except Exception:
        logger.exception(
            "Failed to enqueue recruitment consent email for candidate=%s",
            request.candidate_id,
        )


async def resend_consent_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> dict:
    """HRP-684: email the consent link again.

    (a) The letter goes to the candidate's *current* email, re-read from
    the card at send time — the address stored on the request is where
    the first letter went and may have been corrected since.
    (b) A link that is still valid is re-sent as is: token and expiry
    survive, so the first email keeps working and only ``last_sent_at``
    moves. An expired link is replaced instead of refused: the old request
    is marked expired and a new token goes out, with the lifetime the
    original was issued for - charged like a send.
    (c) A live link whose address was corrected is superseded by a new
    token with the same expiry: the first letter went to someone else.
    """

    import logging

    logger = logging.getLogger(__name__)

    candidate = await _get_candidate(db, tenant_id, candidate_id)

    request = (
        await db.execute(
            select(ConsentRequest)
            .where(
                ConsentRequest.candidate_id == candidate_id,
                ConsentRequest.tenant_id == tenant_id,
                ConsentRequest.status == "pending",
            )
            .order_by(ConsentRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if request is None:
        raise AppError("no_pending_consent_request", status.HTTP_404_NOT_FOUND)

    template = await db.get(ConsentTemplate, request.template_id)
    if template is None:
        raise AppError("consent_template_not_found", status.HTTP_404_NOT_FOUND)

    email = candidate.email or request.email
    now = datetime.now(timezone.utc)
    expires_at = _utc(request.expires_at)
    if expires_at <= now:
        issued_for = max(
            1,
            round((expires_at - _utc(request.created_at)).total_seconds() / 86400),
        )
        # A new link with a full lifetime is a new issuance, charged like
        # the send it replaces - only re-mailing a live link is free.
        await billing_hooks.precheck_action(
            db, tenant_id, "recruitment.send_consent_request"
        )
        request.status = "expired"
        request = _issue_consent_request(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            template=template,
            email=email,
            expires_in_days=issued_for,
            user_id=user_id,
        )
        db.add(request)
        await billing_hooks.consume_action(
            db, tenant_id, user_id, "recruitment.send_consent_request"
        )
        remaining = issued_for
    elif (request.email or "").lower() != (email or "").lower():
        # The address was corrected: whoever got the first, mis-addressed
        # letter must not keep a token that signs for the candidate. The new
        # link keeps the old one's expiry, so this stays a free re-send.
        request.status = "superseded"
        request = _issue_consent_request(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            template=template,
            email=email,
            expires_in_days=1,
            user_id=user_id,
        )
        request.expires_at = expires_at
        db.add(request)
        remaining = max(1, (expires_at - now).days)
    else:
        request.last_sent_at = now
        # Remaining lifetime, so the letter never promises days that are gone.
        remaining = max(1, (expires_at - now).days)
    await db.commit()
    await db.refresh(request)

    await _deliver_consent_email(
        db,
        tenant_id,
        candidate=candidate,
        template=template,
        request=request,
        expires_in_days=remaining,
        logger=logger,
    )

    return _consent_request_to_read(request)


async def get_consent_by_token(db: AsyncSession, token: str) -> dict:
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

    # HRP-384: resolve through the shared helper so the canonical
    # ``Candidate.full_name`` wins. Reading ``person`` alone left
    # resume-sourced candidates (``person_id`` NULL since HRP-181 REDO)
    # nameless here even though the row carries their name.
    # i18n F7: no English fallback on the wire — the public consent page
    # localizes the empty-name case itself.
    candidate_name = candidate_display_name(candidate, fallback="")

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
        raise AppError("consent_link_not_found", status.HTTP_404_NOT_FOUND)
    if request.status == "signed":
        return {"signed_at": request.signed_at, "status": "signed"}
    # Only a pending request signs: a superseded one (a newer send, or a
    # resend to a corrected address) is as dead as an expired one - its
    # letter may have gone to someone else.
    if request.status != "pending" or request.expires_at < datetime.now(timezone.utc):
        if request.status == "pending":
            request.status = "expired"
            await db.commit()
        raise AppError("consent_link_expired", status.HTTP_410_GONE)

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
        )
        .scalars()
        .all()
    ]
    if cv_ids:
        interviews = (
            (
                await db.execute(
                    select(Interview).where(
                        Interview.candidate_vacancy_id.in_(cv_ids),
                        Interview.tenant_id == request.tenant_id,
                        Interview.consent_signed_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
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


async def _resolve_consent_request(db: AsyncSession, token: str) -> ConsentRequest:
    request = (
        await db.execute(select(ConsentRequest).where(ConsentRequest.token == token))
    ).scalar_one_or_none()
    if not request:
        raise AppError("consent_link_not_found", status.HTTP_404_NOT_FOUND)
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
        # HRP-684: rows created before the column existed report their
        # creation time — that is when their link went out.
        "last_sent_at": r.last_sent_at or r.created_at,
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
    # HRP-979: the latest request may be a pending re-send while an older
    # signature is still in force, so the AI gates read this, not status.
    return {
        **_consent_request_to_read(request),
        "active": await has_active_consent(db, tenant_id, candidate_id),
    }


# ─── Active consent (HRP-979) ────────────────────────────────────────
#
# One rule for every entry point that hands a candidate's data to an AI
# provider (resume analysis, question generation, transcripts and their
# analysis, interview recordings): a consent request of this candidate in
# this tenant that the candidate signed and has not revoked. Revoking
# flips ``status``, so a signed row is the whole check. Demo and seeded
# candidates get such a row on creation; nothing beyond it is checked.
#
# Deliberate exception: resume parsing (``tasks/parsing.py``) sends the
# uploaded resume to the LLM without this check. Parsing is what creates
# the candidate card and finds the email the consent request goes to, so
# it has to run before any consent can exist. Everything built on the
# parse (analysis, questions) stays behind the gate.

_DEFAULT_TEMPLATE_NAME = "Candidate consent"
_DEFAULT_TEMPLATE_BODY = (
    "I agree that my application, interview recordings and transcripts are "
    "processed with AI assistance for this recruitment."
)
_CONSENT_REQUIRED_MESSAGE = "Candidate consent is required before this action"


def _active_consent_stmt(tenant_id: uuid.UUID, candidate_id: uuid.UUID):
    return (
        select(ConsentRequest.id)
        .where(
            ConsentRequest.tenant_id == tenant_id,
            ConsentRequest.candidate_id == candidate_id,
            ConsentRequest.status == "signed",
            ConsentRequest.signed_at.is_not(None),
        )
        .limit(1)
    )


async def has_active_consent(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> bool:
    result = await db.execute(_active_consent_stmt(tenant_id, candidate_id))
    return result.first() is not None


def has_active_consent_sync(
    db: Session, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> bool:
    """Sync twin for the Celery tasks."""
    return db.execute(_active_consent_stmt(tenant_id, candidate_id)).first() is not None


async def require_active_consent(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> None:
    """409 ``consent_required`` unless the candidate's consent is in force."""
    if not await has_active_consent(db, tenant_id, candidate_id):
        raise AppError("consent_required", status.HTTP_409_CONFLICT)


async def require_interview_consent(
    db: AsyncSession, tenant_id: uuid.UUID, interview: Interview
) -> None:
    candidate_id = await db.scalar(
        select(CandidateVacancy.candidate_id).where(
            CandidateVacancy.id == interview.candidate_vacancy_id
        )
    )
    if candidate_id is None:
        raise AppError("consent_required", status.HTTP_409_CONFLICT)
    await require_active_consent(db, tenant_id, candidate_id)


def analysis_consent_gate(
    tenant_id: str, *, interview_id: str | None = None, run_id: str | None = None
) -> dict | None:
    """First call of the analysis tasks.

    A consent revoked while the job sat in the queue stops it before any
    data reaches the AI provider: the interview analysis (and its
    in-flight run) or the resume-only run is failed with the reason, and
    the task returns the result handed back here. ``None`` means go on;
    rows that do not exist are left to the task's own handling.
    """
    from sqlalchemy import create_engine

    from app.config import settings

    engine = create_engine(settings.database_url.replace("+asyncpg", "+psycopg2"))
    try:
        with Session(engine) as db:
            tid = uuid.UUID(str(tenant_id))
            run = db.get(AIAnalysisRun, uuid.UUID(run_id)) if run_id else None
            interview = (
                db.get(Interview, uuid.UUID(interview_id)) if interview_id else None
            )
            owner = run or interview
            cv = db.get(CandidateVacancy, owner.candidate_vacancy_id) if owner else None
            if cv is None or has_active_consent_sync(db, tid, cv.candidate_id):
                return None
            if run is not None and run.status in ("pending", "processing"):
                run.status = "failed"
                run.error_message = _CONSENT_REQUIRED_MESSAGE
                run.current_stage = None
            if interview is not None:
                from app.modules.recruitment.tasks.analysis import (
                    _fail_inflight_full_run,
                )

                interview.analysis_status = "failed"
                interview.analysis_error = _CONSENT_REQUIRED_MESSAGE
                _fail_inflight_full_run(
                    db, tid, interview.id, _CONSENT_REQUIRED_MESSAGE
                )
            db.commit()
            return {"status": "failed", "error": "consent_required"}
    finally:
        engine.dispose()


async def _record_signed_consent(
    db: AsyncSession, tenant_id: uuid.UUID, candidate: Candidate
) -> ConsentRequest:
    """A consent signed on the candidate's behalf, on the active template.

    Used where no real candidate is there to sign: demo workspaces, the
    onboarding sample candidates and the E2E seam. Without an active
    template the default one is used, created on first need and kept
    inactive, so it never becomes what real consent requests are sent with.
    """
    template = await db.scalar(
        select(ConsentTemplate).where(
            ConsentTemplate.tenant_id == tenant_id,
            ConsentTemplate.is_active.is_(True),
        )
    )
    if template is None:
        template = await db.scalar(
            select(ConsentTemplate)
            .where(
                ConsentTemplate.tenant_id == tenant_id,
                ConsentTemplate.name == _DEFAULT_TEMPLATE_NAME,
            )
            .limit(1)
        )
    if template is None:
        template = ConsentTemplate(
            tenant_id=tenant_id,
            name=_DEFAULT_TEMPLATE_NAME,
            body=_DEFAULT_TEMPLATE_BODY,
            is_active=False,
        )
        db.add(template)
        await db.flush()
    now = datetime.now(timezone.utc)
    request = ConsentRequest(
        tenant_id=tenant_id,
        candidate_id=candidate.id,
        template_id=template.id,
        token=secrets.token_urlsafe(32),
        email=candidate.email or "",
        expires_at=now,
        signed_at=now,
        status="signed",
    )
    db.add(request)
    await db.flush()
    return request


async def _drop_unused_default_template(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Remove the inactive default template once no consent uses it.

    Auto-consents make it on demand; when their candidates go (the
    onboarding samples' cleanup), it has nothing left to stand behind.
    Matched by name and body, so a template an admin wrote stays.
    """
    await db.execute(
        delete(ConsentTemplate).where(
            ConsentTemplate.tenant_id == tenant_id,
            ConsentTemplate.name == _DEFAULT_TEMPLATE_NAME,
            ConsentTemplate.body == _DEFAULT_TEMPLATE_BODY,
            ConsentTemplate.is_active.is_(False),
            ~exists().where(ConsentRequest.template_id == ConsentTemplate.id),
        )
    )


async def auto_sign_demo_consent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate: Candidate,
    *,
    is_demo: bool | None = None,
) -> None:
    """Consent a candidate nobody real stands behind, at creation.

    Demo workspaces (``is_demo`` is looked up when the caller has not
    resolved it) and the onboarding sample candidates, which the seed
    passes as ``is_demo=True``: fictional people who cannot receive the
    consent email, and without consent no AI feature would open for them.
    A no-op for real candidates of a regular workspace.
    """
    if is_demo is None:
        from app.modules.demo.utils import is_demo_tenant

        is_demo = await is_demo_tenant(db, tenant_id)
    if is_demo:
        await _record_signed_consent(db, tenant_id, candidate)


async def revoke_consent(db: AsyncSession, token: str) -> dict:
    """Public endpoint — the candidate withdraws a signed consent.

    Consent is per candidate, so every signed request of the candidate in
    that tenant is revoked, not just this link's. Interviews lose the
    consent stamp signing gave them, which closes their upload gate too;
    AI processing is refused from here on until a new consent is signed.
    """
    request = (
        await db.execute(
            select(ConsentRequest)
            .where(ConsentRequest.token == token)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not request:
        raise AppError("consent_link_not_found", status.HTTP_404_NOT_FOUND)
    if request.status == "revoked":
        return {"status": "revoked"}
    if request.status != "signed":
        raise AppError("consent_not_signed", status.HTTP_409_CONFLICT)

    signed = list(
        (
            await db.execute(
                select(ConsentRequest).where(
                    ConsentRequest.tenant_id == request.tenant_id,
                    ConsentRequest.candidate_id == request.candidate_id,
                    ConsentRequest.status == "signed",
                )
            )
        ).scalars()
    )
    for row in signed:
        row.status = "revoked"
    cv_ids = select(CandidateVacancy.id).where(
        CandidateVacancy.tenant_id == request.tenant_id,
        CandidateVacancy.candidate_id == request.candidate_id,
    )
    await db.execute(
        update(Interview)
        .where(
            Interview.tenant_id == request.tenant_id,
            Interview.candidate_vacancy_id.in_(cv_ids),
        )
        .values(consent_signed_at=None, consent_template_id=None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    # Same as signing: a token flow with no tenant user, so the audit row
    # is written here rather than by the generic decorator.
    await audit_service.record_event(
        db,
        tenant_id=request.tenant_id,
        user_id=None,
        action="consent.revoke",
        entity_type="consent",
        entity_id=request.id,
        payload_diff={
            "revoked_at": datetime.now(timezone.utc).isoformat(),
            "requests": len(signed),
        },
    )
    return {"status": "revoked"}
