"""Reference data loaded once from migration-seeded tables."""

from sqlalchemy import select

from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import Role
from app.modules.competence.models import SkillLevel
from app.modules.dictionary.models import DictionaryItem


async def fetch_ref_data(db):
    """Fetch system reference data seeded by migrations."""
    roles_q = (
        (await db.execute(select(Role).where(Role.is_system == True)))  # noqa: E712
        .scalars()
        .all()
    )
    role_map = {r.code: r for r in roles_q}

    statuses_q = (await db.execute(select(AssessmentStatus))).scalars().all()
    status_map = {s.code: s for s in statuses_q}

    types_q = (await db.execute(select(AssessmentType))).scalars().all()
    type_map = {t.code: t for t in types_q}

    default_scale = (
        await db.execute(
            select(AnswerScale).where(AnswerScale.is_default == True)  # noqa: E712
        )
    ).scalar_one_or_none()

    # Validate that seed migration data is intact
    missing = []
    for code in ("admin", "manager", "employee"):
        if code not in role_map:
            missing.append(f"role '{code}'")
    if not statuses_q:
        missing.append("assessment_statuses")
    if not types_q:
        missing.append("assessment_types")
    if not default_scale:
        missing.append("default answer_scale")
    if missing:
        raise RuntimeError(
            f"Reference data missing: {', '.join(missing)}. "
            f"Seed migrations may not have been applied. "
            f"Run: make migrate"
        )
    scale_options = (
        (
            await db.execute(
                select(AnswerOption)
                .where(AnswerOption.scale_id == default_scale.id)
                .order_by(AnswerOption.sort_index)
            )
        )
        .scalars()
        .all()
    )

    dict_items_q = (
        (
            await db.execute(
                select(DictionaryItem).where(DictionaryItem.tenant_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    grades = {d.title: d for d in dict_items_q if d.type == "grade"}
    specializations = {d.title: d for d in dict_items_q if d.type == "specialization"}
    comp_types = {d.title: d for d in dict_items_q if d.type == "competence_type"}

    skill_levels_q = (
        (await db.execute(select(SkillLevel).order_by(SkillLevel.sort_index)))
        .scalars()
        .all()
    )
    skill_levels = {sl.title: sl for sl in skill_levels_q}

    return {
        "role_map": role_map,
        "status_map": status_map,
        "type_map": type_map,
        "default_scale": default_scale,
        "scale_options": scale_options,
        "grades": grades,
        "specializations": specializations,
        "comp_types": comp_types,
        "skill_levels": skill_levels,
    }
