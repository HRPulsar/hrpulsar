"""Explicit shared state threaded through the seed steps.

``populate_tenant`` used to be a single ~1800-line function holding all of
this as local variables; the step modules now read and extend a
``SeedContext`` instead. Steps run in the order ``populate.populate_tenant``
calls them — each dataclass field notes which step fills it.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    Assessment,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import Role, User
from app.modules.company.models import Division
from app.modules.competence.models import Competence, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee
from app.modules.position.models import Position


@dataclass
class CompetenceHandles:
    """Named references to the competences later steps attach data to.

    ``all_competences`` additionally holds the unnamed ones (Docker,
    CI/CD) in creation order — it is what ``populate_tenant`` returns.
    """

    python: Competence
    js: Competence
    sql: Competence
    api: Competence
    comm: Competence
    written: Competence
    teamwork: Competence
    mentoring: Competence
    decision: Competence
    planning: Competence
    all_competences: list[Competence]


@dataclass
class SeedContext:
    db: AsyncSession
    tenant_id: uuid.UUID
    admin_user: User

    # --- inputs (per-tenant parameterisation) ---
    people: list
    divisions_l1: list
    divisions_l2: list
    custom_grades: list
    custom_specs: list
    email_domain: str

    # --- reference data (migration-seeded, fetched once) ---
    # ``grades`` / ``specializations`` are per-run copies: the catalog step
    # adds the tenant's custom dictionary items to them.
    role_map: dict[str, Role]
    status_map: dict[str, AssessmentStatus]
    type_map: dict[str, AssessmentType]
    default_scale: AnswerScale
    scale_options: list[AnswerOption]
    grades: dict[str, DictionaryItem]
    specializations: dict[str, DictionaryItem]
    comp_types: dict[str, DictionaryItem]
    skill_levels: dict[str, SkillLevel]

    # --- outputs, populated as steps run ---
    div: dict[str, Division] = field(default_factory=dict)  # org.seed_divisions
    users: list[User] = field(default_factory=list)  # org.seed_people
    employees: list[Employee] = field(default_factory=list)  # org.seed_people
    position_map: dict[str, Position] = field(
        default_factory=dict
    )  # catalog.seed_positions
    competences: CompetenceHandles | None = None  # competences.seed_competences
    assessment_self: Assessment | None = None  # assessments step; consumed by pdps
