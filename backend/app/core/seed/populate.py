"""Tenant population orchestrator.

Runs the seed steps in order over a shared :class:`SeedContext`; each step
lives in its own module and only communicates through the context.
"""

import uuid

from app.modules.auth.models import User

from . import assessments, catalog, competences, exams, org, pdps, talent
from .context import SeedContext
from .data import CUSTOM_GRADES, CUSTOM_SPECS, DIVISIONS_L1, DIVISIONS_L2, PEOPLE


async def populate_tenant(
    db,
    *,
    tenant_id: uuid.UUID,
    admin_user: User,
    ref_data: dict,
    people: list = PEOPLE,
    divisions_l1: list = DIVISIONS_L1,
    divisions_l2: list = DIVISIONS_L2,
    custom_grades: list | None = None,
    custom_specs: list | None = None,
    email_domain: str = "pulsar.demo",
    full_demo: bool = True,
):
    """Populate a tenant with organizational data.

    When full_demo=True (default), creates the full set:
    divisions, employees, dictionary items, competences, assessments, PDPs,
    exams, and talent market cards.

    When full_demo=False, creates only divisions, employees, dictionary items,
    and competences (suitable for secondary tenants).
    """
    if custom_grades is None:
        custom_grades = CUSTOM_GRADES
    if custom_specs is None:
        custom_specs = CUSTOM_SPECS

    ctx = SeedContext(
        db=db,
        tenant_id=tenant_id,
        admin_user=admin_user,
        people=people,
        divisions_l1=divisions_l1,
        divisions_l2=divisions_l2,
        custom_grades=custom_grades,
        custom_specs=custom_specs,
        email_domain=email_domain,
        role_map=ref_data["role_map"],
        status_map=ref_data["status_map"],
        type_map=ref_data["type_map"],
        default_scale=ref_data["default_scale"],
        scale_options=ref_data["scale_options"],
        # copies: the catalog step adds the tenant's custom items
        grades=dict(ref_data["grades"]),
        specializations=dict(ref_data["specializations"]),
        comp_types=ref_data["comp_types"],
        skill_levels=ref_data["skill_levels"],
    )

    await org.seed_divisions(ctx)
    await org.seed_people(ctx)
    await org.seed_career_history(ctx)
    await org.assign_division_managers(ctx)
    await catalog.seed_custom_dictionary(ctx)
    await catalog.seed_specialization_divisions(ctx)
    await catalog.seed_positions(ctx)
    await competences.seed_competences(ctx)

    if full_demo:
        await assessments.seed_assessments(ctx)
        await pdps.seed_pdps(ctx)
        await exams.seed_mass_exam(ctx)
        await talent.seed_talent_market(ctx)

    assert ctx.competences is not None
    return {
        "employees": ctx.employees,
        "users": ctx.users,
        "divisions": ctx.div,
        "competences": ctx.competences.all_competences,
        "positions": ctx.position_map,
    }
