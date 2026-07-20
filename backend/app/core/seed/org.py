"""Steps 1–2g: division tree, users & employees, career history, managers."""

import random
from datetime import datetime, timedelta, timezone

from app.core.security import hash_password
from app.modules.auth.models import User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import (
    Compensation,
    Course,
    Education,
    Employee,
    EmployeeEvent,
    PreviousEmployment,
    WorkExperience,
)

from .context import SeedContext
from .data import (
    COMPENSATION_DATA,
    COURSES_DATA,
    DEMO_PASSWORD,
    EDUCATION_DATA,
    MANAGER_ASSIGNMENTS,
    PREV_EMPLOYMENT_DATA,
    WORK_EXP_DATA,
)
from .helpers import now, past_date, uid


async def seed_divisions(ctx: SeedContext) -> None:
    """Step 1: two-level division tree."""
    for name, key in ctx.divisions_l1:
        d = Division(id=uid(), tenant_id=ctx.tenant_id, name=name, parent_id=None)
        ctx.db.add(d)
        ctx.div[key] = d

    await ctx.db.flush()

    for name, key, parent_key in ctx.divisions_l2:
        d = Division(
            id=uid(),
            tenant_id=ctx.tenant_id,
            name=name,
            parent_id=ctx.div[parent_key].id,
        )
        ctx.db.add(d)
        ctx.div[key] = d

    await ctx.db.flush()


async def seed_people(ctx: SeedContext) -> None:
    """Step 2: users + employees + hire/promotion events."""
    emp_role = ctx.role_map["employee"]
    mgr_role = ctx.role_map["manager"]

    for first, last, _position, _div_key, email_prefix in ctx.people:
        u = User(
            id=uid(),
            tenant_id=ctx.tenant_id,
            email=f"{email_prefix}@{ctx.email_domain}",
            password_hash=hash_password(DEMO_PASSWORD),
            first_name=first,
            last_name=last,
            is_active=True,
            email_verified_at=now,
        )
        ctx.db.add(u)
        ctx.users.append(u)

    await ctx.db.flush()

    for i, (_first, _last, position, div_key, _email_prefix) in enumerate(ctx.people):
        u = ctx.users[i]
        role = (
            mgr_role
            if any(t in position for t in ("Lead", "VP", "Head", "Manager"))
            else emp_role
        )
        await ctx.db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))

        hire_days_ago = random.randint(90, 1200)
        emp = Employee(
            id=uid(),
            tenant_id=ctx.tenant_id,
            user_id=u.id,
            division_id=ctx.div[div_key].id,
            position_title=position,
            hire_date=past_date(hire_days_ago),
            status="active",
        )
        ctx.db.add(emp)
        ctx.employees.append(emp)

        ctx.db.add(
            EmployeeEvent(
                id=uid(),
                employee_id=emp.id,
                event_type="hire",
                description=f"Hired as {position}",
                event_date=emp.hire_date,
            )
        )

    await ctx.db.flush()

    # Position change events for some employees
    sample_size = min(5, len(ctx.employees))
    for emp in random.sample(ctx.employees[: max(sample_size, 1)], sample_size):
        ctx.db.add(
            EmployeeEvent(
                id=uid(),
                employee_id=emp.id,
                event_type="position_change",
                description="Promoted",
                event_date=past_date(random.randint(30, 200)),
                metadata={
                    "old_position": "Junior " + (emp.position_title or "").split()[-1],
                    "new_position": emp.position_title,
                },
            )
        )

    await ctx.db.flush()


async def seed_career_history(ctx: SeedContext) -> None:
    """Steps 2b–2f: previous employment, work experience, education,
    courses & certifications, compensation."""
    for emp_idx, company, position, desc, start_ago, end_ago in PREV_EMPLOYMENT_DATA:
        if emp_idx < len(ctx.employees):
            ctx.db.add(
                PreviousEmployment(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    employee_id=ctx.employees[emp_idx].id,
                    company_name=company,
                    position=position,
                    description=desc,
                    start_date=past_date(start_ago),
                    end_date=past_date(end_ago),
                )
            )

    await ctx.db.flush()

    for emp_idx, title, role, desc, start_ago, end_ago in WORK_EXP_DATA:  # type: ignore[assignment]
        if emp_idx < len(ctx.employees):
            ctx.db.add(
                WorkExperience(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    employee_id=ctx.employees[emp_idx].id,
                    title=title,
                    role=role,
                    description=desc,
                    start_date=past_date(start_ago),
                    end_date=past_date(end_ago) if end_ago else None,
                )
            )

    await ctx.db.flush()

    for emp_idx, institution, degree, field, start_ago, end_ago in EDUCATION_DATA:
        if emp_idx < len(ctx.employees):
            ctx.db.add(
                Education(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    employee_id=ctx.employees[emp_idx].id,
                    institution=institution,
                    degree=degree,
                    field_of_study=field,
                    start_date=past_date(start_ago),
                    end_date=past_date(end_ago),
                )
            )

    await ctx.db.flush()

    for emp_idx, title, provider, cert_url, completed_ago, expiry_ahead in COURSES_DATA:
        if emp_idx < len(ctx.employees):
            ctx.db.add(
                Course(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    employee_id=ctx.employees[emp_idx].id,
                    title=title,
                    provider=provider,
                    certificate_url=cert_url,
                    completed_date=past_date(completed_ago),
                    expiry_date=(
                        (
                            datetime.now(timezone.utc) + timedelta(days=expiry_ahead)
                        ).date()
                        if expiry_ahead
                        else None
                    ),
                )
            )

    await ctx.db.flush()

    for (  # type: ignore[assignment]
        emp_idx,
        comp_type,
        amount,
        currency,
        eff_ago,
        end_ago,
        notes,
    ) in COMPENSATION_DATA:
        if emp_idx < len(ctx.employees):
            ctx.db.add(
                Compensation(
                    id=uid(),
                    tenant_id=ctx.tenant_id,
                    employee_id=ctx.employees[emp_idx].id,
                    type=comp_type,
                    amount=amount,
                    currency=currency,
                    effective_date=past_date(eff_ago),
                    end_date=past_date(end_ago) if end_ago else None,
                    notes=notes,
                )
            )

    await ctx.db.flush()


async def assign_division_managers(ctx: SeedContext) -> None:
    """Step 2g: division managers & deputies (GF6)."""
    for div_key, (mgr_idx, deputy_idx) in MANAGER_ASSIGNMENTS.items():
        if div_key in ctx.div and mgr_idx < len(ctx.employees):
            ctx.div[div_key].manager_id = ctx.employees[mgr_idx].id
            if deputy_idx is not None and deputy_idx < len(ctx.employees):
                ctx.div[div_key].deputy_manager_id = ctx.employees[deputy_idx].id

    await ctx.db.flush()
