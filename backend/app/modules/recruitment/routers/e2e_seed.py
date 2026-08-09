"""E2E-only seed endpoints behind E2E_MODE (HRP-181 REDO Stage 5)."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

router = APIRouter(tags=["recruitment"])


# ── HRP-181 REDO Stage 5 — E2E seed helpers ────────────────────────
#
# Two tiny endpoints behind ``E2E_MODE`` so the Playwright recruitment
# spec can drive the bulk-upload modal and the AI verdict popover without
# a Celery worker / live LLM key. ``include_in_schema=False`` keeps them
# out of the public OpenAPI surface; production gets a 404.


@router.post(
    "/recruitment/_test/seed-parsed-files",
    status_code=200,
    include_in_schema=False,
)
async def _test_seed_parsed_files(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flip a batch of detached ``CandidateFile`` rows to ``completed``.

    Payload: ``{"files": [{"file_id": "...", "parsed_data": {...}}]}``.
    ``parsed_data`` is optional — when omitted the row gets a deterministic
    stub the dedup preview can read. E2E-only; returns 404 in prod.
    """
    from sqlalchemy import select

    from app.config import settings
    from app.modules.recruitment.models import CandidateFile

    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")

    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise HTTPException(
            status_code=400,
            detail="files: non-empty list of {file_id, parsed_data?} required",
        )

    requested: list[tuple[uuid.UUID, dict]] = []
    for idx, entry in enumerate(raw_files):
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=400, detail=f"files[{idx}]: object required"
            )
        try:
            fid = uuid.UUID(str(entry.get("file_id")))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"files[{idx}].file_id: invalid UUID",
            ) from exc
        parsed = entry.get("parsed_data")
        if parsed is None:
            parsed = {
                "first_name": "Seed",
                "last_name": f"Candidate {idx + 1}",
                "contacts": {"email": f"seed-{fid}@example.com"},
                "experience": [{"position": "Engineer"}],
            }
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=400,
                detail=f"files[{idx}].parsed_data: object required",
            )
        requested.append((fid, parsed))

    rows = (
        (
            await db.execute(
                select(CandidateFile).where(
                    CandidateFile.id.in_([fid for fid, _ in requested]),
                    CandidateFile.tenant_id == current_user.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}

    affected = 0
    for fid, parsed in requested:
        row = by_id.get(fid)
        if row is None:
            continue
        row.parse_status = "completed"
        row.parsed_data = parsed
        affected += 1
    await db.commit()
    return {"updated": affected}


@router.post(
    "/recruitment/_test/seed-verdict",
    status_code=200,
    include_in_schema=False,
)
async def _test_seed_verdict(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Overwrite the AI block on a ``CandidateVacancy`` row.

    Real verdicts come from ``ai_service.assess_candidate``; the Playwright
    spec uses this shortcut to drive the verdict-popover happy path.
    """
    from sqlalchemy import select

    from app.config import settings
    from app.modules.recruitment.models import CandidateVacancy

    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        cv_id = uuid.UUID(str(payload.get("candidate_vacancy_id")))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="candidate_vacancy_id: invalid UUID",
        ) from exc

    updates: dict[str, object] = {}
    for key in (
        "ai_verdict",
        "ai_readiness",
        "ai_score",
        # HRP-274: tenant-scale rebase of the canonical 0..1 ``ai_score``
        # — lets the raw/normalized toggle spec seed both sides.
        "ai_score_normalized",
        # HRP-273: mode of the active analysis run — drives the
        # ``[resume only]`` / ``[full]`` sub-badge next to the verdict.
        "ai_analysis_mode",
        "ai_verdict_summary",
        "ai_key_strength",
        "ai_key_risk",
        "ai_risk_mitigation",
    ):
        if key in payload:
            updates[key] = payload[key]
    if not updates:
        raise HTTPException(status_code=400, detail="No AI fields supplied")

    cv = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise HTTPException(status_code=404, detail="candidate_vacancy not found")

    for k, v in updates.items():
        setattr(cv, k, v)
    # HRP-493 made the candidates table derive ``ai_readiness`` from the
    # inputs the model can actually see, so seeding the column alone is
    # invisible on the list. Back a resume-backed readiness with a parsed
    # resume stub; transcript-backed readiness would need a transcribed
    # Interview row, which no spec seeds this way today.
    if updates.get("ai_readiness") in ("resume_only", "resume_and_transcript"):
        from app.modules.recruitment.models import Candidate

        cand = (
            await db.execute(
                select(Candidate).where(
                    Candidate.id == cv.candidate_id,
                    Candidate.tenant_id == current_user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if cand is not None and cand.parsed_resume_jsonb is None:
            cand.parsed_resume_jsonb = {"summary": "seeded by _test/seed-verdict"}
    cv.version = (cv.version or 1) + 1
    await db.commit()
    return {"id": str(cv.id), "version": cv.version}


@router.get(
    "/recruitment/_test/assessment-invites/{invite_id}/token",
    include_in_schema=False,
)
async def _test_get_assessment_invite_token(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reveal a manager-assessment invite token for the public-link e2e.

    The real token travels only inside the invite email (the API returns
    the invite row without it), so the cold-start spec needs this
    E2E_MODE-gated reveal — same precedent as ``dev_get_invitation_token``
    in the auth router. Tenant-scoped; production gets a 404.
    """
    from sqlalchemy import select

    from app.config import settings
    from app.modules.recruitment.models import AssessmentInvite

    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")

    invite = (
        await db.execute(
            select(AssessmentInvite).where(
                AssessmentInvite.id == invite_id,
                AssessmentInvite.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="invite not found")
    return {"id": str(invite.id), "token": invite.token}
