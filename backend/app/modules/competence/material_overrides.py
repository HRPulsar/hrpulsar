"""Per-(material × specialization) overrides for PDP material delivery.

Two-level material model (POS7). Result for an employee with specialization
S in the context of competence C:

    materials_for_pdp(C, S) =
        base_materials(C)
        \\ {m : override(m, S, mode='hide')}
        ∪ {m : override(m, S, mode='add')}

* `mode='hide'` removes a base material from PDPs of employees with
  specialization S, while keeping it visible for everyone else.
* `mode='add'` reveals a competence material only for employees with
  specialization S. The material itself lives on the competence
  (so deleting the override restores hidden-by-default behaviour).
"""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.competence.models import (
    Competence,
    Material,
    MaterialSpecializationOverride,
)
from app.modules.dictionary.models import DictionaryItem

ALLOWED_MODES: frozenset[str] = frozenset({"hide", "add"})


async def _load_competence_for_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> Competence:
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    if comp.tenant_id is not None and comp.tenant_id != tenant_id:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    return comp


async def _load_specialization_for_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, specialization_id: uuid.UUID
) -> DictionaryItem:
    spec = await db.get(DictionaryItem, specialization_id)
    if not spec or spec.type != "specialization":
        raise AppError("specialization_not_found", status.HTTP_404_NOT_FOUND)
    if spec.tenant_id is not None and spec.tenant_id != tenant_id:
        raise AppError("specialization_not_found", status.HTTP_404_NOT_FOUND)
    return spec


async def _load_material_for_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    material_id: uuid.UUID,
) -> Material:
    mat = await db.get(Material, material_id)
    if not mat:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    if mat.competence_id != competence_id:
        raise AppError(
            "material_not_in_competence",
            status.HTTP_400_BAD_REQUEST,
        )
    if mat.tenant_id is not None and mat.tenant_id != tenant_id:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    return mat


async def get_materials_for_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    specialization_id: uuid.UUID | None,
) -> list[Material]:
    """Return the effective material set for (competence, specialization).

    Semantics (POS7 plan §2.2):
    - `hide(m, S)` removes a base material from PDPs of S-employees only.
    - `add(m, *)` marks the material as «contextual»: it stops being part of
      the base set, and surfaces only for specializations that own an
      `add(m, S)` row. Without `add` rows the material is plain base.

    When `specialization_id` is None the function returns the **plain** base
    set (no overrides applied) so existing PDP flows for employees without a
    specialization keep working unchanged.
    """
    base_q = await db.execute(
        select(Material)
        .where(
            Material.competence_id == competence_id,
            Material.is_active.is_(True),
            or_(Material.tenant_id == tenant_id, Material.tenant_id.is_(None)),
        )
        .order_by(Material.sort_index)
    )
    base_materials = list(base_q.scalars().all())

    if specialization_id is None:
        return base_materials

    overrides_q = await db.execute(
        select(MaterialSpecializationOverride)
        .join(Material, Material.id == MaterialSpecializationOverride.material_id)
        .where(
            MaterialSpecializationOverride.tenant_id == tenant_id,
            Material.competence_id == competence_id,
        )
    )
    overrides = list(overrides_q.scalars().all())

    hidden_for_spec: set[uuid.UUID] = {
        o.material_id
        for o in overrides
        if o.mode == "hide" and o.specialization_id == specialization_id
    }
    add_for_spec: set[uuid.UUID] = {
        o.material_id
        for o in overrides
        if o.mode == "add" and o.specialization_id == specialization_id
    }
    contextual_materials: set[uuid.UUID] = {
        o.material_id for o in overrides if o.mode == "add"
    }

    visible: list[Material] = [
        m
        for m in base_materials
        if m.id not in hidden_for_spec
        and (m.id not in contextual_materials or m.id in add_for_spec)
    ]

    base_ids: set[uuid.UUID] = {m.id for m in base_materials}
    extra_ids = add_for_spec - base_ids
    if extra_ids:
        extra_q = await db.execute(
            select(Material)
            .where(
                Material.competence_id == competence_id,
                Material.id.in_(extra_ids),
                Material.is_active.is_(True),
                or_(Material.tenant_id == tenant_id, Material.tenant_id.is_(None)),
            )
            .order_by(Material.sort_index)
        )
        visible.extend(extra_q.scalars().all())
    return visible


async def list_overrides(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    specialization_id: uuid.UUID | None = None,
) -> list[MaterialSpecializationOverride]:
    """Override rows for materials owned by this competence."""
    await _load_competence_for_tenant(db, tenant_id, competence_id)

    stmt = (
        select(MaterialSpecializationOverride)
        .join(
            Material,
            Material.id == MaterialSpecializationOverride.material_id,
        )
        .where(
            MaterialSpecializationOverride.tenant_id == tenant_id,
            Material.competence_id == competence_id,
        )
    )
    if specialization_id is not None:
        stmt = stmt.where(
            MaterialSpecializationOverride.specialization_id == specialization_id
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def add_material_override(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    material_id: uuid.UUID,
    specialization_id: uuid.UUID,
    mode: str,
) -> MaterialSpecializationOverride:
    if mode not in ALLOWED_MODES:
        raise AppError(
            "material_override_invalid_mode",
            status.HTTP_400_BAD_REQUEST,
            mode=mode,
        )

    await _load_competence_for_tenant(db, tenant_id, competence_id)
    await _load_specialization_for_tenant(db, tenant_id, specialization_id)
    await _load_material_for_competence(db, tenant_id, competence_id, material_id)

    existing_q = await db.execute(
        select(MaterialSpecializationOverride).where(
            MaterialSpecializationOverride.tenant_id == tenant_id,
            MaterialSpecializationOverride.material_id == material_id,
            MaterialSpecializationOverride.specialization_id == specialization_id,
            MaterialSpecializationOverride.mode == mode,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        return existing

    override = MaterialSpecializationOverride(
        tenant_id=tenant_id,
        material_id=material_id,
        specialization_id=specialization_id,
        mode=mode,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


async def remove_material_override(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    override_id: uuid.UUID,
) -> None:
    await _load_competence_for_tenant(db, tenant_id, competence_id)

    override = await db.get(MaterialSpecializationOverride, override_id)
    if override is None or override.tenant_id != tenant_id:
        raise AppError("material_override_not_found", status.HTTP_404_NOT_FOUND)

    material = await db.get(Material, override.material_id)
    if material is None or material.competence_id != competence_id:
        raise AppError("material_override_not_found", status.HTTP_404_NOT_FOUND)

    await db.delete(override)
    await db.commit()
