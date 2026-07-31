"""HRP-186: service layer for the manager-assessment subsystem.

The flow is:

* tenant owns one or more :class:`AssessmentScale` rows (one default).
* a vacancy holds an ``assessment_scale_id`` FK; on the first assessment
  write the scale is snapshotted into ``assessment_scale_snapshot``.
* each candidate-vacancy can have many :class:`AssessmentRound` rows;
  every round has one or more :class:`RecruitmentAssessment` sheets,
  one per evaluator (user or invited).
* the round aggregates competence scores; the candidate-vacancy carries
  the denormalized ``manager_score`` from the latest complete round
  (or last with any scores) — recomputed by :func:`recompute_manager_score`.

Token security for invited evaluators lives in
:mod:`app.modules.recruitment.manager_assessment_public`.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.recruitment import audit_service
from app.modules.recruitment.common import candidate_display_name
from app.modules.recruitment.manager_assessment_models import (
    AssessmentCompetenceScore,
    AssessmentIndicatorScore,
    AssessmentRound,
    AssessmentRoundEvaluator,
    AssessmentScale,
    AssessmentScaleLevel,
    RecruitmentAssessment,
)
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    IndicatorScoreIn,
    ManagerAssessmentInviteCreate,
    RoundCreate,
    ScaleCreate,
    ScaleUpdate,
)
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateVacancy,
    Vacancy,
    VacancyProfile,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """SHA-256 digest of a token, hex-encoded.

    A static SHA-256 is fine here because tokens are 32-byte random
    ``secrets.token_urlsafe`` strings — the hash is purely to defeat DB
    dump extraction, not to harden against brute force on a low-entropy
    secret.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token() -> tuple[str, str]:
    """Return ``(plaintext, hash)`` for a brand-new invite token."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


# ---------------------------------------------------------------------------
# Default seed (used in tests + bootstrap)
# ---------------------------------------------------------------------------


DEFAULT_SCALE_NAME = "Standard 1-4"
DEFAULT_SCALE_DESCRIPTION = "Default scale shipped with HRPulsar."
DEFAULT_SCALE_LEVELS = [
    {
        "value": 1,
        "label": "Not suitable",
        "description": "Cannot perform required tasks",
        "weight": 0,
        "color": "rose",
        "sort_order": 0,
    },
    {
        "value": 2,
        "label": "Below expectations",
        "description": "Significant gaps",
        "weight": 33,
        "color": "amber",
        "sort_order": 1,
    },
    {
        "value": 3,
        "label": "Meets expectations",
        "description": "Acceptable level",
        "weight": 66,
        "color": "blue",
        "sort_order": 2,
    },
    {
        "value": 4,
        "label": "Exceeds expectations",
        "description": "Top performer",
        "weight": 100,
        "color": "emerald",
        "sort_order": 3,
    },
]


async def ensure_default_scale(
    db: AsyncSession, tenant_id: uuid.UUID
) -> AssessmentScale:
    """Return the tenant default scale, creating the seed if none exists."""

    result = await db.execute(
        select(AssessmentScale).where(
            AssessmentScale.tenant_id == tenant_id,
            AssessmentScale.archived_at.is_(None),
        )
    )
    scales = result.scalars().all()
    for scale in scales:
        if scale.is_default:
            return scale
    if scales:
        scales[0].is_default = True
        await db.commit()
        await db.refresh(scales[0])
        return scales[0]

    scale = AssessmentScale(
        tenant_id=tenant_id,
        name=DEFAULT_SCALE_NAME,
        description=DEFAULT_SCALE_DESCRIPTION,
        is_default=True,
        divergence_threshold=2,
        version=1,
    )
    db.add(scale)
    await db.flush()
    for level in DEFAULT_SCALE_LEVELS:
        db.add(
            AssessmentScaleLevel(
                scale_id=scale.id,
                value=level["value"],
                label=level["label"],
                description=level["description"],
                weight=level["weight"],
                color=level["color"],
                sort_order=level["sort_order"],
            )
        )
    await db.commit()
    await db.refresh(scale)
    return scale


# ---------------------------------------------------------------------------
# Scales — CRUD
# ---------------------------------------------------------------------------


async def list_scales(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AssessmentScale)
        .where(AssessmentScale.tenant_id == tenant_id)
        .order_by(
            AssessmentScale.archived_at.is_(None).desc(),
            AssessmentScale.is_default.desc(),
            AssessmentScale.name,
        )
    )
    scales = result.scalars().all()
    if not scales:
        await ensure_default_scale(db, tenant_id)
        result = await db.execute(
            select(AssessmentScale).where(AssessmentScale.tenant_id == tenant_id)
        )
        scales = result.scalars().all()
    return [await _scale_to_dict(db, s) for s in scales]


async def get_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> dict[str, Any]:
    scale = await _load_scale(db, tenant_id, scale_id)
    return await _scale_to_dict(db, scale)


async def create_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: ScaleCreate,
) -> dict[str, Any]:
    if payload.is_default:
        await _clear_default(db, tenant_id)

    scale = AssessmentScale(
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        is_default=payload.is_default,
        divergence_threshold=payload.divergence_threshold,
        version=1,
    )
    db.add(scale)
    await db.flush()
    for lvl in payload.levels:
        db.add(
            AssessmentScaleLevel(
                scale_id=scale.id,
                value=lvl.value,
                label=lvl.label,
                description=lvl.description,
                weight=lvl.weight,
                color=lvl.color,
                sort_order=lvl.sort_order,
            )
        )
    await db.commit()
    await db.refresh(scale)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_scale.create",
        entity_type="assessment_scale",
        entity_id=scale.id,
        payload_diff={"name": scale.name, "levels": len(payload.levels)},
    )
    return await _scale_to_dict(db, scale)


async def update_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    scale_id: uuid.UUID,
    payload: ScaleUpdate,
) -> dict[str, Any]:
    scale = await _load_scale(db, tenant_id, scale_id)
    if scale.archived_at is not None:
        raise AppError("archived_scales_read_only", status.HTTP_409_CONFLICT)

    if payload.is_default is True:
        await _clear_default(db, tenant_id, except_id=scale.id)
        scale.is_default = True
    elif payload.is_default is False:
        scale.is_default = False

    if payload.name is not None:
        scale.name = payload.name
    if payload.description is not None:
        scale.description = payload.description
    if payload.divergence_threshold is not None:
        scale.divergence_threshold = payload.divergence_threshold

    if payload.levels is not None:
        if await _scale_in_use(db, tenant_id, scale.id):
            raise AppError("scale_levels_locked", status.HTTP_409_CONFLICT)
        await db.execute(
            delete(AssessmentScaleLevel).where(
                AssessmentScaleLevel.scale_id == scale.id
            )
        )
        for lvl in payload.levels:
            db.add(
                AssessmentScaleLevel(
                    scale_id=scale.id,
                    value=lvl.value,
                    label=lvl.label,
                    description=lvl.description,
                    weight=lvl.weight,
                    color=lvl.color,
                    sort_order=lvl.sort_order,
                )
            )

    scale.version += 1
    await db.commit()
    await db.refresh(scale)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_scale.update",
        entity_type="assessment_scale",
        entity_id=scale.id,
        payload_diff={"version": scale.version},
    )
    return await _scale_to_dict(db, scale)


async def archive_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    scale_id: uuid.UUID,
) -> dict[str, Any]:
    scale = await _load_scale(db, tenant_id, scale_id)
    if scale.archived_at is not None:
        return await _scale_to_dict(db, scale)
    scale.archived_at = datetime.now(timezone.utc)
    if scale.is_default:
        scale.is_default = False
        # Promote the next non-archived scale as default if any exists.
        other = await db.execute(
            select(AssessmentScale)
            .where(
                AssessmentScale.tenant_id == tenant_id,
                AssessmentScale.id != scale.id,
                AssessmentScale.archived_at.is_(None),
            )
            .order_by(AssessmentScale.name)
        )
        promote = other.scalars().first()
        if promote is not None:
            promote.is_default = True
    await db.commit()
    await db.refresh(scale)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_scale.archive",
        entity_type="assessment_scale",
        entity_id=scale.id,
    )
    return await _scale_to_dict(db, scale)


async def delete_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    scale_id: uuid.UUID,
) -> None:
    scale = await _load_scale(db, tenant_id, scale_id)
    if await _scale_in_use(db, tenant_id, scale.id):
        raise AppError("scale_in_use_archive_only", status.HTTP_409_CONFLICT)
    await db.execute(
        delete(AssessmentScaleLevel).where(AssessmentScaleLevel.scale_id == scale.id)
    )
    await db.delete(scale)
    await db.commit()
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_scale.delete",
        entity_type="assessment_scale",
        entity_id=scale.id,
    )


# ---------------------------------------------------------------------------
# Vacancy ↔ scale binding
# ---------------------------------------------------------------------------


async def set_vacancy_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    vacancy_id: uuid.UUID,
    scale_id: uuid.UUID,
) -> dict[str, Any]:
    vacancy = await _load_vacancy(db, tenant_id, vacancy_id)
    if vacancy.assessment_scale_snapshot is not None:
        raise AppError("vacancy_scale_frozen", status.HTTP_409_CONFLICT)
    scale = await _load_scale(db, tenant_id, scale_id)
    vacancy.assessment_scale_id = scale.id
    await db.commit()
    await db.refresh(vacancy)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="vacancy.scale_set",
        entity_type="vacancy",
        entity_id=vacancy.id,
        payload_diff={"scale_id": str(scale.id)},
    )
    return {
        "vacancy_id": vacancy.id,
        "assessment_scale_id": vacancy.assessment_scale_id,
        "assessment_scale_snapshot": vacancy.assessment_scale_snapshot,
    }


async def _snapshot_vacancy_scale(
    db: AsyncSession, vacancy: Vacancy
) -> dict[str, Any] | None:
    """Freeze the vacancy's scale into a JSONB snapshot if not already.

    Returns the snapshot dict, or None if no scale is bound.
    """

    if vacancy.assessment_scale_snapshot is not None:
        return vacancy.assessment_scale_snapshot
    scale_id = vacancy.assessment_scale_id
    scale: AssessmentScale | None
    if scale_id is None:
        scale = await ensure_default_scale(db, vacancy.tenant_id)
        vacancy.assessment_scale_id = scale.id
    else:
        scale = await db.get(AssessmentScale, scale_id)
    if scale is None:
        return None
    snapshot = await _scale_to_dict(db, scale)
    # snapshot stores only the fields needed to render the form
    snap_payload = {
        "scale_id": str(snapshot["id"]),
        "name": snapshot["name"],
        "divergence_threshold": snapshot["divergence_threshold"],
        "levels": [
            {
                "value": lvl["value"],
                "label": lvl["label"],
                "description": lvl["description"],
                "weight": lvl["weight"],
                "color": lvl["color"],
                "sort_order": lvl["sort_order"],
            }
            for lvl in snapshot["levels"]
        ],
    }
    vacancy.assessment_scale_snapshot = snap_payload
    await db.commit()
    await db.refresh(vacancy)
    return vacancy.assessment_scale_snapshot


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


async def list_rounds(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> list[dict[str, Any]]:
    await _load_cv(db, tenant_id, cv_id)
    result = await db.execute(
        select(AssessmentRound)
        .where(
            AssessmentRound.candidate_vacancy_id == cv_id,
            AssessmentRound.tenant_id == tenant_id,
        )
        .order_by(
            AssessmentRound.created_at,
        )
    )
    rounds = result.scalars().all()
    return [await _round_to_dict(db, r) for r in rounds]


async def create_round(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    cv_id: uuid.UUID,
    payload: RoundCreate,
) -> dict[str, Any]:
    cv = await _load_cv(db, tenant_id, cv_id)

    rounds = await db.execute(
        select(AssessmentRound).where(
            AssessmentRound.candidate_vacancy_id == cv.id,
            AssessmentRound.tenant_id == tenant_id,
        )
    )
    existing = rounds.scalars().all()

    if payload.type == "pre_interview":
        if any(r.type == "pre_interview" for r in existing):
            raise AppError("pre_interview_round_exists", status.HTTP_409_CONFLICT)
        round_number = None
    elif payload.type == "final":
        if any(r.type == "final" for r in existing):
            raise AppError("final_round_exists", status.HTTP_409_CONFLICT)
        round_number = None
    else:
        existing_iv = [r for r in existing if r.type == "interview"]
        max_num = max((r.round_number or 0) for r in existing_iv) if existing_iv else 0
        round_number = payload.round_number or max_num + 1

    rd = AssessmentRound(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv.id,
        type=payload.type,
        round_number=round_number,
        status="in_progress",
        created_by=user_id,
    )
    db.add(rd)
    await db.commit()
    await db.refresh(rd)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_round.create",
        entity_type="assessment_round",
        entity_id=rd.id,
        payload_diff={"type": rd.type, "round_number": rd.round_number},
    )
    return await _round_to_dict(db, rd)


async def update_round_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    round_id: uuid.UUID,
    new_status: str,
    archived_reason: str | None = None,
) -> dict[str, Any]:
    if new_status not in {"in_progress", "complete", "archived"}:
        raise AppError("invalid_round_status", status.HTTP_400_BAD_REQUEST)
    rd = await _load_round(db, tenant_id, round_id)
    rd.status = new_status
    if new_status == "complete":
        rd.completed_at = datetime.now(timezone.utc)
    elif new_status == "archived":
        rd.archived_at = datetime.now(timezone.utc)
        rd.archived_reason = archived_reason
    await db.commit()
    await db.refresh(rd)
    await recompute_manager_score(db, tenant_id, rd.candidate_vacancy_id)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action=f"assessment_round.{new_status}",
        entity_type="assessment_round",
        entity_id=rd.id,
    )
    return await _round_to_dict(db, rd)


async def _assert_pre_interview_slot_free(
    db: AsyncSession,
    rd: AssessmentRound,
    *,
    evaluator_user_id: uuid.UUID | None = None,
    evaluator_invite_id: uuid.UUID | None = None,
) -> None:
    """HRP-369: a pre_interview round holds exactly one evaluator.

    Called on every path that can claim the slot (internal evaluator row,
    invite creation, sheet creation on invite acceptance). Locks the round
    row to serialize concurrent claims; ``rd`` may be a pre-lock read —
    only the immutable ``id``/``type`` are used. The caller's own claim
    (matching ``evaluator_user_id`` / ``evaluator_invite_id``) stays
    idempotent. Sheets of revoked or declined invites no longer occupy the
    slot, and a sheet orphaned by user deletion (both evaluator columns
    NULL) never does — otherwise a dead sheet would brick the round.
    """
    if rd.type != "pre_interview":
        return
    await db.execute(
        select(AssessmentRound.id).where(AssessmentRound.id == rd.id).with_for_update()
    )
    evaluator_q = select(AssessmentRoundEvaluator.user_id).where(
        AssessmentRoundEvaluator.round_id == rd.id
    )
    if evaluator_user_id is not None:
        evaluator_q = evaluator_q.where(
            AssessmentRoundEvaluator.user_id != evaluator_user_id
        )
    other_evaluator = await db.execute(evaluator_q)

    sheet_q = (
        select(RecruitmentAssessment.id)
        .outerjoin(
            AssessmentInvite,
            RecruitmentAssessment.evaluator_invite_id == AssessmentInvite.id,
        )
        .where(
            RecruitmentAssessment.round_id == rd.id,
            or_(
                # Another internal evaluator's sheet (NULL user never matches).
                RecruitmentAssessment.evaluator_user_id.is_not(None),
                # A live invited evaluator's sheet.
                AssessmentInvite.status.notin_(("revoked", "declined")),
            ),
        )
    )
    # NULL-safe own-claim exclusion: a plain ``~(col == own)`` would drop
    # NULL-column rows (invited sheets when checking a user, and vice
    # versa) because the negation evaluates to NULL.
    if evaluator_user_id is not None:
        sheet_q = sheet_q.where(
            or_(
                RecruitmentAssessment.evaluator_user_id.is_(None),
                RecruitmentAssessment.evaluator_user_id != evaluator_user_id,
            )
        )
    if evaluator_invite_id is not None:
        sheet_q = sheet_q.where(
            or_(
                RecruitmentAssessment.evaluator_invite_id.is_(None),
                RecruitmentAssessment.evaluator_invite_id != evaluator_invite_id,
            )
        )
    other_sheet = await db.execute(sheet_q)

    if other_evaluator.first() is not None or other_sheet.first() is not None:
        raise AppError("pre_interview_single_evaluator", status.HTTP_409_CONFLICT)


async def add_evaluator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    round_id: uuid.UUID,
    evaluator_user_id: uuid.UUID,
) -> dict[str, Any]:
    rd = await _load_round(db, tenant_id, round_id)
    # HRP-369: the FIRST user to start scoring becomes the round's only
    # evaluator (re-adding themselves stays idempotent); any other claim
    # on the slot is rejected.
    await _assert_pre_interview_slot_free(db, rd, evaluator_user_id=evaluator_user_id)
    existing = await db.execute(
        select(AssessmentRoundEvaluator).where(
            AssessmentRoundEvaluator.round_id == rd.id,
            AssessmentRoundEvaluator.user_id == evaluator_user_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(AssessmentRoundEvaluator(round_id=rd.id, user_id=evaluator_user_id))
        await db.commit()
    # Pre-create the draft assessment sheet so PATCH endpoints can hit it.
    await get_or_create_assessment(
        db, tenant_id, rd.id, evaluator_user_id=evaluator_user_id
    )
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_round.add_evaluator",
        entity_type="assessment_round",
        entity_id=rd.id,
        payload_diff={"evaluator_user_id": str(evaluator_user_id)},
    )
    return await _round_to_dict(db, rd)


# ---------------------------------------------------------------------------
# Assessments — per-evaluator sheets
# ---------------------------------------------------------------------------


async def get_or_create_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    round_id: uuid.UUID,
    *,
    evaluator_user_id: uuid.UUID | None = None,
    evaluator_invite_id: uuid.UUID | None = None,
    evaluator_display_name: str | None = None,
) -> RecruitmentAssessment:
    if evaluator_user_id is None and evaluator_invite_id is None:
        raise AppError("evaluator_user_or_invite_required", status.HTTP_400_BAD_REQUEST)
    rd = await _load_round(db, tenant_id, round_id)
    # Take the scale snapshot lazily — on the first sheet creation.
    cv = await db.get(CandidateVacancy, rd.candidate_vacancy_id)
    if cv is not None:
        vacancy = await db.get(Vacancy, cv.vacancy_id)
        if vacancy is not None:
            await _snapshot_vacancy_scale(db, vacancy)

    async def _find_existing() -> RecruitmentAssessment | None:
        if evaluator_user_id is not None:
            result = await db.execute(
                select(RecruitmentAssessment).where(
                    RecruitmentAssessment.round_id == rd.id,
                    RecruitmentAssessment.evaluator_user_id == evaluator_user_id,
                )
            )
        else:
            result = await db.execute(
                select(RecruitmentAssessment).where(
                    RecruitmentAssessment.round_id == rd.id,
                    RecruitmentAssessment.evaluator_invite_id == evaluator_invite_id,
                )
            )
        return result.scalar_one_or_none()

    existing = await _find_existing()
    if existing is not None:
        return existing
    # HRP-369: sheet creation also claims the pre_interview single slot —
    # the invite-acceptance path arrives here without add_evaluator.
    await _assert_pre_interview_slot_free(
        db,
        rd,
        evaluator_user_id=evaluator_user_id,
        evaluator_invite_id=evaluator_invite_id,
    )
    if rd.type == "pre_interview":
        # Re-check under the round lock: two simultaneous first loads of
        # the same evaluator's sheet would otherwise both pass the guard
        # (own claim excluded) and the loser would 500 on the unique index.
        existing = await _find_existing()
        if existing is not None:
            return existing
    a = RecruitmentAssessment(
        tenant_id=tenant_id,
        round_id=rd.id,
        evaluator_type="user" if evaluator_user_id is not None else "invited",
        evaluator_user_id=evaluator_user_id,
        evaluator_invite_id=evaluator_invite_id,
        evaluator_display_name=evaluator_display_name,
        status="draft",
        version=1,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def list_assessments_for_round(
    db: AsyncSession, tenant_id: uuid.UUID, round_id: uuid.UUID
) -> list[dict[str, Any]]:
    await _load_round(db, tenant_id, round_id)
    result = await db.execute(
        select(RecruitmentAssessment).where(
            RecruitmentAssessment.round_id == round_id,
            RecruitmentAssessment.tenant_id == tenant_id,
        )
    )
    assessments = result.scalars().all()
    return [await _assessment_to_dict(db, a) for a in assessments]


async def get_assessment(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    a = await _load_assessment(db, tenant_id, assessment_id)
    return await _assessment_to_dict(db, a)


async def set_competence_score(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    assessment_id: uuid.UUID,
    competence_id: uuid.UUID,
    payload: CompetenceScoreIn,
) -> dict[str, Any]:
    a = await _load_assessment(db, tenant_id, assessment_id)
    if (
        a.evaluator_user_id is not None
        and user_id is not None
        and a.evaluator_user_id != user_id
    ):
        raise AppError("assessment_sheet_owner_only", status.HTTP_403_FORBIDDEN)
    result = await db.execute(
        select(AssessmentCompetenceScore).where(
            AssessmentCompetenceScore.assessment_id == a.id,
            AssessmentCompetenceScore.competence_id == competence_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = AssessmentCompetenceScore(
            tenant_id=tenant_id,
            assessment_id=a.id,
            competence_id=competence_id,
            score_value=payload.score_value,
            score_source=payload.score_source,
            comment=payload.comment,
        )
        db.add(row)
    else:
        row.score_value = payload.score_value
        row.score_source = payload.score_source
        row.comment = payload.comment
    a.version += 1
    round_id = a.round_id
    assessment_id = a.id
    await db.commit()
    await db.refresh(row)
    cv_id = await _cv_id_for_round(db, round_id)
    if cv_id is not None:
        await recompute_manager_score(db, tenant_id, cv_id)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment.competence_score_set",
        entity_type="assessment",
        entity_id=assessment_id,
        payload_diff={
            "competence_id": str(competence_id),
            "score_value": payload.score_value,
            "source": payload.score_source,
        },
    )
    return _competence_score_to_dict(row)


async def set_indicator_score(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    assessment_id: uuid.UUID,
    indicator_id: uuid.UUID,
    payload: IndicatorScoreIn,
) -> dict[str, Any]:
    a = await _load_assessment(db, tenant_id, assessment_id)
    if (
        a.evaluator_user_id is not None
        and user_id is not None
        and a.evaluator_user_id != user_id
    ):
        raise AppError("assessment_sheet_owner_only", status.HTTP_403_FORBIDDEN)
    result = await db.execute(
        select(AssessmentIndicatorScore).where(
            AssessmentIndicatorScore.assessment_id == a.id,
            AssessmentIndicatorScore.indicator_id == indicator_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = AssessmentIndicatorScore(
            tenant_id=tenant_id,
            assessment_id=a.id,
            indicator_id=indicator_id,
            competence_id=payload.competence_id,
            score_value=payload.score_value,
            comment=payload.comment,
        )
        db.add(row)
    else:
        row.score_value = payload.score_value
        row.comment = payload.comment
        row.competence_id = payload.competence_id

    # If indicators are scored on this competence, mark the overall as
    # computed and recompute its value as the rounded mean.
    indicator_result = await db.execute(
        select(AssessmentIndicatorScore).where(
            AssessmentIndicatorScore.assessment_id == a.id,
            AssessmentIndicatorScore.competence_id == payload.competence_id,
        )
    )
    indicators = [
        i for i in indicator_result.scalars().all() if i.score_value is not None
    ]
    overall_result = await db.execute(
        select(AssessmentCompetenceScore).where(
            AssessmentCompetenceScore.assessment_id == a.id,
            AssessmentCompetenceScore.competence_id == payload.competence_id,
        )
    )
    overall = overall_result.scalar_one_or_none()
    if indicators:
        avg = round(
            sum(i.score_value for i in indicators if i.score_value is not None)
            / len(indicators)
        )
        if overall is None:
            overall = AssessmentCompetenceScore(
                tenant_id=tenant_id,
                assessment_id=a.id,
                competence_id=payload.competence_id,
                score_value=avg,
                score_source="computed_from_indicators",
            )
            db.add(overall)
        elif overall.score_source != "manual":
            overall.score_value = avg
            overall.score_source = "computed_from_indicators"
    elif overall is not None and overall.score_source != "manual":
        # HRP-348: the last indicator score was cleared — a stale computed
        # overall must not keep the competence looking assessed.
        overall.score_value = None
    a.version += 1
    round_id = a.round_id
    assessment_id = a.id
    await db.commit()
    await db.refresh(row)
    cv_id = await _cv_id_for_round(db, round_id)
    if cv_id is not None:
        await recompute_manager_score(db, tenant_id, cv_id)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment.indicator_score_set",
        entity_type="assessment",
        entity_id=assessment_id,
        payload_diff={
            "indicator_id": str(indicator_id),
            "score_value": payload.score_value,
        },
    )
    return _indicator_score_to_dict(row)


async def submit_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    assessment_id: uuid.UUID,
    *,
    final_notes: str | None = None,
) -> dict[str, Any]:
    a = await _load_assessment(db, tenant_id, assessment_id)
    a.status = "submitted"
    a.submitted_at = datetime.now(timezone.utc)
    if final_notes is not None:
        a.final_notes = final_notes
    a.version += 1
    await db.commit()
    await db.refresh(a)
    cv_id = await _cv_id_for_round(db, a.round_id)
    if cv_id is not None:
        await recompute_manager_score(db, tenant_id, cv_id)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment.submit",
        entity_type="assessment",
        entity_id=a.id,
    )
    return await _assessment_to_dict(db, a)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def recompute_manager_score(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> None:
    """Recompute ``candidate_vacancies.manager_score`` for one CV.

    Picks the last round (by created_at) whose status is ``complete``;
    if none is complete, falls back to the last round with any scored
    competences. The CV's snapshot scale weights determine the
    normalized weight; ``manager_score`` itself is the rounded mean of
    ``score_value`` levels across all evaluators / competences in the
    chosen round.
    """

    cv = await db.get(CandidateVacancy, cv_id)
    if cv is None or cv.tenant_id != tenant_id:
        return

    rounds_result = await db.execute(
        select(AssessmentRound)
        .where(
            AssessmentRound.candidate_vacancy_id == cv_id,
            AssessmentRound.tenant_id == tenant_id,
            AssessmentRound.archived_at.is_(None),
        )
        .order_by(AssessmentRound.created_at)
    )
    rounds = rounds_result.scalars().all()
    if not rounds:
        cv.manager_score = None
        cv.manager_score_weight = None
        cv.manager_score_source_round_id = None
        cv.manager_score_updated_at = datetime.now(timezone.utc)
        await db.commit()
        return

    complete = [r for r in rounds if r.status == "complete"]
    candidates = complete or rounds
    chosen: AssessmentRound | None = None
    chosen_avg: float | None = None
    for r in reversed(candidates):
        avg = await _round_average(db, r.id)
        if avg is not None:
            chosen = r
            chosen_avg = avg
            break
    if chosen is None or chosen_avg is None:
        cv.manager_score = None
        cv.manager_score_weight = None
        cv.manager_score_source_round_id = None
        cv.manager_score_updated_at = datetime.now(timezone.utc)
        await db.commit()
        return
    cv.manager_score = float(chosen_avg)
    cv.manager_score_source_round_id = chosen.id
    cv.manager_score_updated_at = datetime.now(timezone.utc)
    # convert avg level → weight via vacancy snapshot
    vacancy = await db.get(Vacancy, cv.vacancy_id)
    snapshot = vacancy.assessment_scale_snapshot if vacancy else None
    cv.manager_score_weight = _level_to_weight(snapshot, chosen_avg)
    await db.commit()


async def round_aggregate(
    db: AsyncSession, tenant_id: uuid.UUID, round_id: uuid.UUID
) -> dict[str, Any]:
    rd = await _load_round(db, tenant_id, round_id)
    a_result = await db.execute(
        select(RecruitmentAssessment).where(
            RecruitmentAssessment.round_id == rd.id,
            RecruitmentAssessment.tenant_id == tenant_id,
        )
    )
    assessments = a_result.scalars().all()
    by_competence: dict[str, list[tuple[int, str]]] = {}
    for a in assessments:
        scores_result = await db.execute(
            select(AssessmentCompetenceScore).where(
                AssessmentCompetenceScore.assessment_id == a.id,
                AssessmentCompetenceScore.score_value.is_not(None),
            )
        )
        for sc in scores_result.scalars().all():
            evaluator_label = a.evaluator_display_name or (
                f"user:{a.evaluator_user_id}"
                if a.evaluator_user_id
                else f"invited:{a.evaluator_invite_id}"
            )
            assert sc.score_value is not None
            by_competence.setdefault(str(sc.competence_id), []).append(
                (sc.score_value, evaluator_label)
            )
    # threshold from scale snapshot or vacancy default
    cv = await db.get(CandidateVacancy, rd.candidate_vacancy_id)
    vacancy = await db.get(Vacancy, cv.vacancy_id) if cv else None
    threshold = 2
    if vacancy and vacancy.assessment_scale_snapshot:
        threshold = vacancy.assessment_scale_snapshot.get("divergence_threshold", 2)
    competences = []
    for cid, entries in by_competence.items():
        scores = [e[0] for e in entries]
        avg = round(sum(scores) / len(scores), 2)
        spread = max(scores) - min(scores)
        competences.append(
            {
                "competence_id": cid,
                "average": avg,
                "min": min(scores),
                "max": max(scores),
                "diverges": spread >= threshold,
                "scorers": [{"evaluator": e[1], "score": e[0]} for e in entries],
            }
        )
    overall = await _round_average(db, rd.id)
    return {
        "round_id": rd.id,
        "average": overall,
        "competences": competences,
        "divergence_threshold": threshold,
    }


# ---------------------------------------------------------------------------
# Manager-assessment invites (public flow)
# ---------------------------------------------------------------------------


async def list_vacancy_profile_competences(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return the vacancy profile's competence list (empty when no profile).

    Entries are whitelisted to the fields the evaluation sheet needs —
    ``profile_data`` also carries salary and other recruiter-only blocks
    that must never leak through the public token endpoint.
    """
    result = await db.execute(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )
    profile = result.scalar_one_or_none()
    raw = (profile.profile_data or {}).get("competences") if profile else None
    if not isinstance(raw, list):
        return []
    competences: list[dict[str, Any]] = []
    for comp in raw:
        if not isinstance(comp, dict):
            continue
        if not (comp.get("id") or comp.get("name")):
            continue
        competences.append(
            {
                "id": comp.get("id"),
                "name": comp.get("name"),
                "criticality": comp.get("criticality"),
                "indicators": comp.get("indicators") or [],
            }
        )
    return competences


async def create_invites(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    cv_id: uuid.UUID,
    payload: ManagerAssessmentInviteCreate,
) -> list[dict[str, Any]]:
    cv = await _load_cv(db, tenant_id, cv_id)
    round_id = payload.round_id
    rd: AssessmentRound | None = None
    if round_id is not None:
        rd = await _load_round(db, tenant_id, round_id)
        if rd.candidate_vacancy_id != cv.id:
            raise AppError(
                "round_id_candidate_vacancy_mismatch", status.HTTP_400_BAD_REQUEST
            )
        if rd.type == "pre_interview":
            # HRP-369: refuse upfront instead of letting the evaluator
            # discover the occupied slot at consent time. A live invite
            # (submitted, or active and unexpired) also holds the slot;
            # expired/revoked/declined ones can be replaced.
            if len(payload.invitees) > 1:
                raise AppError(
                    "pre_interview_single_evaluator", status.HTTP_409_CONFLICT
                )
            await _assert_pre_interview_slot_free(db, rd)
            live_invite = await db.execute(
                select(AssessmentInvite.id).where(
                    AssessmentInvite.round_id == rd.id,
                    or_(
                        AssessmentInvite.status == "submitted",
                        and_(
                            AssessmentInvite.status.in_(INVITE_ACTIVE_STATUSES),
                            AssessmentInvite.expires_at > datetime.now(timezone.utc),
                        ),
                    ),
                )
            )
            if live_invite.first() is not None:
                raise AppError(
                    "pre_interview_single_evaluator", status.HTTP_409_CONFLICT
                )
    # HRP-352: an invite without a filled vacancy profile would land the
    # evaluator on an empty sheet — refuse upfront with an actionable error.
    if not await list_vacancy_profile_competences(db, tenant_id, cv.vacancy_id):
        raise AppError("vacancy_profile_no_competences", status.HTTP_400_BAD_REQUEST)
    expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

    candidate = await db.get(Candidate, cv.candidate_id)
    vacancy = await db.get(Vacancy, cv.vacancy_id)
    vacancy_title = vacancy.title if vacancy else None

    # i18n F4: invitees are external evaluators without an account, so
    # every invite email of this batch uses the tenant default locale.
    from app.core.i18n import resolve_locale, translate
    from app.modules.company.models import Tenant

    tenant = await db.get(Tenant, tenant_id)
    locale = resolve_locale(tenant_default=tenant.default_locale if tenant else None)
    candidate_name = candidate_display_name(
        candidate, fallback=translate("email.fallback.unnamed", locale)
    )

    results: list[dict[str, Any]] = []
    for invitee in payload.invitees:
        token, token_h = issue_token()
        invite = AssessmentInvite(
            tenant_id=tenant_id,
            candidate_vacancy_id=cv.id,
            token=token,
            token_hash=token_h,
            email=invitee.email,
            evaluator_name=invitee.name,
            status="pending",
            expires_at=expires_at,
            round_id=rd.id if rd is not None else None,
            allow_reediting=payload.allow_reediting,
            personal_message=payload.personal_message,
            delivery_status="queued",
            invited_by=user_id,
        )
        db.add(invite)
        await db.flush()

        try:
            from app.core.email import enqueue_email
            from app.core.email_templates import (
                render_manager_assessment_invite_email,
            )

            # HRP-351: the subject/body must name the candidate being
            # evaluated (not the evaluator) and carry the personal message.
            subject, html_body = render_manager_assessment_invite_email(
                token,
                candidate_name,
                vacancy_title,
                evaluator_name=invitee.name,
                personal_message=payload.personal_message,
                expires_in_days=payload.expires_in_days,
                locale=locale,
            )
            enqueue_email(
                invitee.email,
                subject,
                html_body,
                tenant_id=str(tenant_id),
                template_code="recruitment.assessment_invite",
            )
            invite.delivery_status = "sent"
        except Exception:
            log.exception("Failed to enqueue recruitment invite email for cv=%s", cv_id)
            invite.delivery_status = "delivery_failed"
            invite.delivery_error = "Email backend rejected the send"

        await db.commit()
        await db.refresh(invite)
        await audit_service.record_event(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="assessment_invite.create",
            entity_type="assessment_invite",
            entity_id=invite.id,
            payload_diff={
                "email": invitee.email,
                "round_id": str(rd.id) if rd else None,
            },
        )
        results.append(_invite_to_dict(invite))
    return results


async def list_manager_invites(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
) -> list[dict[str, Any]]:
    await _load_cv(db, tenant_id, cv_id)
    result = await db.execute(
        select(AssessmentInvite)
        .where(
            AssessmentInvite.candidate_vacancy_id == cv_id,
            AssessmentInvite.tenant_id == tenant_id,
        )
        .order_by(AssessmentInvite.created_at)
    )
    return [_invite_to_dict(inv) for inv in result.scalars().all()]


async def revoke_invite(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    invite_id: uuid.UUID,
) -> dict[str, Any]:
    inv = await _load_invite(db, tenant_id, invite_id)
    if inv.revoked_at is not None:
        return _invite_to_dict(inv)
    inv.revoked_at = datetime.now(timezone.utc)
    inv.revoked_by = user_id
    inv.status = "revoked"
    await db.commit()
    await db.refresh(inv)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_invite.revoke",
        entity_type="assessment_invite",
        entity_id=inv.id,
    )
    return _invite_to_dict(inv)


async def extend_invite(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    invite_id: uuid.UUID,
    additional_days: int,
) -> dict[str, Any]:
    inv = await _load_invite(db, tenant_id, invite_id)
    # HRP-359: declined is terminal — the token is dead, so extending the
    # expiry would silently succeed while the link stays invalid forever.
    if inv.revoked_at is not None or inv.status in ("submitted", "declined"):
        raise AppError("invite_extend_terminal_status", status.HTTP_409_CONFLICT)
    new_exp = inv.expires_at + timedelta(days=additional_days)
    # Cap at 30 days from creation.
    max_exp = inv.created_at + timedelta(days=30)
    if new_exp > max_exp:
        new_exp = max_exp
    inv.expires_at = new_exp
    if inv.status == "expired":
        inv.status = "pending"
    await db.commit()
    await db.refresh(inv)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assessment_invite.extend",
        entity_type="assessment_invite",
        entity_id=inv.id,
        payload_diff={"new_expires_at": new_exp.isoformat()},
    )
    return _invite_to_dict(inv)


# ---------------------------------------------------------------------------
# Helpers — internal
# ---------------------------------------------------------------------------


async def _load_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> AssessmentScale:
    scale = await db.get(AssessmentScale, scale_id)
    if scale is None or scale.tenant_id != tenant_id:
        raise AppError("scale_not_found", status.HTTP_404_NOT_FOUND)
    return scale


async def _scale_to_dict(db: AsyncSession, scale: AssessmentScale) -> dict[str, Any]:
    lvl_result = await db.execute(
        select(AssessmentScaleLevel)
        .where(AssessmentScaleLevel.scale_id == scale.id)
        .order_by(AssessmentScaleLevel.sort_order, AssessmentScaleLevel.value)
    )
    levels = [
        {
            "id": lvl.id,
            "value": lvl.value,
            "label": lvl.label,
            "description": lvl.description,
            "weight": lvl.weight,
            "color": lvl.color,
            "sort_order": lvl.sort_order,
        }
        for lvl in lvl_result.scalars().all()
    ]
    return {
        "id": scale.id,
        "tenant_id": scale.tenant_id,
        "name": scale.name,
        "description": scale.description,
        "is_default": scale.is_default,
        "archived_at": scale.archived_at,
        "divergence_threshold": scale.divergence_threshold,
        "version": scale.version,
        "created_at": scale.created_at,
        "updated_at": scale.updated_at,
        "levels": levels,
    }


async def _clear_default(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    except_id: uuid.UUID | None = None,
) -> None:
    result = await db.execute(
        select(AssessmentScale).where(
            AssessmentScale.tenant_id == tenant_id,
            AssessmentScale.is_default.is_(True),
        )
    )
    for scale in result.scalars().all():
        if except_id is not None and scale.id == except_id:
            continue
        scale.is_default = False


async def _scale_in_use(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(Vacancy.id).where(
            Vacancy.tenant_id == tenant_id,
            Vacancy.assessment_scale_id == scale_id,
            Vacancy.assessment_scale_snapshot.is_not(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def _load_vacancy(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> Vacancy:
    v = await db.get(Vacancy, vacancy_id)
    if v is None or v.tenant_id != tenant_id:
        raise AppError("vacancy_not_found", status.HTTP_404_NOT_FOUND)
    return v


async def _load_cv(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> CandidateVacancy:
    cv = await db.get(CandidateVacancy, cv_id)
    if cv is None or cv.tenant_id != tenant_id:
        raise AppError("candidate_vacancy_not_found", status.HTTP_404_NOT_FOUND)
    return cv


async def _load_round(
    db: AsyncSession, tenant_id: uuid.UUID, round_id: uuid.UUID
) -> AssessmentRound:
    rd = await db.get(AssessmentRound, round_id)
    if rd is None or rd.tenant_id != tenant_id:
        raise AppError("assessment_round_not_found", status.HTTP_404_NOT_FOUND)
    return rd


async def _load_assessment(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> RecruitmentAssessment:
    a = await db.get(RecruitmentAssessment, assessment_id)
    if a is None or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    return a


async def _load_invite(
    db: AsyncSession, tenant_id: uuid.UUID, invite_id: uuid.UUID
) -> AssessmentInvite:
    inv = await db.get(AssessmentInvite, invite_id)
    if inv is None or inv.tenant_id != tenant_id:
        raise AppError("invite_not_found", status.HTTP_404_NOT_FOUND)
    return inv


async def _cv_id_for_round(db: AsyncSession, round_id: uuid.UUID) -> uuid.UUID | None:
    rd = await db.get(AssessmentRound, round_id)
    if rd is None:
        return None
    return rd.candidate_vacancy_id


async def _round_to_dict(db: AsyncSession, rd: AssessmentRound) -> dict[str, Any]:
    evaluators_result = await db.execute(
        select(AssessmentRoundEvaluator).where(
            AssessmentRoundEvaluator.round_id == rd.id
        )
    )
    evaluators = evaluators_result.scalars().all()
    invite_evals_result = await db.execute(
        select(AssessmentInvite).where(AssessmentInvite.round_id == rd.id)
    )
    invites = invite_evals_result.scalars().all()
    return {
        "id": rd.id,
        "tenant_id": rd.tenant_id,
        "candidate_vacancy_id": rd.candidate_vacancy_id,
        "type": rd.type,
        "round_number": rd.round_number,
        "status": rd.status,
        "created_by": rd.created_by,
        "completed_at": rd.completed_at,
        "archived_at": rd.archived_at,
        "archived_reason": rd.archived_reason,
        "created_at": rd.created_at,
        "updated_at": rd.updated_at,
        "evaluators": [
            {"user_id": ev.user_id, "invited_at": ev.invited_at} for ev in evaluators
        ],
        "invites": [_invite_to_dict(inv) for inv in invites],
    }


async def _assessment_to_dict(
    db: AsyncSession, a: RecruitmentAssessment
) -> dict[str, Any]:
    # Refresh so any prior commit-driven expire doesn't trigger a
    # synchronous lazy reload mid-render.
    await db.refresh(a)
    c_result = await db.execute(
        select(AssessmentCompetenceScore).where(
            AssessmentCompetenceScore.assessment_id == a.id
        )
    )
    competences = [_competence_score_to_dict(c) for c in c_result.scalars().all()]
    i_result = await db.execute(
        select(AssessmentIndicatorScore).where(
            AssessmentIndicatorScore.assessment_id == a.id
        )
    )
    indicators = [_indicator_score_to_dict(i) for i in i_result.scalars().all()]
    return {
        "id": a.id,
        "round_id": a.round_id,
        "evaluator_type": a.evaluator_type,
        "evaluator_user_id": a.evaluator_user_id,
        "evaluator_invite_id": a.evaluator_invite_id,
        "evaluator_display_name": a.evaluator_display_name,
        "status": a.status,
        "submitted_at": a.submitted_at,
        "final_notes": a.final_notes,
        "version": a.version,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "competence_scores": competences,
        "indicator_scores": indicators,
    }


def _competence_score_to_dict(
    row: AssessmentCompetenceScore,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "assessment_id": row.assessment_id,
        "competence_id": row.competence_id,
        "score_value": row.score_value,
        "score_source": row.score_source,
        "comment": row.comment,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _indicator_score_to_dict(
    row: AssessmentIndicatorScore,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "assessment_id": row.assessment_id,
        "indicator_id": row.indicator_id,
        "competence_id": row.competence_id,
        "score_value": row.score_value,
        "comment": row.comment,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


#: Statuses a live invite can hold before the terminal ones
#: (``submitted`` / ``declined`` / ``revoked`` / ``expired``).
INVITE_ACTIVE_STATUSES = ("pending", "opened", "in_progress")


def effective_invite_status(inv: AssessmentInvite) -> str:
    """Invite status with expiry derived at read time (HRP-358).

    The stored status flips to ``expired`` lazily on a token resolve, but
    the recruiter-facing list must show ``expired`` even when the evaluator
    never clicked the link after the deadline.
    """
    if inv.status in INVITE_ACTIVE_STATUSES and inv.expires_at < datetime.now(
        timezone.utc
    ):
        return "expired"
    return inv.status


def _invite_to_dict(inv: AssessmentInvite) -> dict[str, Any]:
    return {
        "id": inv.id,
        "candidate_vacancy_id": inv.candidate_vacancy_id,
        "round_id": inv.round_id,
        "email": inv.email,
        "evaluator_name": inv.evaluator_name,
        "status": effective_invite_status(inv),
        "allow_reediting": inv.allow_reediting,
        "expires_at": inv.expires_at,
        "opened_at": inv.opened_at,
        "submitted_at": inv.submitted_at,
        "declined_at": inv.declined_at,
        "revoked_at": inv.revoked_at,
        "delivery_status": inv.delivery_status,
        "delivery_error": inv.delivery_error,
        "delivery_retry_count": inv.delivery_retry_count,
        "created_at": inv.created_at,
    }


async def _round_average(db: AsyncSession, round_id: uuid.UUID) -> float | None:
    result = await db.execute(
        select(AssessmentCompetenceScore.score_value)
        .join(
            RecruitmentAssessment,
            RecruitmentAssessment.id == AssessmentCompetenceScore.assessment_id,
        )
        .where(
            RecruitmentAssessment.round_id == round_id,
            AssessmentCompetenceScore.score_value.is_not(None),
        )
    )
    scores = [s for s in result.scalars().all() if s is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _level_to_weight(snapshot: dict[str, Any] | None, level: float) -> float | None:
    if snapshot is None:
        return None
    levels = snapshot.get("levels", [])
    if not levels:
        return None
    nearest = min(
        levels,
        key=lambda lvl: abs(float(lvl.get("value", 0)) - level),
    )
    return float(nearest.get("weight", 0))


__all__ = [
    "ensure_default_scale",
    "list_scales",
    "get_scale",
    "create_scale",
    "update_scale",
    "archive_scale",
    "delete_scale",
    "set_vacancy_scale",
    "list_rounds",
    "create_round",
    "update_round_status",
    "add_evaluator",
    "get_or_create_assessment",
    "list_assessments_for_round",
    "get_assessment",
    "set_competence_score",
    "set_indicator_score",
    "submit_assessment",
    "recompute_manager_score",
    "round_aggregate",
    "create_invites",
    "list_manager_invites",
    "revoke_invite",
    "extend_invite",
    "hash_token",
    "issue_token",
    "list_vacancy_profile_competences",
    "effective_invite_status",
    "INVITE_ACTIVE_STATUSES",
]
