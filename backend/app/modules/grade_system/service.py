import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.company.models import SpecializationDivision
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.grade_system.schemas import (
    GradeCompetenceLinkCreate,
    GradeSpecializationCreate,
    GradeSpecializationUpdate,
)


def _chain_to_dict(gs: GradeSpecialization) -> dict:
    return {
        "id": gs.id,
        "grade_id": gs.grade_id,
        "grade_title": gs.grade.title if gs.grade else "",
        "specialization_id": gs.specialization_id,
        "description": gs.description,
        "requirements": gs.requirements,
        "salary_min": gs.salary_min,
        "salary_max": gs.salary_max,
        "salary_currency": gs.salary_currency,
        "sort_index": gs.sort_index,
        "passing_score": gs.passing_score,
        "tenant_id": gs.tenant_id,
        "created_at": gs.created_at,
        "competence_links": [
            {
                "id": link.id,
                "competence_id": link.competence_id,
                "competence_title": link.competence.title if link.competence else None,
                "skill_level_id": link.skill_level_id,
                "skill_level_title": (
                    link.skill_level.title if link.skill_level else None
                ),
            }
            for link in gs.competence_links
        ],
    }


async def list_by_specialization(
    db: AsyncSession, tenant_id: uuid.UUID, specialization_id: uuid.UUID
) -> list[dict]:
    result = await db.execute(
        select(GradeSpecialization)
        .options(selectinload(GradeSpecialization.competence_links))
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
        .order_by(GradeSpecialization.sort_index)
    )
    return [_chain_to_dict(gs) for gs in result.scalars().all()]


async def list_grades_for_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    *,
    include_id: uuid.UUID | None = None,
) -> list[dict]:
    """Grade options configured for a specialization (HRP-293).

    Unlike the assessment criteria variant this does NOT require a
    competence link — any configured chain qualifies. Grades deactivated
    on the Dictionaries → Grades level (tenant-effective, HRP-285/337)
    are dropped; ``include_id`` bypasses only the active filter (HRP-292
    semantics) — a grade outside the specialization's chains is never
    returned, so callers keeping a legacy unchained saved value visible
    must inject it client-side from the stored title.
    """
    from sqlalchemy import ColumnElement

    from app.modules.dictionary.models import DictionaryItem
    from app.modules.dictionary.service import effective_is_active_expr

    sub = (
        select(GradeSpecialization.grade_id)
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
        .distinct()
    )
    active_or_included: ColumnElement[bool] = effective_is_active_expr(tenant_id).is_(
        True
    )
    if include_id is not None:
        active_or_included = active_or_included | (DictionaryItem.id == include_id)
    items_q = (
        select(DictionaryItem)
        .where(
            DictionaryItem.type == "grade",
            DictionaryItem.id.in_(sub),
            active_or_included,
        )
        .order_by(DictionaryItem.sort_index, DictionaryItem.title)
    )
    items = (await db.execute(items_q)).scalars().all()
    return [{"id": d.id, "title": d.title, "i18n_key": d.i18n_key} for d in items]


async def list_by_division(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> list[dict]:
    """GF7: Return grade chains filtered by specializations assigned to a division."""
    spec_result = await db.execute(
        select(SpecializationDivision.specialization_id).where(
            SpecializationDivision.division_id == division_id,
            SpecializationDivision.tenant_id == tenant_id,
        )
    )
    spec_ids = [row[0] for row in spec_result.all()]
    if not spec_ids:
        return []

    result = await db.execute(
        select(GradeSpecialization)
        .options(selectinload(GradeSpecialization.competence_links))
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id.in_(spec_ids),
        )
        .order_by(GradeSpecialization.sort_index)
    )
    return [_chain_to_dict(gs) for gs in result.scalars().all()]


async def create_chain(
    db: AsyncSession, tenant_id: uuid.UUID, data: GradeSpecializationCreate
) -> dict:
    # Check uniqueness
    existing = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.grade_id == data.grade_id,
            GradeSpecialization.specialization_id == data.specialization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise AppError("grade_chain_already_exists", status.HTTP_409_CONFLICT)

    if (
        data.salary_min is not None
        and data.salary_max is not None
        and data.salary_min > data.salary_max
    ):
        raise AppError("salary_min_greater_than_max", status.HTTP_400_BAD_REQUEST)

    gs = GradeSpecialization(
        tenant_id=tenant_id,
        grade_id=data.grade_id,
        specialization_id=data.specialization_id,
        description=data.description,
        requirements=data.requirements,
        salary_min=data.salary_min,
        salary_max=data.salary_max,
        salary_currency=data.salary_currency,
        sort_index=data.sort_index,
        passing_score=data.passing_score,
    )
    db.add(gs)
    await db.flush()

    # Add competence links
    for link_data in data.competence_links:
        link = GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=link_data.competence_id,
            skill_level_id=link_data.skill_level_id,
        )
        db.add(link)

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(GradeSpecialization)
        .options(selectinload(GradeSpecialization.competence_links))
        .where(GradeSpecialization.id == gs.id)
    )
    return _chain_to_dict(result.scalar_one())


async def update_chain(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    chain_id: uuid.UUID,
    data: GradeSpecializationUpdate,
) -> dict:
    gs = await db.get(GradeSpecialization, chain_id)
    if not gs or gs.tenant_id != tenant_id:
        raise AppError("grade_chain_not_found", status.HTTP_404_NOT_FOUND)

    updates = data.model_dump(exclude_unset=True)
    new_min = updates.get("salary_min", gs.salary_min)
    new_max = updates.get("salary_max", gs.salary_max)
    if new_min is not None and new_max is not None and new_min > new_max:
        raise AppError("salary_min_greater_than_max", status.HTTP_400_BAD_REQUEST)

    for field, value in updates.items():
        setattr(gs, field, value)
    await db.commit()

    result = await db.execute(
        select(GradeSpecialization)
        .options(selectinload(GradeSpecialization.competence_links))
        .where(GradeSpecialization.id == gs.id)
    )
    return _chain_to_dict(result.scalar_one())


async def delete_chain(
    db: AsyncSession, tenant_id: uuid.UUID, chain_id: uuid.UUID
) -> None:
    gs = await db.get(GradeSpecialization, chain_id)
    if not gs or gs.tenant_id != tenant_id:
        raise AppError("grade_chain_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(gs)
    await db.commit()


async def add_competence_link(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    chain_id: uuid.UUID,
    data: GradeCompetenceLinkCreate,
) -> dict:
    gs = await db.get(GradeSpecialization, chain_id)
    if not gs or gs.tenant_id != tenant_id:
        raise AppError("grade_chain_not_found", status.HTTP_404_NOT_FOUND)

    link = GradeCompetenceLink(
        grade_specialization_id=chain_id,
        competence_id=data.competence_id,
        skill_level_id=data.skill_level_id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {
        "id": link.id,
        "competence_id": link.competence_id,
        "competence_title": link.competence.title if link.competence else None,
        "skill_level_id": link.skill_level_id,
        "skill_level_title": link.skill_level.title if link.skill_level else None,
    }


async def remove_competence_link(
    db: AsyncSession, tenant_id: uuid.UUID, link_id: uuid.UUID
) -> None:
    link = await db.get(GradeCompetenceLink, link_id)
    if not link:
        raise AppError("grade_competence_link_not_found", status.HTTP_404_NOT_FOUND)

    gs = await db.get(GradeSpecialization, link.grade_specialization_id)
    if not gs or gs.tenant_id != tenant_id:
        raise AppError("grade_competence_link_not_found", status.HTTP_404_NOT_FOUND)

    await db.delete(link)
    await db.commit()
