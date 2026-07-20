"""Steps 3–3c: custom dictionary items, specialization-division mappings,
positions."""

from app.modules.company.models import SpecializationDivision
from app.modules.dictionary.models import DictionaryItem
from app.modules.position.models import Position

from .context import SeedContext
from .data import CUSTOM_SPEC_DIV, SPEC_DIV_MAPPINGS
from .helpers import uid


def _infer_position_meta(
    title: str,
    grades: dict,
    specializations: dict,
) -> tuple:
    """Best-effort inference of grade and specialization from position title."""
    grade = None
    spec = None
    tl = title.lower()

    # Grade detection (more specific patterns first)
    if "junior" in tl:
        grade = grades.get("Junior")
    elif "senior" in tl:
        grade = grades.get("Senior")
    elif any(w in tl for w in ("lead", "principal")):
        grade = grades.get("Lead") or grades.get("Principal")
    elif any(w in tl for w in ("vp ", "vp of")):
        grade = grades.get("VP")
    elif any(w in tl for w in ("head of", "head nurse", "director")):
        grade = grades.get("Director") or grades.get("Department Head")
    elif any(w in tl for w in ("cto", "ceo", "coo", "cfo", "cmo", "chief")):
        grade = grades.get("CTO") or grades.get("Chief Officer")
    elif "partner" in tl:
        grade = grades.get("Partner") or grades.get("Senior")
    elif "managing" in tl:
        grade = grades.get("Director")
    else:
        grade = grades.get("Middle")

    # Specialization detection
    if "backend" in tl:
        spec = specializations.get("Backend Developer")
    elif "frontend" in tl:
        spec = specializations.get("Frontend Developer")
    elif "full-stack" in tl or "full stack" in tl:
        spec = specializations.get("Full-Stack Developer")
    elif "qa" in tl or "quality" in tl:
        spec = specializations.get("QA Engineer")
    elif "devops" in tl or "infrastructure" in tl or "security" in tl:
        spec = specializations.get("DevOps Engineer")
    elif "product manager" in tl or "product analyst" in tl:
        spec = specializations.get("Product Manager")
    elif any(w in tl for w in ("designer", "ux ", "ui ")):
        spec = specializations.get("UX/UI Designer")
    elif any(w in tl for w in ("hr ", "recruiter", "l&d", "recruitment")):
        spec = specializations.get("HR Manager")
    elif "data analyst" in tl:
        spec = specializations.get("Data Analyst")
    elif "technical writer" in tl:
        spec = specializations.get("Technical Writer")
    elif "scrum" in tl:
        spec = specializations.get("Scrum Master")
    elif "pharmacist" in tl:
        spec = specializations.get("Pharmacist")
    elif "nurse" in tl:
        spec = specializations.get("Clinical Nurse")
    elif "researcher" in tl or "research" in tl:
        spec = specializations.get("Clinical Researcher")
    elif "consultant" in tl:
        spec = specializations.get("Strategy Consultant") or specializations.get(
            "IT Consultant"
        )

    return grade, spec


async def seed_custom_dictionary(ctx: SeedContext) -> None:
    """Step 3: tenant-scoped custom grades and specializations.

    Extends ``ctx.grades`` / ``ctx.specializations`` (the per-run copies)
    so positions and later steps can reference the custom titles.
    """
    for title, desc, idx in ctx.custom_grades:
        di = DictionaryItem(
            id=uid(),
            type="grade",
            title=title,
            description=desc,
            is_active=True,
            sort_index=idx,
            tenant_id=ctx.tenant_id,
        )
        ctx.db.add(di)
        ctx.grades[di.title] = di

    for title, idx in ctx.custom_specs:
        di = DictionaryItem(
            id=uid(),
            type="specialization",
            title=title,
            is_active=True,
            sort_index=idx,
            tenant_id=ctx.tenant_id,
        )
        ctx.db.add(di)
        ctx.specializations[di.title] = di

    await ctx.db.flush()


async def seed_specialization_divisions(ctx: SeedContext) -> None:
    """Step 3b: specialization-division mappings (GF7)."""
    for spec_title, div_key in SPEC_DIV_MAPPINGS + CUSTOM_SPEC_DIV:
        if spec_title in ctx.specializations and div_key in ctx.div:
            ctx.db.add(
                SpecializationDivision(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    division_id=ctx.div[div_key].id,
                    specialization_id=ctx.specializations[spec_title].id,
                )
            )

    await ctx.db.flush()


async def seed_positions(ctx: SeedContext) -> None:
    """Step 3c: positions inferred from the people list, linked back to
    employees."""
    title_counts: dict[str, int] = {}
    title_div: dict[str, str] = {}
    for _, _, pos_title, div_key, _ in ctx.people:
        title_counts[pos_title] = title_counts.get(pos_title, 0) + 1
        if pos_title not in title_div:
            title_div[pos_title] = div_key

    for pos_title, count in title_counts.items():
        grade, spec = _infer_position_meta(pos_title, ctx.grades, ctx.specializations)
        dk = title_div[pos_title]
        pos = Position(
            id=uid(),
            tenant_id=ctx.tenant_id,
            title=pos_title,
            division_id=ctx.div[dk].id if dk in ctx.div else None,
            grade_id=grade.id if grade else None,
            specialization_id=spec.id if spec else None,
            headcount=count,
            source="manual",
        )
        ctx.db.add(pos)
        ctx.position_map[pos_title] = pos

    await ctx.db.flush()

    # Link employees to positions
    for i, (_, _, pos_title, _, _) in enumerate(ctx.people):
        if i < len(ctx.employees) and pos_title in ctx.position_map:
            ctx.employees[i].position_id = ctx.position_map[pos_title].id

    await ctx.db.flush()
