"""Usage checks for competence tree elements (Phase CR2).

Returns where a given competence / group / indicator / material is referenced
in user-facing services (matrix, employee card, assessment, IDP, talent market).
The PDF spec requires these checks before deactivating, deleting, moving or
unpublishing tree elements.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import (
    PDP,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentResult,
    PDPItem,
    PDPItemMaterial,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
)
from app.modules.employee.models import CourseCompetence, WorkExperienceCompetence
from app.modules.grade_system.models import GradeCompetenceLink
from app.modules.talent_market.models import TalentCardCompetence


@dataclass(frozen=True)
class CompetenceUsage:
    matrix: bool
    employee_card: bool
    assessment: bool
    idp: bool
    talent_market: bool

    @property
    def is_used(self) -> bool:
        return any(
            (
                self.matrix,
                self.employee_card,
                self.assessment,
                self.idp,
                self.talent_market,
            )
        )


@dataclass(frozen=True)
class IndicatorUsage:
    assessment: bool
    idp: bool

    @property
    def is_used(self) -> bool:
        return self.assessment or self.idp


@dataclass(frozen=True)
class MaterialUsage:
    idp: bool

    @property
    def is_used(self) -> bool:
        return self.idp


async def _exists(db: AsyncSession, stmt) -> bool:
    return bool((await db.execute(select(exists(stmt)))).scalar())


async def check_competence_usage(
    db: AsyncSession, competence_id: uuid.UUID
) -> CompetenceUsage:
    """Returns flags showing which user-facing service references this competence."""
    matrix = await _exists(
        db,
        select(GradeCompetenceLink.id).where(
            GradeCompetenceLink.competence_id == competence_id
        ),
    )
    employee_card_we = await _exists(
        db,
        select(WorkExperienceCompetence.id).where(
            WorkExperienceCompetence.competence_id == competence_id
        ),
    )
    employee_card_course = await _exists(
        db,
        select(CourseCompetence.id).where(
            CourseCompetence.competence_id == competence_id
        ),
    )
    assessment_comp = await _exists(
        db,
        select(AssessmentCompetence.id).where(
            AssessmentCompetence.competence_id == competence_id
        ),
    )
    assessment_result = await _exists(
        db,
        select(AssessmentResult.id).where(
            AssessmentResult.competence_id == competence_id
        ),
    )
    idp = await _exists(
        db,
        select(PDPItem.id).where(PDPItem.competence_id == competence_id),
    )
    talent_market = await _exists(
        db,
        select(TalentCardCompetence.id).where(
            TalentCardCompetence.competence_id == competence_id
        ),
    )
    return CompetenceUsage(
        matrix=matrix,
        employee_card=(employee_card_we or employee_card_course),
        assessment=(assessment_comp or assessment_result),
        idp=idp,
        talent_market=talent_market,
    )


async def check_indicator_usage(
    db: AsyncSession, indicator: Indicator
) -> IndicatorUsage:
    """`assessment` = answer references this indicator;
    `idp` = parent competence is referenced by any PDPItem (PDP doesn't link
    to indicators directly, but blocks indicator edits on the parent
    competence per PM spec)."""
    assessment = await _exists(
        db,
        select(AssessmentAnswer.id).where(
            AssessmentAnswer.indicator_id == indicator.id
        ),
    )
    idp = await _exists(
        db,
        select(PDPItem.id).where(PDPItem.competence_id == indicator.competence_id),
    )
    return IndicatorUsage(assessment=assessment, idp=idp)


async def check_material_usage(
    db: AsyncSession, material_id: uuid.UUID
) -> MaterialUsage:
    """Material is referenced when a PDPItemMaterial points to it."""
    idp = await _exists(
        db,
        select(PDPItemMaterial.id).where(PDPItemMaterial.material_id == material_id),
    )
    return MaterialUsage(idp=idp)


async def collect_subtree_competence_ids(
    db: AsyncSession, group_id: uuid.UUID
) -> set[uuid.UUID]:
    """Recursively collect all competence ids belonging to the group or any
    descendant subgroup. Used for group-level usage checks and cascade ops."""
    visited: set[uuid.UUID] = set()
    stack: list[uuid.UUID] = [group_id]
    competence_ids: set[uuid.UUID] = set()

    while stack:
        gid = stack.pop()
        if gid in visited:
            continue
        visited.add(gid)

        comps = await db.execute(
            select(Competence.id).where(Competence.group_id == gid)
        )
        competence_ids.update(comps.scalars().all())

        children = await db.execute(
            select(CompetenceGroup.id).where(CompetenceGroup.parent_id == gid)
        )
        for child_id in children.scalars().all():
            if child_id not in visited:
                stack.append(child_id)

    return competence_ids


async def check_group_usage(db: AsyncSession, group_id: uuid.UUID) -> CompetenceUsage:
    """Aggregate usage flags across the entire subtree (group + descendants)."""
    competence_ids = await collect_subtree_competence_ids(db, group_id)
    if not competence_ids:
        return CompetenceUsage(False, False, False, False, False)

    matrix = await _exists(
        db,
        select(GradeCompetenceLink.id).where(
            GradeCompetenceLink.competence_id.in_(competence_ids)
        ),
    )
    employee_card_we = await _exists(
        db,
        select(WorkExperienceCompetence.id).where(
            WorkExperienceCompetence.competence_id.in_(competence_ids)
        ),
    )
    employee_card_course = await _exists(
        db,
        select(CourseCompetence.id).where(
            CourseCompetence.competence_id.in_(competence_ids)
        ),
    )
    assessment_comp = await _exists(
        db,
        select(AssessmentCompetence.id).where(
            AssessmentCompetence.competence_id.in_(competence_ids)
        ),
    )
    assessment_result = await _exists(
        db,
        select(AssessmentResult.id).where(
            AssessmentResult.competence_id.in_(competence_ids)
        ),
    )
    idp = await _exists(
        db,
        select(PDPItem.id).where(PDPItem.competence_id.in_(competence_ids)),
    )
    talent_market = await _exists(
        db,
        select(TalentCardCompetence.id).where(
            TalentCardCompetence.competence_id.in_(competence_ids)
        ),
    )
    return CompetenceUsage(
        matrix=matrix,
        employee_card=(employee_card_we or employee_card_course),
        assessment=(assessment_comp or assessment_result),
        idp=idp,
        talent_market=talent_market,
    )


async def check_published_descendants(db: AsyncSession, group_id: uuid.UUID) -> bool:
    """True if any client-published competence exists in the subtree.
    Blocker for group deactivation per PM spec: cannot deactivate a group
    that contains published competences."""
    competence_ids = await collect_subtree_competence_ids(db, group_id)
    if not competence_ids:
        return False
    return await _exists(
        db,
        select(Competence.id).where(
            Competence.id.in_(competence_ids), Competence.is_published.is_(True)
        ),
    )


async def check_skill_level_usage(db: AsyncSession, skill_level_id: uuid.UUID) -> bool:
    """Custom skill level can't be deleted while indicators/materials use it."""
    used_by_indicator = await _exists(
        db,
        select(Indicator.id).where(Indicator.skill_level_id == skill_level_id),
    )
    if used_by_indicator:
        return True
    return await _exists(
        db,
        select(Material.id).where(Material.skill_level_id == skill_level_id),
    )


# `PDP` is imported only to trigger SQLAlchemy mapper resolution for
# PDPItem.pdp relationship lookups in tests; silences "unused" linters.
_ = PDP
