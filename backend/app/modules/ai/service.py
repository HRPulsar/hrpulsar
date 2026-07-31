import logging
import uuid

from fastapi import status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, exception_summary
from app.modules.ai import llm_client, prompts
from app.modules.ai.models import Embedding
from app.modules.ai_settings import service as ai_settings_service

logger = logging.getLogger(__name__)


async def generate_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    specialization: str,
    company_description: str = "",
    activity_fields: str = "",
) -> list[dict]:
    """Generate competency framework using LLM."""

    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    prompt = prompts.GENERATE_COMPETENCES.format(
        specialization=specialization,
        company_description=company_description or "Not specified",
        activity_fields=activity_fields or "Not specified",
    )
    try:
        result = await llm_client.generate_json(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
        return result if isinstance(result, list) else [result]  # type: ignore[list-item]
    except Exception as e:
        logger.exception("Failed to generate competences")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )


async def generate_indicators(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    competence_title: str,
    context: str = "",
) -> list[dict]:
    """Generate indicators for a competence using LLM."""

    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    prompt = prompts.GENERATE_INDICATORS.format(
        competence_title=competence_title,
        context=context or "General professional context",
    )
    try:
        result = await llm_client.generate_json(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
        return result if isinstance(result, list) else [result]  # type: ignore[list-item]
    except Exception as e:
        logger.exception("Failed to generate indicators")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )


async def _collect_context_for_pdp(
    db: AsyncSession,
    assessment_id: uuid.UUID,
) -> str:
    """Build the SUGGEST_PDP prompt from assessment results.

    Raises 404 if there are no results — same behaviour as the inline
    flow had before the refactor, so async/sync paths report identically.
    """
    from app.modules.assessment.models import AssessmentResult

    results = await db.execute(
        select(AssessmentResult).where(AssessmentResult.assessment_id == assessment_id)
    )
    all_results = results.scalars().all()

    if not all_results:
        raise AppError("no_assessment_results_found", status.HTTP_404_NOT_FOUND)

    sorted_results = sorted(all_results, key=lambda r: r.avg_score)
    weak = [
        {"competence_id": str(r.competence_id), "score": r.avg_score}
        for r in sorted_results[:5]
    ]
    strong = [
        {"competence_id": str(r.competence_id), "score": r.avg_score}
        for r in sorted_results[-3:]
    ]

    return prompts.SUGGEST_PDP.format(
        weak_competences=str(weak),
        strong_competences=str(strong),
    )


async def suggest_pdp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    assessment_id: uuid.UUID,
) -> list[dict]:
    """Suggest PDP items based on assessment results (sync legacy path)."""
    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    prompt = await _collect_context_for_pdp(db, assessment_id)

    try:
        result = await llm_client.generate_json(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
        return result if isinstance(result, list) else [result]  # type: ignore[list-item]
    except Exception as e:
        logger.exception("Failed to suggest PDP")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )


# --- Position Generation ---


async def _collect_context_for_positions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict:
    """Read all context the position-generation prompt needs.

    Acquires the per-tenant advisory xact-lock so concurrent generations
    don't race on the unique title constraint. Returns a dict with both
    the formatted prompt strings and the lookup maps used during persist.
    """
    from app.modules.company.models import (
        CompanyActivityField,
        Division,
        Tenant,
    )
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.dictionary.service import effective_is_active_expr
    from app.modules.position.models import Position

    # Serialize concurrent generate_positions calls per tenant — prevents two
    # racing executions from violating uq_position_tenant_title. Auto-released
    # at COMMIT. 63-bit key from tenant_id makes collisions practically zero.
    lock_key = int.from_bytes(tenant_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_key))

    tenant = await db.get(Tenant, tenant_id)
    company_desc = (tenant.description or tenant.name) if tenant else "Unknown"
    industry = (tenant.industry or "Not specified") if tenant else "Not specified"
    company_size = (
        (tenant.company_size or "Not specified") if tenant else "Not specified"
    )

    af_result = await db.execute(
        select(CompanyActivityField).where(CompanyActivityField.tenant_id == tenant_id)
    )
    activity_fields = (
        ", ".join(
            af.activity_field.title
            for af in af_result.scalars().all()
            if af.activity_field
        )
        or "Not specified"
    )

    spec_result = await db.execute(
        select(DictionaryItem).where(
            DictionaryItem.type == "specialization",
            effective_is_active_expr(tenant_id).is_(True),
            (DictionaryItem.tenant_id == tenant_id)
            | DictionaryItem.tenant_id.is_(None),
        )
    )
    spec_items = spec_result.scalars().all()
    specializations = ", ".join(s.title for s in spec_items) or "None"
    spec_map = {s.title.lower(): s.id for s in spec_items}

    grade_result = await db.execute(
        select(DictionaryItem).where(
            DictionaryItem.type == "grade",
            effective_is_active_expr(tenant_id).is_(True),
            (DictionaryItem.tenant_id == tenant_id)
            | DictionaryItem.tenant_id.is_(None),
        )
    )
    grade_items = grade_result.scalars().all()
    grades = ", ".join(g.title for g in grade_items) or "None"
    grade_map = {g.title.lower(): g.id for g in grade_items}

    div_result = await db.execute(
        select(Division).where(Division.tenant_id == tenant_id)
    )
    div_items = div_result.scalars().all()
    divisions = ", ".join(d.name for d in div_items) or "None"
    div_map = {d.name.lower(): d.id for d in div_items}

    pos_result = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.source != "ai_draft",
        )
    )
    existing = [p.title for p in pos_result.scalars().all()]
    existing_str = ", ".join(existing) if existing else "None"

    drafts_result = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.source == "ai_draft",
        )
    )
    existing_drafts = {p.title.lower(): p for p in drafts_result.scalars().all()}

    count = max(5, min(15, len(spec_items) * len(grade_items)))

    prompt = prompts.GENERATE_POSITIONS.format(
        company_description=company_desc,
        industry=industry,
        company_size=company_size,
        activity_fields=activity_fields,
        specializations=specializations,
        grades=grades,
        divisions=divisions,
        existing_positions=existing_str,
        count=count,
    )

    return {
        "prompt": prompt,
        "count": count,
        "existing_titles": [t.lower() for t in existing],
        "existing_drafts": existing_drafts,
        "spec_map": spec_map,
        "grade_map": grade_map,
        "div_map": div_map,
    }


async def _persist_positions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    items: list,
    *,
    existing_titles: list[str],
    existing_drafts: dict,
    spec_map: dict,
    grade_map: dict,
    div_map: dict,
) -> list:
    """Apply LLM-generated position items to the DB (upsert + sweep)."""
    from app.modules.position.models import Position

    created = []
    existing_lower = set(existing_titles)
    reused_keys: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "").strip()
        if not title:
            continue
        key = title.lower()
        if key in existing_lower or key in reused_keys:
            continue

        spec_title = item.get("specialization_title")
        grade_title = item.get("grade_title")
        div_name = item.get("division_name")
        description = item.get("description")
        specialization_id = spec_map.get(spec_title.lower()) if spec_title else None
        grade_id = grade_map.get(grade_title.lower()) if grade_title else None
        division_id = div_map.get(div_name.lower()) if div_name else None

        existing_draft = existing_drafts.get(key)
        if existing_draft is not None:
            existing_draft.title = title
            existing_draft.description = description
            existing_draft.specialization_id = specialization_id
            existing_draft.grade_id = grade_id
            existing_draft.division_id = division_id
            created.append(existing_draft)
        else:
            pos = Position(
                tenant_id=tenant_id,
                title=title,
                description=description,
                specialization_id=specialization_id,
                grade_id=grade_id,
                division_id=division_id,
                source="ai_draft",
            )
            db.add(pos)
            created.append(pos)

        reused_keys.add(key)

    # Delete drafts the LLM did not regenerate, then flush so DELETEs precede
    # any remaining INSERTs at commit time (avoids uq_position_tenant_title race)
    for key, draft in existing_drafts.items():
        if key not in reused_keys:
            await db.delete(draft)
    await db.flush()
    return created


async def generate_positions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> list[dict]:
    """Generate position suggestions based on company context.

    Synchronous (blocking) variant — keeps the request handler holding a
    DB connection across the LLM call. The async path through
    `app.modules.ai.tasks.generate_positions_task` is preferred for new
    callers; this remains for the legacy frontend until it's migrated.
    """
    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    ctx = await _collect_context_for_positions(db, tenant_id)

    try:
        result = await llm_client.generate_json(
            ctx["prompt"],
            system=prompts.build_system_position(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
        items = result if isinstance(result, list) else [result]
        items = items[: ctx["count"]]
    except Exception as e:
        logger.exception("Failed to generate positions")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )

    created = await _persist_positions(
        db,
        tenant_id,
        items,
        existing_titles=ctx["existing_titles"],
        existing_drafts=ctx["existing_drafts"],
        spec_map=ctx["spec_map"],
        grade_map=ctx["grade_map"],
        div_map=ctx["div_map"],
    )

    await db.commit()
    for p in created:
        await db.refresh(p)

    from app.modules.position.service import _position_to_read

    return [_position_to_read(p, 0) for p in created]


# --- Vector Search ---


async def create_embedding(
    db: AsyncSession,
    entity_type: str,
    entity_id: uuid.UUID,
    text_content: str,
) -> dict:
    """Generate and store embedding for an entity."""
    vector = await llm_client.get_embedding(text_content)

    # Upsert
    existing = await db.execute(
        select(Embedding).where(
            Embedding.entity_type == entity_type,
            Embedding.entity_id == entity_id,
        )
    )
    emb = existing.scalar_one_or_none()

    if emb:
        emb.text_content = text_content
        emb.embedding = vector
    else:
        emb = Embedding(
            entity_type=entity_type,
            entity_id=entity_id,
            text_content=text_content,
            embedding=vector,
        )
        db.add(emb)

    await db.commit()
    return {"entity_type": entity_type, "entity_id": str(entity_id), "status": "stored"}


async def semantic_search(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    query: str,
    entity_type: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search entities by semantic similarity."""

    query_vector = await llm_client.get_embedding(query)

    # pgvector cosine distance search
    sql = """
        SELECT entity_type, entity_id, text_content,
               1 - (embedding <=> :query_vec::vector) AS similarity
        FROM embeddings
    """
    params = {"query_vec": str(query_vector)}

    if entity_type:
        sql += " WHERE entity_type = :entity_type"
        params["entity_type"] = entity_type

    sql += " ORDER BY embedding <=> :query_vec::vector LIMIT :limit"
    params["limit"] = str(limit)

    result = await db.execute(text(sql), params)

    return [
        {
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id),
            "text_content": row.text_content,
            "similarity": round(float(row.similarity), 4),
        }
        for row in result.fetchall()
    ]
