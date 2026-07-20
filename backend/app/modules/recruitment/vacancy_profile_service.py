"""Vacancy profile: AI generation session lifecycle (generate / cancel /
poll) and manual save.

Split out of ``service.py`` (project-review #7); see ``service.py`` for
the delegating namespace.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recruitment.common import (
    _get_vacancy,
    normalize_competence_id,
)
from app.modules.recruitment.models import (
    VacancyAttachment,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    VacancyProfileUpdate,
)

logger = logging.getLogger(__name__)


async def get_vacancy_profile(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> dict | None:
    """Get vacancy profile if exists."""
    await _get_vacancy(db, tenant_id, vacancy_id)

    result = await db.execute(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None

    return {
        "id": profile.id,
        "vacancy_id": profile.vacancy_id,
        "profile_data": profile.profile_data,
        "version": profile.version,
        "language": profile.language,
        "coverage_note": profile.coverage_note,
        "generated_by": profile.generated_by,
        "created_at": profile.created_at,
    }


def _extract_task_text(value: dict | list | str | None) -> str:
    """Pull plain text out of the JSON task fields used by VacancyForm.

    The frontend stores task blocks as ``{"text": "..."}``; older payloads
    accept plain strings or already-flattened lists. Returning a clean
    string keeps the LLM prompt readable instead of leaking JSON braces
    that confuse the model.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip()
        import json

        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_task_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(value)


async def _lookup_dictionary_title(
    db: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID | None
) -> str | None:
    """Resolve dictionary_items.title with tenant fallback to origin (null tenant)."""
    if item_id is None:
        return None
    from app.modules.dictionary.models import DictionaryItem

    result = await db.execute(
        select(DictionaryItem).where(DictionaryItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    if item.tenant_id is not None and item.tenant_id != tenant_id:
        return None
    return item.title


async def _build_attachments_text(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> str:
    """HRP-135 REDO: extract text from every vacancy attachment so it can
    feed the AI profile prompt.

    Reads attachment bytes from S3/MinIO when storage is configured and
    parses them through ``ai.file_parsing``. Files whose bytes are not
    available (storage disabled / file_id missing) are still listed by
    filename + mime type so the LLM at least knows what the recruiter
    attached. Returns an empty string when the vacancy has no
    attachments — the prompt template treats that as "no extra inputs".
    """
    from app.core.s3 import download_bytes
    from app.modules.ai.file_parsing import parse_file
    from app.modules.storage.models import File as StorageFile

    rows = (
        (
            await db.execute(
                select(VacancyAttachment)
                .where(
                    VacancyAttachment.vacancy_id == vacancy_id,
                    VacancyAttachment.tenant_id == tenant_id,
                )
                .order_by(VacancyAttachment.uploaded_at)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return ""

    file_paths: dict[uuid.UUID, str] = {}
    file_ids = [r.file_id for r in rows if r.file_id is not None]
    if file_ids:
        stored = (
            (await db.execute(select(StorageFile).where(StorageFile.id.in_(file_ids))))
            .scalars()
            .all()
        )
        file_paths = {f.id: f.path for f in stored if f.path}

    sections: list[str] = []
    for row in rows:
        header = f"# Attachment: {row.filename} ({row.mime_type})"
        path = file_paths.get(row.file_id) if row.file_id else None
        body = ""
        if path:
            raw = download_bytes(path)
            if raw is not None:
                try:
                    body = parse_file(row.filename, raw)
                except Exception:  # noqa: BLE001 - incl. UnsupportedFileError
                    # Best-effort: a single unparseable attachment must not
                    # poison the whole prompt. The header above tells the
                    # model that an attachment exists; we just skip the body.
                    body = ""
        sections.append(header if not body else f"{header}\n{body}")
    return "\n\n".join(sections)


async def generate_profile_now(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    clarification: str | None = None,
) -> dict:
    """Generate vacancy competency profile via LLM and park the result on
    the session row for review.

    Synchronous flow (no Celery dependency) so the API can return either
    the generated payload or a real error to the caller — the previous
    fire-and-forget task only surfaced as a stuck spinner when no worker
    was running, which is the root cause of HRP-134.

    HRP-235 REDO (QA case 4): the result is deliberately NOT written to
    ``vacancy_profiles``. It stays in ``session.result_payload`` until the
    recruiter reviews it in the matrix dialog and applies the selection
    (``save_profile`` via PUT /profile); discarding cancels the session
    and the saved profile is never touched.

    HRP-134 REDO: tracks the run in ``vacancy_profile_sessions`` so a
    returning user can see "Generating…" if the request is still
    in-flight server-side, and re-open the latest finished result via
    ``GET /recruitment/vacancies/{id}/profile/sessions/active``.

    ``clarification`` is free-form recruiter context that the new
    "Generate competence matrix" modal collects before kick-off — it
    rides through to the prompt so the LLM tilts the resulting competence
    list towards the recruiter's intent (e.g. "focus on backend leads,
    skip junior soft skills").
    """
    from app.modules.recruitment.ai_service import generate_vacancy_profile
    from app.modules.recruitment.models import Vacancy, VacancyProfileSession

    # Verify the vacancy belongs to the tenant before writing the session
    # row — otherwise a 404 would leave behind an orphan running session.
    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    # HRP-235 REDO (QA case 2): one generation session per vacancy at a
    # time. The row-level lock on the vacancy serialises concurrent
    # generate calls so the blocking-session check and the session insert
    # below are atomic — two tabs cannot both pass the check. A ``ready``
    # session with a parked (unreviewed) result blocks too: starting a
    # new run would orphan the pending payload the Review-for-save banner
    # promised. Legacy ``ready`` rows from before the deferred-save
    # change carry no ``profile_data`` (their result already landed in
    # the profile back then) and do not block.
    await db.execute(
        select(Vacancy.id).where(Vacancy.id == vacancy.id).with_for_update()
    )
    blocking_rows = (
        (
            await db.execute(
                select(VacancyProfileSession).where(
                    VacancyProfileSession.tenant_id == tenant_id,
                    VacancyProfileSession.vacancy_id == vacancy_id,
                    VacancyProfileSession.status.in_(("running", "ready")),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in blocking_rows:
        if row.status == "running":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Profile generation is already in progress for this vacancy.",
            )
        if (row.result_payload or {}).get("profile_data"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A generated profile is awaiting review for this vacancy — "
                "apply or discard it first.",
            )

    started_at = datetime.now(timezone.utc)
    session = VacancyProfileSession(
        tenant_id=tenant_id,
        vacancy_id=vacancy_id,
        started_by_id=user_id,
        status="running",
        started_at=started_at,
    )
    db.add(session)
    await db.flush()
    session_id = session.id
    # Commit the session row so a concurrent client polling
    # ``/profile/sessions/active`` can see status=running even while the
    # LLM call is still in flight on this connection.
    await db.commit()

    specialization_title = await _lookup_dictionary_title(
        db, tenant_id, vacancy.specialization_id
    )
    grade_title = await _lookup_dictionary_title(db, tenant_id, vacancy.grade_id)

    # HRP-135 REDO: surface the manual textual inputs (requirements /
    # responsibilities / conditions) and any uploaded attachments to the
    # prompt builder. Without this the recruiter's manual context is
    # silently dropped and the LLM has to guess from the title alone.
    attachments_text = await _build_attachments_text(db, tenant_id, vacancy_id)

    vacancy_data = {
        "vacancy_id": str(vacancy.id),
        "title": vacancy.title,
        "specialization": specialization_title or "Not specified",
        "grade": grade_title or "Not specified",
        "description": (vacancy.description or "").strip() or "Not specified",
        "tasks_main": _extract_task_text(vacancy.tasks_main) or "Not specified",
        "tasks_additional": _extract_task_text(vacancy.tasks_additional)
        or "Not specified",
        "tasks_kpi": _extract_task_text(vacancy.tasks_kpi) or "Not specified",
        "requirements": (vacancy.requirements or "").strip() or "Not specified",
        "responsibilities": (vacancy.responsibilities or "").strip() or "Not specified",
        "conditions": (vacancy.conditions or "").strip() or "Not specified",
        "attachments_text": attachments_text,
        "clarification": (clarification or "").strip(),
        "language": vacancy.language or "ru",
    }

    async def _mark_session_failed(error: str) -> None:
        # Re-fetch on a fresh transaction — the commit above closed it.
        # HRP-134 REDO follow-up: a plain ``db.get`` would return the
        # identity-map-cached row this request added earlier with
        # ``status="running"`` and mask a concurrent cancel committed on
        # a separate connection. ``populate_existing`` forces the SELECT
        # to overwrite identity-map state with the fresh DB read so a
        # "cancelled" status correctly wins over "failed".
        sess = (
            await db.execute(
                select(VacancyProfileSession)
                .where(VacancyProfileSession.id == session_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if sess is None:
            return
        if sess.status == "cancelled":
            # User dismissed mid-LLM; don't reopen the banner as "failed".
            return
        sess.status = "failed"
        sess.completed_at = datetime.now(timezone.utc)
        sess.error_message = error[:1000]
        await db.commit()

    try:
        profile_data = await generate_vacancy_profile(vacancy_data)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "generate_vacancy_profile failed for %s", vacancy_id
        )
        await _mark_session_failed(str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"AI profile generation failed: {exc}",
        )

    if not isinstance(profile_data, dict):
        await _mark_session_failed("AI returned non-dict payload")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "AI returned an unexpected payload (not a JSON object).",
        )

    # HRP-134 REDO: a single pre-write status check would only narrow,
    # not close, the cancel race — the cancel handler runs on a separate
    # AsyncSession and can commit ``status="cancelled"`` at any point
    # before our own commit. The fix is two-pronged: (1) ``populate_existing``
    # bypasses the identity-map cache that would otherwise serve the
    # stale ``status="running"`` row this request committed at the top;
    # (2) ``with_for_update`` takes a row-level lock so any concurrent
    # cancel either blocks until we commit or has already committed
    # before we get to read.
    for competence in profile_data.get("competences", []) or []:
        if isinstance(competence, dict):
            raw = competence.get("id") or competence.get("name") or ""
            normalized = normalize_competence_id(raw)
            if normalized is not None:
                competence["id"] = str(normalized)

    session_row = (
        await db.execute(
            select(VacancyProfileSession)
            .where(VacancyProfileSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if session_row is None or session_row.status == "cancelled":
        # Pin the vacancy primary key before rollback — afterwards the
        # ORM expires all attributes and accessing ``vacancy.id`` would
        # trigger a sync lazy-load that explodes inside async drivers.
        cancelled_vacancy_id = vacancy_id
        await db.rollback()
        # Return the same shape as the success path with a ``cancelled``
        # marker. Returning (instead of raising 409) keeps the EE billing
        # wrapper on the success branch — the LLM call already ran and
        # the platform paid for tokens, so the credit charge must land.
        return {
            "cancelled": True,
            "vacancy_id": cancelled_vacancy_id,
        }

    # HRP-235 REDO (QA case 4): the generated profile is NOT persisted to
    # ``vacancy_profiles`` here. It parks on the session row instead, and
    # only lands in the profile when the recruiter walks through the
    # Review competence matrix dialog and applies the selection (frontend
    # PUT /profile → ``save_profile``). Closing the generation window no
    # longer silently overwrites the saved profile.
    coverage_note = profile_data.get("coverage_note")

    # Session row is already held under FOR UPDATE; flip to ready and let
    # the commit release the lock + the result write atomically.
    session_row.status = "ready"
    session_row.completed_at = datetime.now(timezone.utc)
    session_row.result_payload = {
        "profile_data": profile_data,
        "coverage_note": coverage_note,
    }

    await db.commit()
    return {
        "status": "ready",
        "session_id": session_id,
        "vacancy_id": vacancy_id,
        "profile_data": profile_data,
        "coverage_note": coverage_note,
    }


async def cancel_active_profile_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
) -> dict:
    """HRP-235: mark the currently-running profile-generation session as
    cancelled so the UI can drop the in-progress banner.

    The synchronous ``generate_profile_now`` flow keeps the request
    handler busy until the LLM responds — cancellation here is a UI
    hint, not a true interrupt. The generate handler observes the
    cancelled status under its row lock and drops the result, and the
    next ``GET /profile/sessions/active`` returns ``None`` (because we
    exclude cancelled rows) so the user can dismiss the banner and start
    a fresh session.

    HRP-235 REDO (QA case 4): ``ready`` sessions are cancellable too —
    that is how the review dialog's Discard drops a pending result.
    Only a pinned ``session_id`` may retire a ``ready`` row: the legacy
    bodyless latest-match path keeps its historical running/failed scope,
    otherwise an older client's Dismiss could silently discard another
    tab's unreviewed result. Applying a pending result goes through
    ``apply_profile_session`` instead.
    """
    from app.modules.recruitment.models import VacancyProfileSession

    await _get_vacancy(db, tenant_id, vacancy_id)

    # HRP-134 REDO follow-up: acquire the same row-level lock the
    # generate handler uses (see ``generate_profile_now``) so the two
    # serialise rather than interleave. If generate already won the
    # race and flipped the row to ``ready``, this filter falls through
    # to "no_active_session" and the UI knows to keep the saved profile;
    # if we win, generate blocks on the lock until our commit, then
    # observes ``cancelled`` and bails out without writing the profile.
    # HRP-134 REDO (Viktoriya 2026-06-26): also dismiss the last
    # ``failed`` session so the inline error banner does not return on
    # the next poll. Without this the recruiter sees Profile generation
    # failed → click Dismiss → the next 4-second poll surfaces the
    # banner again, because ``get_active_profile_session`` keeps every
    # non-cancelled row.
    # HRP-134 REDO race fix: when the caller pins a ``session_id``
    # (Dismiss on a failed banner, Cancel on a known running session),
    # cancel exactly that row. The legacy latest-match path stays for
    # bodyless callers, but it could grab a *newer* running session
    # started from a second tab / by a second recruiter — dismissing an
    # old failed banner then killed the healthy run while the failed row
    # survived and resurrected the banner on the next poll.
    cancellable = (
        ("running", "failed", "ready")
        if session_id is not None
        else ("running", "failed")
    )
    stmt = (
        select(VacancyProfileSession)
        .where(
            VacancyProfileSession.tenant_id == tenant_id,
            VacancyProfileSession.vacancy_id == vacancy_id,
            VacancyProfileSession.status.in_(cancellable),
        )
        .order_by(VacancyProfileSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )
    if session_id is not None:
        stmt = stmt.where(VacancyProfileSession.id == session_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        # Idempotent: no running session is fine, the UI just dismisses.
        return {"status": "no_active_session"}
    prior_status = row.status
    row.status = "cancelled"
    row.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "status": "cancelled",
        "session_id": row.id,
        "prior_status": prior_status,
    }


async def get_active_profile_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    include_result: bool = True,
) -> dict | None:
    """HRP-134: latest non-terminal session for this vacancy, or None.

    Returns either the still-running session (so the UI can keep showing
    Generating…) or the most recent completed one. ``cancelled`` and
    ``applied`` rows are spent and never surface.

    HRP-235 REDO: ``has_pending_result`` tells the UI whether a ready
    session still holds an unreviewed payload (drives the Review-for-save
    banner and the action-button lock). ``include_result=False`` strips
    the generated ``profile_data`` from the response — the poll is
    readable by any tenant member, but the unapproved matrix itself is
    only for callers who can open the review dialog (admin/recruiter).
    """
    from app.modules.recruitment.models import VacancyProfileSession

    await _get_vacancy(db, tenant_id, vacancy_id)

    row = (
        await db.execute(
            select(VacancyProfileSession)
            .where(
                VacancyProfileSession.tenant_id == tenant_id,
                VacancyProfileSession.vacancy_id == vacancy_id,
                VacancyProfileSession.status.notin_(("cancelled", "applied")),
            )
            .order_by(VacancyProfileSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    payload = row.result_payload or {}
    has_pending_result = row.status == "ready" and bool(payload.get("profile_data"))
    if not include_result and "profile_data" in payload:
        payload = {k: v for k, v in payload.items() if k != "profile_data"}
    return {
        "id": row.id,
        "vacancy_id": row.vacancy_id,
        "status": row.status,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "error_message": row.error_message,
        "result_payload": payload or None,
        "has_pending_result": has_pending_result,
    }


async def apply_profile_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    session_id: uuid.UUID,
    data: VacancyProfileUpdate,
) -> dict:
    """HRP-235 REDO (QA case 4): persist a reviewed generation result.

    The review dialog sends back the (possibly edited / filtered)
    ``profile_data`` together with the session that produced it. In one
    transaction the profile row is upserted — with the AI provenance
    fields the old inline save used to set (``generated_by="ai"``,
    ``language`` from the vacancy on create, ``coverage_note`` column) —
    and the session flips to ``applied``, so the Review-for-save banner
    retires atomically with the save and the audit trail can tell an
    applied result from a discarded one.
    """
    from app.modules.recruitment.models import VacancyProfileSession

    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    session_row = (
        await db.execute(
            select(VacancyProfileSession)
            .where(
                VacancyProfileSession.id == session_id,
                VacancyProfileSession.tenant_id == tenant_id,
                VacancyProfileSession.vacancy_id == vacancy_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if session_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation session not found")
    if session_row.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Generation session is not awaiting review "
            f"(status: {session_row.status}).",
        )

    # Same stable-UUID normalisation as save_profile (HRP-348) — the
    # assessment sheets key their scores by competence id.
    for competence in data.profile_data.get("competences", []) or []:
        if isinstance(competence, dict):
            raw = competence.get("id") or competence.get("name") or ""
            normalized = normalize_competence_id(raw)
            if normalized is not None:
                competence["id"] = str(normalized)

    profile = (
        await db.execute(
            select(VacancyProfile).where(
                VacancyProfile.vacancy_id == vacancy_id,
                VacancyProfile.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()

    coverage_note = data.profile_data.get("coverage_note")
    if profile:
        profile.profile_data = data.profile_data
        profile.version = profile.version + 1
        profile.generated_by = "ai"
        if coverage_note:
            profile.coverage_note = coverage_note
    else:
        profile = VacancyProfile(
            tenant_id=tenant_id,
            vacancy_id=vacancy_id,
            profile_data=data.profile_data,
            version=1,
            language=vacancy.language or "ru",
            coverage_note=coverage_note,
            generated_by="ai",
        )
        db.add(profile)

    session_row.status = "applied"

    await db.commit()
    await db.refresh(profile)
    return {
        "id": profile.id,
        "vacancy_id": profile.vacancy_id,
        "profile_data": profile.profile_data,
        "version": profile.version,
        "language": profile.language,
        "coverage_note": profile.coverage_note,
        "generated_by": profile.generated_by,
        "created_at": profile.created_at,
    }


async def save_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: VacancyProfileUpdate,
) -> dict:
    """Save/update vacancy profile. If profile exists, increment version."""
    await _get_vacancy(db, tenant_id, vacancy_id)

    # HRP-348: manual PUT edits must keep competences addressable by the
    # same stable UUIDs the generate path assigns — assessment sheets and
    # question sets key their scores by competence id.
    for competence in data.profile_data.get("competences", []) or []:
        if isinstance(competence, dict):
            raw = competence.get("id") or competence.get("name") or ""
            normalized = normalize_competence_id(raw)
            if normalized is not None:
                competence["id"] = str(normalized)

    result = await db.execute(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )
    profile = result.scalar_one_or_none()

    if profile:
        # HRP-339: reject a stale draft — saving over a profile that moved
        # on (generation applied in another tab, a concurrent edit) would
        # silently discard the newer version.
        if data.base_version is not None and data.base_version != profile.version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The profile was updated while you were editing. "
                "Review the latest version before saving.",
            )
        profile.profile_data = data.profile_data
        profile.version = profile.version + 1
    else:
        profile = VacancyProfile(
            tenant_id=tenant_id,
            vacancy_id=vacancy_id,
            profile_data=data.profile_data,
            version=1,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)
    return {
        "id": profile.id,
        "vacancy_id": profile.vacancy_id,
        "profile_data": profile.profile_data,
        "version": profile.version,
        "language": profile.language,
        "coverage_note": profile.coverage_note,
        "generated_by": profile.generated_by,
        "created_at": profile.created_at,
    }
