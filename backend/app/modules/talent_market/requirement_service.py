"""Talent card requirements: free-text, required specializations and competences.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.competence.models import Competence, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import GradeSpecialization
from app.modules.talent_market.common import _card_to_read, assert_card_not_terminal
from app.modules.talent_market.matching import _auto_populate_candidates
from app.modules.talent_market.models import (
    TalentCard,
    TalentCardCompetence,
    TalentCardRequirement,
    TalentCardSpecialization,
)

logger = logging.getLogger(__name__)


async def add_requirement(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> dict:
    # HRP-291: legacy free-text requirements follow the same Draft-only
    # rule as the structured blocks — the endpoint predates HRP-87 but is
    # still a live mutation path.
    await _get_draft_card(db, tenant_id, card_id)

    req = TalentCardRequirement(
        card_id=card_id,
        description=data.description,
        min_experience_years=data.min_experience_years,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return {
        "id": req.id,
        "description": req.description,
        "min_experience_years": req.min_experience_years,
    }


# ---------------------------------------------------------------------------
# HRP-87 — Required specialization / competence blocks
# ---------------------------------------------------------------------------


async def _get_draft_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> TalentCard:
    """Resolve a card and reject requirement edits outside Draft.

    HRP-291: gate on the status itself, not ``is_published`` — a card
    cancelled straight from Draft never flipped that flag but is just as
    read-only as a published or completed one.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    if card.status != "draft":
        raise AppError(
            "tm_card_requirements_read_only",
            status.HTTP_409_CONFLICT,
            state=card.status,
        )
    return card


async def _validate_spec_grade(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    grade_id: uuid.UUID,
) -> GradeSpecialization:
    """Both ids must exist AND form a configured `GradeSpecialization` pair.

    HRP-87 surfaces grades via `/specializations/{id}/grades`, which returns
    only configured pairs, so a missing pair only happens when the API is
    hit directly with an arbitrary grade id. We reject with 422 instead of
    silently saving a row that can't auto-fill or align with the company's
    ladder.
    """
    spec = await db.get(DictionaryItem, specialization_id)
    if not spec or spec.type != "specialization":
        raise AppError(
            "specialization_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    grade = await db.get(DictionaryItem, grade_id)
    if not grade or grade.type != "grade":
        raise AppError("tm_grade_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if spec.tenant_id is not None and spec.tenant_id != tenant_id:
        raise AppError("specialization_not_found", status.HTTP_404_NOT_FOUND)
    if grade.tenant_id is not None and grade.tenant_id != tenant_id:
        raise AppError("tm_grade_not_found", status.HTTP_404_NOT_FOUND)

    pair = (
        await db.execute(
            select(GradeSpecialization)
            .where(
                GradeSpecialization.tenant_id == tenant_id,
                GradeSpecialization.specialization_id == specialization_id,
                GradeSpecialization.grade_id == grade_id,
            )
            .options(selectinload(GradeSpecialization.competence_links))
        )
    ).scalar_one_or_none()
    if pair is None:
        raise AppError(
            "tm_grade_not_configured_for_specialization",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return pair


async def _pair_competence_keys(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    grade_id: uuid.UUID | None,
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    """(competence, skill level) keys a configured (spec, grade) pair implies.

    Empty when the pair isn't configured in the grade ladder — the card
    can carry such a row (the ladder may have changed underneath it), it
    simply implies nothing.
    """
    pair = (
        await db.execute(
            select(GradeSpecialization)
            .where(
                GradeSpecialization.tenant_id == tenant_id,
                GradeSpecialization.specialization_id == specialization_id,
                GradeSpecialization.grade_id == grade_id,
            )
            .options(selectinload(GradeSpecialization.competence_links))
        )
    ).scalar_one_or_none()
    if pair is None:
        return []
    return [(link.competence_id, link.skill_level_id) for link in pair.competence_links]


async def _recompute_required_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    dropped: tuple[uuid.UUID, uuid.UUID | None] | None = None,
) -> None:
    """HRP-171: keep Required Competences in step with Required Specializations.

    Adds every (competence, skill level) the card's current specs imply
    through their configured ``GradeSpecialization`` links, and removes
    what the ``dropped`` pair — the spec row the caller just deleted or
    re-pointed — used to imply and no remaining spec still does.

    HRP-683: this used to be a full rebuild that deleted every row no
    current pair implied, so any spec edit also wiped competences that
    were never derived from a pair: the ones the recruiter picked by hand
    (HRP-128) and the ones the recruitment bridge copies off a vacancy
    (``post_vacancy_to_talent_market``). Deriving additively, and
    deleting only what the changed pair owned, keeps both sources on the
    card without a "who wrote this row" column. The ConfirmDialog copy
    stays honest — competences are still recomputed from the specs.

    Known ceiling: if the ``dropped`` pair has since been removed from
    the ladder we can't tell what it contributed, so its competences stay
    on the card for the recruiter to delete. Callers that need the
    surrounding ``_auto_populate_candidates`` recompute must invoke it
    themselves; this helper only owns the competence block.
    """
    spec_rows = list(
        (
            await db.execute(
                select(TalentCardSpecialization).where(
                    TalentCardSpecialization.card_id == card_id
                )
            )
        )
        .scalars()
        .all()
    )

    desired: dict[tuple[uuid.UUID, uuid.UUID | None], None] = {}
    for spec in spec_rows:
        for key in await _pair_competence_keys(
            db, tenant_id, spec.specialization_id, spec.grade_id
        ):
            desired[key] = None

    existing_rows = list(
        (
            await db.execute(
                select(TalentCardCompetence).where(
                    TalentCardCompetence.card_id == card_id
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_key = {(r.competence_id, r.skill_level_id): r for r in existing_rows}

    if dropped is not None:
        for key in await _pair_competence_keys(db, tenant_id, *dropped):
            row = existing_by_key.get(key)
            if row is not None and key not in desired:
                await db.delete(row)

    for key in desired:
        if key in existing_by_key:
            continue
        comp_id, sl_id = key
        db.add(
            TalentCardCompetence(
                card_id=card_id,
                competence_id=comp_id,
                skill_level_id=sl_id,
            )
        )

    await db.flush()


async def add_required_specialization(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> dict:
    """Create a Required Specialization row and recompute the competences.

    Behaviour (HRP-87 + HRP-171):

    1. Persist the (specialization, grade, optional min_experience_years) row.
    2. Recompute Required Competences from the union of every current spec's
       configured `GradeSpecialization.competence_links`. The recruiter has
       already confirmed the recompute via the ConfirmDialog on the UI.
    """
    card = await _get_draft_card(db, tenant_id, card_id)
    await _validate_spec_grade(
        db,
        tenant_id=tenant_id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
    )

    spec_row = TalentCardSpecialization(
        card_id=card.id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
        min_experience_years=data.min_experience_years,
    )
    db.add(spec_row)
    await db.flush()

    await _recompute_required_competences(db, tenant_id, card.id)
    await db.commit()
    await db.refresh(spec_row)
    await _auto_populate_candidates(db, tenant_id, card.id)
    return {
        "id": spec_row.id,
        "specialization_id": spec_row.specialization_id,
        "grade_id": spec_row.grade_id,
        "min_experience_years": spec_row.min_experience_years,
    }


async def update_required_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    data,
) -> dict:
    await _get_draft_card(db, tenant_id, card_id)
    row = await db.get(TalentCardSpecialization, link_id)
    if not row or row.card_id != card_id:
        raise AppError("tm_specialization_link_not_found", status.HTTP_404_NOT_FOUND)
    await _validate_spec_grade(
        db,
        tenant_id=tenant_id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
    )
    dropped = (row.specialization_id, row.grade_id)
    row.specialization_id = data.specialization_id
    row.grade_id = data.grade_id
    row.min_experience_years = data.min_experience_years
    await db.flush()
    # HRP-171 REDO 2.1: changing the (spec, grade) pair must also re-derive
    # Required Competences — recruiters are warned about the recompute via
    # the ConfirmDialog before the PATCH lands here. The old pair is what
    # loses its competences (HRP-683); rows from other sources stay.
    await _recompute_required_competences(db, tenant_id, card_id, dropped=dropped)
    await db.commit()
    await db.refresh(row)
    await _auto_populate_candidates(db, tenant_id, card_id)
    return {
        "id": row.id,
        "specialization_id": row.specialization_id,
        "grade_id": row.grade_id,
        "min_experience_years": row.min_experience_years,
    }


async def delete_required_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    link_id: uuid.UUID,
) -> None:
    await _get_draft_card(db, tenant_id, card_id)
    row = await db.get(TalentCardSpecialization, link_id)
    if not row or row.card_id != card_id:
        raise AppError("tm_specialization_link_not_found", status.HTTP_404_NOT_FOUND)
    dropped = (row.specialization_id, row.grade_id)
    await db.delete(row)
    await db.flush()
    # HRP-171 REDO 2.2: dropping a spec drops its derived competences too.
    await _recompute_required_competences(db, tenant_id, card_id, dropped=dropped)
    await db.commit()
    await _auto_populate_candidates(db, tenant_id, card_id)


async def add_required_competences(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> list[dict]:
    """HRP-128: set/replace Required Competences for a card.

    Renamed from the original HRP-87 step-3 "bulk add" semantics — the new
    Change dialog opens pre-checked with the existing selection, so the
    incoming `items` is the *full* desired set:

    * (competence_id, skill_level_id) tuples already on the card stay put;
    * tuples in `items` but not on the card are inserted;
    * tuples on the card but not in `items` are deleted.

    Match% is now card-level (TalentCard.match_percent) — no longer per row.
    """
    card = await _get_draft_card(db, tenant_id, card_id)

    existing_rows = (
        (
            await db.execute(
                select(TalentCardCompetence).where(
                    TalentCardCompetence.card_id == card.id
                )
            )
        )
        .scalars()
        .all()
    )
    existing_index = {(r.competence_id, r.skill_level_id): r for r in existing_rows}
    desired_keys: set[tuple[uuid.UUID, uuid.UUID]] = set()

    out: list[dict] = []
    for item in data.items:
        # Validate competence + skill level exist within tenant scope.
        comp = await db.get(Competence, item.competence_id)
        if not comp or comp.tenant_id != tenant_id:
            raise AppError(
                "tm_competence_id_not_found",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                competence_id=item.competence_id,
            )
        sl = await db.get(SkillLevel, item.skill_level_id)
        if not sl or (sl.tenant_id is not None and sl.tenant_id != tenant_id):
            raise AppError(
                "tm_skill_level_id_not_found",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                skill_level_id=item.skill_level_id,
            )

        key = (item.competence_id, item.skill_level_id)
        desired_keys.add(key)
        if key in existing_index:
            row = existing_index[key]
        else:
            row = TalentCardCompetence(
                card_id=card.id,
                competence_id=item.competence_id,
                skill_level_id=item.skill_level_id,
            )
            db.add(row)
            await db.flush()
            existing_index[key] = row
        out.append(
            {
                "id": row.id,
                "competence_id": row.competence_id,
                "skill_level_id": row.skill_level_id,
                "match_percent": row.match_percent,
            }
        )

    # Drop rows no longer in the desired set (HRP-128 replace semantics).
    for key, row in list(existing_index.items()):
        if key not in desired_keys:
            await db.delete(row)

    await db.commit()
    await _auto_populate_candidates(db, tenant_id, card.id)
    return out


async def update_required_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    data,
) -> dict:
    await _get_draft_card(db, tenant_id, card_id)
    row = await db.get(TalentCardCompetence, link_id)
    if not row or row.card_id != card_id:
        raise AppError("tm_competence_link_not_found", status.HTTP_404_NOT_FOUND)
    comp = await db.get(Competence, data.competence_id)
    if not comp or comp.tenant_id != tenant_id:
        raise AppError("competence_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)
    sl = await db.get(SkillLevel, data.skill_level_id)
    if not sl or (sl.tenant_id is not None and sl.tenant_id != tenant_id):
        raise AppError("skill_level_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)
    row.competence_id = data.competence_id
    row.skill_level_id = data.skill_level_id
    await db.commit()
    await db.refresh(row)
    await _auto_populate_candidates(db, tenant_id, card_id)
    return {
        "id": row.id,
        "competence_id": row.competence_id,
        "skill_level_id": row.skill_level_id,
        "match_percent": row.match_percent,
    }


async def delete_required_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    link_id: uuid.UUID,
) -> None:
    await _get_draft_card(db, tenant_id, card_id)
    row = await db.get(TalentCardCompetence, link_id)
    if not row or row.card_id != card_id:
        raise AppError("tm_competence_link_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(row)
    await db.commit()
    await _auto_populate_candidates(db, tenant_id, card_id)


# ---------------------------------------------------------------------------
# HRP-242 — explicit Candidates recompute
# ---------------------------------------------------------------------------


async def recompute_card_candidates(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> dict:
    """HRP-242: refresh the Candidates auto-pool on demand.

    Triggered from the refresh action in the Candidates block header for
    non-terminal cards. Reuses `_auto_populate_candidates` so the rules
    (appointed rows survive, matched rows that no longer qualify are
    pruned, manual not_matched picks stay) match the silent recompute
    chain. Terminal statuses are rejected — there's nothing to refresh
    on Completed / Cancelled cards.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    # HRP-291: one source of truth for what "terminal" means.
    assert_card_not_terminal(card)
    await _auto_populate_candidates(db, tenant_id, card_id)
    card = await db.get(TalentCard, card_id)
    if card is None:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    return _card_to_read(card)
