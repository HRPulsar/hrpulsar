"""Answer-scale utilities and CRUD, split out of ``assessment.service``.

Leaf module: depends only on ``assessment.models`` and SQLAlchemy, never on
the rest of the assessment service. This lets both ``assessment.service`` and
``assessment.breakdown_service`` reuse ``_load_scale_full`` / ``_scale_detail_dict``
without an import cycle. Public CRUD functions are re-exported from
``assessment.service`` so router/call sites keep their existing import path.

Assessment-lifecycle scale wiring (``set_assessment_scale`` / ``set_group_scale``)
stays in ``assessment.service`` because it calls back into the assessment detail
builders.
"""

import uuid
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    Assessment,
)


async def list_scales(db: AsyncSession, tenant_id: uuid.UUID) -> list:
    result = await db.execute(
        select(AnswerScale)
        .options(
            selectinload(AnswerScale.options),
            selectinload(AnswerScale.levels),
        )
        .where(
            or_(AnswerScale.tenant_id == tenant_id, AnswerScale.tenant_id.is_(None)),
            AnswerScale.deleted_at.is_(None),
            AnswerScale.is_snapshot.is_(False),
        )
    )
    return list(result.scalars().all())


# --- Custom answer scale CRUD ---


def _validate_options_payload(options: list) -> None:
    """Enforce 2..10 non-neutral options + at most 1 neutral option."""
    neutral_count = sum(1 for o in options if o.is_neutral)
    non_neutral_count = len(options) - neutral_count
    if neutral_count > 1:
        raise AppError(
            "answer_scale_one_neutral_only",
            status.HTTP_400_BAD_REQUEST,
        )
    if non_neutral_count < 2:
        raise AppError(
            "answer_scale_min_two_options",
            status.HTTP_400_BAD_REQUEST,
        )
    if non_neutral_count > 10:
        raise AppError(
            "answer_scale_max_ten_options",
            status.HTTP_400_BAD_REQUEST,
        )


def _validate_levels_payload(levels: list) -> None:
    """Enforce coverage of [0..100] without overlap when levels are provided."""
    if not levels:
        return
    if len(levels) > 100:
        raise AppError(
            "answer_scale_max_levels",
            status.HTTP_400_BAD_REQUEST,
        )
    for lvl in levels:
        if lvl.percent_from > lvl.percent_to:
            raise AppError(
                "answer_scale_level_range_invalid",
                status.HTTP_400_BAD_REQUEST,
            )
    ordered = sorted(levels, key=lambda lv: (lv.sort_index, lv.percent_from))
    if ordered[0].percent_from != 0:
        raise AppError(
            "answer_scale_first_level_start",
            status.HTTP_400_BAD_REQUEST,
        )
    if ordered[-1].percent_to != 100:
        raise AppError(
            "answer_scale_last_level_end",
            status.HTTP_400_BAD_REQUEST,
        )
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if cur.percent_from != prev.percent_to + 1:
            raise AppError(
                "answer_scale_levels_must_cover_range",
                status.HTTP_400_BAD_REQUEST,
            )


async def _scale_detail_dict(db: AsyncSession, scale: AnswerScale) -> dict:
    """Serialize a fully loaded scale (options + levels) into the read shape."""
    return {
        "id": scale.id,
        "title": scale.title,
        "description": scale.description,
        "i18n_key": scale.i18n_key,
        "tenant_id": scale.tenant_id,
        "is_default": scale.is_default,
        "is_snapshot": scale.is_snapshot,
        "deleted_at": scale.deleted_at,
        "options": [
            {
                "id": o.id,
                "title": o.title,
                "code": o.code,
                "weight": o.weight,
                "description": o.description,
                "sort_index": o.sort_index,
                "is_neutral": o.is_neutral,
            }
            for o in scale.options
        ],
        "levels": [
            {
                "id": lv.id,
                "percent_from": lv.percent_from,
                "percent_to": lv.percent_to,
                # HRP-479: system_code was dropped here (and the frontend
                # label shim collapsed origin levels — whose system_title
                # is NULL — to an empty string).
                "system_code": lv.system_code,
                "system_title": lv.system_title,
                "description": lv.description,
                "sort_index": lv.sort_index,
            }
            for lv in scale.levels
        ],
    }


async def _load_scale_full(db: AsyncSession, scale_id: uuid.UUID) -> AnswerScale | None:
    result = await db.execute(
        select(AnswerScale)
        .options(
            selectinload(AnswerScale.options),
            selectinload(AnswerScale.levels),
        )
        .where(AnswerScale.id == scale_id)
    )
    return result.scalar_one_or_none()


def _build_scoring_options(options: list) -> list[AnswerOption]:
    """Translate input options into ORM rows.

    Sort order: non-neutral options first by sort_index, neutral option last.
    Weights for non-neutral options are assigned by their final position
    (0..N-1). Neutral options have weight=None.
    """
    non_neutral = sorted(
        (o for o in options if not o.is_neutral), key=lambda o: o.sort_index
    )
    neutral = [o for o in options if o.is_neutral]

    rows: list[AnswerOption] = []
    for idx, o in enumerate(non_neutral):
        rows.append(
            AnswerOption(
                title=o.title,
                code=f"opt_{idx}",
                weight=idx,
                description=o.description,
                sort_index=idx,
                is_neutral=False,
            )
        )
    for o in neutral:
        rows.append(
            AnswerOption(
                title=o.title,
                code="neutral",
                weight=None,
                description=o.description,
                sort_index=len(rows),
                is_neutral=True,
            )
        )
    return rows


def _build_levels(levels: list) -> list[AnswerScaleLevel]:
    ordered = sorted(levels, key=lambda lv: (lv.sort_index, lv.percent_from))
    return [
        AnswerScaleLevel(
            percent_from=lv.percent_from,
            percent_to=lv.percent_to,
            system_title=lv.system_title,
            description=lv.description,
            sort_index=idx,
        )
        for idx, lv in enumerate(ordered)
    ]


async def create_answer_scale(db: AsyncSession, tenant_id: uuid.UUID, data) -> dict:
    _validate_options_payload(data.options)
    _validate_levels_payload(data.levels)

    scale = AnswerScale(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        is_default=False,
        is_snapshot=False,
    )
    scale.options = _build_scoring_options(data.options)
    scale.levels = _build_levels(data.levels)
    db.add(scale)
    await db.commit()

    full = await _load_scale_full(db, scale.id)
    assert full is not None
    return await _scale_detail_dict(db, full)


async def update_answer_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scale_id: uuid.UUID,
    data,
) -> dict:
    scale = await _load_scale_full(db, scale_id)
    if (
        scale is None
        or scale.tenant_id != tenant_id
        or scale.is_default
        or scale.is_snapshot
        or scale.deleted_at is not None
    ):
        raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)

    _validate_options_payload(data.options)
    _validate_levels_payload(data.levels)

    scale.title = data.title
    scale.description = data.description
    scale.options = _build_scoring_options(data.options)
    scale.levels = _build_levels(data.levels)
    await db.commit()

    refreshed = await _load_scale_full(db, scale_id)
    assert refreshed is not None
    return await _scale_detail_dict(db, refreshed)


async def delete_answer_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> dict:
    scale = await db.get(AnswerScale, scale_id)
    if (
        scale is None
        or scale.tenant_id != tenant_id
        or scale.is_default
        or scale.is_snapshot
        or scale.deleted_at is not None
    ):
        raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)

    default_result = await db.execute(
        select(AnswerScale).where(
            AnswerScale.tenant_id.is_(None),
            AnswerScale.is_default.is_(True),
            AnswerScale.deleted_at.is_(None),
        )
    )
    default_scale = default_result.scalar_one_or_none()

    drafts_q = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.scale_id == scale_id)
    )
    reassigned = 0
    for a in drafts_q.scalars().all():
        if a.status and a.status.code == "draft":
            a.scale_id = default_scale.id if default_scale else None
            reassigned += 1

    scale.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"deleted": True, "reassigned_drafts": reassigned}


async def get_answer_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> dict:
    """Fetch a scale by id for preview/archive viewing.

    Bypasses the deleted_at filter because callers may need to render a
    scale that was already attached to a finished assessment.
    """
    scale = await _load_scale_full(db, scale_id)
    if scale is None:
        raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)
    if scale.tenant_id is not None and scale.tenant_id != tenant_id:
        raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)
    return await _scale_detail_dict(db, scale)


async def snapshot_scale_for_assessment(
    db: AsyncSession, assessment: Assessment
) -> AnswerScale | None:
    """Freeze the scale referenced by an assessment into a snapshot copy.

    Called when an assessment leaves draft so subsequent edits to the
    original scale don't bleed into a running assessment. Snapshot rows
    have `tenant_id=NULL` and `is_snapshot=true`, so they are invisible
    in the picker but still resolvable for reading answers.
    """
    if assessment.scale_id is None:
        return None
    source = await _load_scale_full(db, assessment.scale_id)
    if source is None or source.is_snapshot:
        return None

    copy = AnswerScale(
        tenant_id=None,
        title=source.title,
        description=source.description,
        i18n_key=source.i18n_key,
        is_default=False,
        is_snapshot=True,
    )
    copy.options = [
        AnswerOption(
            title=o.title,
            code=o.code,
            weight=o.weight,
            description=o.description,
            sort_index=o.sort_index,
            is_neutral=o.is_neutral,
        )
        for o in source.options
    ]
    copy.levels = [
        AnswerScaleLevel(
            percent_from=lv.percent_from,
            percent_to=lv.percent_to,
            system_code=lv.system_code,
            system_title=lv.system_title,
            description=lv.description,
            sort_index=lv.sort_index,
        )
        for lv in source.levels
    ]
    db.add(copy)
    await db.flush()
    assessment.scale_id = copy.id
    return copy
