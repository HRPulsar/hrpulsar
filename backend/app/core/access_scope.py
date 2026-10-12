"""Access-scope helpers: who sees what across modules.

`None` from `get_visible_employee_ids` means "no scope restriction" (admin / hr) —
callers must NOT add an `employee_id IN (...)` filter in that case. An empty `set()`
means "the user is not linked to any employee" and lists should return nothing.
"""

import uuid
from typing import Any

from fastapi import status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.sections import matrix_levels
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee

ADMIN_ROLE_CODES = frozenset({"admin", "hr", "platform_admin"})
MANAGER_ROLE_CODES = frozenset({"manager"})


def _is_admin(current_user: User) -> bool:
    return any(r.code in ADMIN_ROLE_CODES for r in current_user.roles)


def _is_manager(current_user: User) -> bool:
    return any(r.code in MANAGER_ROLE_CODES for r in current_user.roles)


def is_employee_only(current_user: User) -> bool:
    """True if the caller has neither admin nor manager privileges.

    Used to apply stricter visibility (e.g. hide Draft assessments — HRP-40).
    """
    return not _is_admin(current_user) and not _is_manager(current_user)


async def directory_show_grades(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """HRP-623: whether a colleague may see someone else's grade.

    Off by default, flipped on the company profile. Lives here rather than
    in one module's service because three directory-shaped payloads read it
    (the employee list, the position drill-down and the specialization tab)
    and a second copy of the query is a second place to forget it.
    """
    return bool(
        await db.scalar(
            select(Tenant.directory_show_grades).where(Tenant.id == tenant_id)
        )
    )


# HRP-637: the two field classes answer to two different role sets, so they
# get two predicates rather than one ``is_employee_only()`` used twice.
# Hiring cannot raise a requisition without the grade and specialization of
# the position it is filling (the requisition form fills its pickers from
# them — HRP-180), but compensation is not theirs to read. HRP-830: hiring
# is whoever reaches the recruitment section, not the recruiter and
# hiring_manager roles - the defaults open it to exactly those two on top
# of the admin-level and manager roles below.
GRADE_ROLE_CODES = ADMIN_ROLE_CODES | MANAGER_ROLE_CODES


async def can_see_position_grades(db: AsyncSession, current_user: User) -> bool:
    """HRP-637: may this caller read a position's grade and specialization?

    The positions catalogue publishes "position -> grade", and the employee
    directory publishes "colleague -> position". Joining the two rebuilt a
    colleague's grade whatever ``directory_show_grades`` said, so the flag
    closed the copy of the field and not the fact. Same flag, one more
    payload: off means a rank-and-file caller sees neither the grade nor the
    specialization of a position, on means they see both.

    Deliberately not ``is_employee_only()``: hiring - ``view`` on
    recruitment - reads the pair and not the band, so the two predicates
    carry different rules.
    """
    if any(r.code in GRADE_ROLE_CODES for r in current_user.roles):
        return True
    if (await matrix_levels(db, current_user))["recruitment"] != "none":
        return True
    return await directory_show_grades(db, current_user.tenant_id)


# HRP-637: the two classes of field a position-shaped payload carries that
# a rank-and-file caller may not read. ``grade_specialization_id`` sits in
# the first group because the specialization page turns it straight back
# into a grade title.
_GRADE_FIELDS = (
    "specialization_id",
    "specialization_title",
    "grade_id",
    "grade_title",
    "grade_specialization_id",
)
# Dropped rather than blanked: every schema carrying these gives them a
# default (``[]``, ``None``, the installation currency), and
# ``SpecializationGradeRead.salary_currency`` is a bare ``str`` that a
# ``None`` would fail validation on.
_SALARY_FIELDS = ("salary_min", "salary_max", "salary_currency")
_GRADE_LIST_FIELDS = ("specializations", "grades")
# HRP-637: "this position's pair has competence links" is the pair showing
# through a boolean. It travels with the pair, and so does the predicate
# that selects on it.
_GRADE_DERIVED_FIELDS = ("matrix_configured",)


def trim_position_fields(
    row: dict, *, show_grades: bool = True, show_salary: bool = True
) -> dict:
    """HRP-637: drop the fields the caller may not read, in place.

    Narrows the full row rather than building a second payload — the shape
    ``employee.service.directory_rows`` already uses — so a field added to a
    position payload stays visible here until someone adds it to the tuples
    above, and the payloads sharing these keys (the catalogue row, the
    position detail, the two matrix reads, the specialization drill-down)
    share one rule instead of five copies of it. Keys the row does not
    carry are skipped, which is what lets one call serve all of them.
    """
    if not show_salary:
        for field in _SALARY_FIELDS:
            row.pop(field, None)
    if not show_grades:
        for field in _GRADE_FIELDS:
            if field in row:
                row[field] = None
        for field in _GRADE_LIST_FIELDS:
            row.pop(field, None)
        for field in _GRADE_DERIVED_FIELDS:
            row.pop(field, None)
    return row


def can_see_compensation(current_user: User) -> bool:
    """HRP-637: may this caller read salary bands?

    Compensation is not structure: it stays with admin / hr / manager
    whatever ``directory_show_grades`` is set to, so there is no tenant flag
    to consult and no async work to do. Narrower than
    ``can_see_position_grades`` on purpose — the hiring roles get the pair
    but not the band.
    """
    return not is_employee_only(current_user)


async def get_managed_division_ids(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return all division IDs in the subtree managed by this employee.

    Empty list means the employee is not a manager / deputy of any division.
    """
    result = await db.execute(select(Division).where(Division.tenant_id == tenant_id))
    all_divisions = result.scalars().all()

    managed_roots = [
        d
        for d in all_divisions
        if d.manager_id == employee_id or d.deputy_manager_id == employee_id
    ]
    if not managed_roots:
        return []

    children_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for d in all_divisions:
        if d.parent_id:
            children_map.setdefault(d.parent_id, []).append(d.id)

    subtree_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    queue = [d.id for d in managed_roots]
    while queue:
        current = queue.pop(0)
        if current in seen:
            # A corrupted parent chain (a cycle) ends here instead of
            # hanging the request — same guard as company.service.get_division_subtree_ids.
            continue
        seen.add(current)
        subtree_ids.append(current)
        queue.extend(children_map.get(current, []))
    return subtree_ids


async def get_current_employee(db: AsyncSession, current_user: User) -> Employee | None:
    result = await db.execute(
        select(Employee).where(
            Employee.user_id == current_user.id,
            Employee.tenant_id == current_user.tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_visible_division_ids(
    db: AsyncSession, current_user: User
) -> list[uuid.UUID] | None:
    """List of division ids the current user can see for filter pickers.

    - Admin / HR / platform_admin → ``None`` (no restriction; show all).
    - Division manager → the managed subtree.
    - Anyone else → empty list.
    """
    if _is_admin(current_user):
        return None

    emp = await get_current_employee(db, current_user)
    if emp is None:
        return []

    return await get_managed_division_ids(db, current_user.tenant_id, emp.id)


async def get_visible_employee_ids(
    db: AsyncSession, current_user: User
) -> set[uuid.UUID] | None:
    """Set of employee ids the current user can see.

    - Admin / HR / platform_admin → ``None`` (no restriction).
    - Division manager → own employee + all employees in managed subtree.
    - Regular employee → own employee only.
    - User without an Employee row → empty set (sees nothing).
    """
    if _is_admin(current_user):
        return None

    emp = await get_current_employee(db, current_user)
    if emp is None:
        return set()

    visible: set[uuid.UUID] = {emp.id}

    division_ids = await get_managed_division_ids(db, current_user.tenant_id, emp.id)
    if division_ids:
        result = await db.execute(
            select(Employee.id).where(
                Employee.tenant_id == current_user.tenant_id,
                Employee.division_id.in_(division_ids),
            )
        )
        visible.update(result.scalars().all())
    return visible


async def is_employee_in_read_scope(
    db: AsyncSession, current_user: User, employee_id: uuid.UUID
) -> bool:
    """Whether `current_user` may see the *full* HR card of `employee_id`.

    - admin / hr / platform_admin → everything.
    - manager → own card plus the managed division subtree.
    - anyone else → their own card only.

    HRP-623 turned the assert below into a predicate: the card route now
    picks a schema instead of raising, while the sub-resources keep raising.
    """
    if _is_admin(current_user):
        return True
    visible = await get_visible_employee_ids(db, current_user)
    return visible is None or employee_id in visible


async def assert_employee_read_scope(
    db: AsyncSession, current_user: User, employee_id: uuid.UUID
) -> None:
    """Raise 403 if `current_user` cannot read the card of `employee_id`.

    Takes the id rather than the row — unlike ``assert_employee_write_scope``,
    whose callers already hold one — because the read routers do not load the
    ``Employee`` before answering.

    HRP-616 deliberately closes this hard. HRP-623 reopens the *card itself*
    to colleagues in a trimmed schema; the sub-resources (competences,
    events, education, work history) stay behind this assert.
    """
    if await is_employee_in_read_scope(db, current_user, employee_id):
        return
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def assert_employee_write_scope(
    db: AsyncSession, current_user: User, target: Employee
) -> None:
    """Raise 403 if `current_user` cannot perform a write on `target`.

    HRP-829: writing on someone's record is ``manage`` on ``employees`` -
    the tenant's matrix, ``admin`` and ``manager`` by default - in place of
    the manager role.

    - below ``manage`` → 403 ``employee_write_forbidden``; ``hr`` included,
      which the admin tier used to let through on another's education and
      courses (Maxim, 24.09).
    - admin-level (admin / hr / platform_admin) → the whole workspace.
    - anyone else → `target` must be within `get_visible_employee_ids` (own
      card + managed subtree). Otherwise 403 ``outside_division_scope``.
    """
    if (await matrix_levels(db, current_user))["employees"] != "manage":
        raise AppError(
            "employee_write_forbidden",
            status.HTTP_403_FORBIDDEN,
            detail_extra={},
            detail_code_key="error_code",
        )
    if _is_admin(current_user):
        return
    # The subtree first: an out-of-scope target answers the same whoever
    # they are - asking "is this an admin-level account" first told the
    # caller who holds admin and hr across the workspace.
    visible = await get_visible_employee_ids(db, current_user)
    if visible is not None and target.id not in visible:
        raise AppError(
            "outside_division_scope",
            status.HTTP_403_FORBIDDEN,
            detail_extra={},
            detail_code_key="error_code",
        )
    await assert_may_write_person(db, current_user, target.user_id)


def _admin_level_filter(user_ids: Any) -> Select:
    """``user_roles.user_id`` of the admin-level role holders among ``user_ids``."""
    return (
        select(user_roles.c.user_id)
        .join(Role, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id.in_(user_ids), Role.code.in_(ADMIN_ROLE_CODES))
    )


async def assert_may_write_person(
    db: AsyncSession, current_user: User, user_id: uuid.UUID
) -> None:
    """HRP-829 (Maxim, 24.09): below the admin level nobody writes an
    admin-level person's record - status, transfer, history, pay. A role the
    tenant raised to ``manage`` could otherwise file the workspace owner in
    their division and terminate them out of the app."""
    if _is_admin(current_user):
        return
    if await db.scalar(_admin_level_filter([user_id]).limit(1)) is None:
        return
    raise AppError(
        "employee_write_forbidden",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def pay_visible_employee_ids(
    db: AsyncSession, current_user: User
) -> set[uuid.UUID] | None:
    """HRP-829: whose pay an aggregate may count for this caller - the read
    scope less the admin-level people, whose record (pay included) is
    closed below the admin level. ``None`` for an admin-level role."""
    visible = await get_visible_employee_ids(db, current_user)
    if not visible:
        return visible
    admins = await db.scalars(
        select(Employee.id).where(
            Employee.id.in_(visible),
            Employee.user_id.in_(
                _admin_level_filter(select(Employee.user_id).where(Employee.id.in_(visible)))
            ),
        )
    )
    return visible - set(admins)


async def assert_division_write_scope(
    db: AsyncSession, current_user: User, *division_ids: uuid.UUID | None
) -> None:
    """Raise 403 unless every id sits in the caller's managed subtree.

    - admin / hr / platform_admin → pass.
    - anyone else → each id must be in ``get_visible_division_ids``, the
      managed subtree. ``None`` (the root) is in nobody's subtree, so a
      manager neither creates a top-level division nor detaches one from
      the tree (HRP-819).

    Which roles may write at all is the router's question (``require_role``);
    this only asks whether the caller's subtree holds the ids.
    """
    visible = await get_visible_division_ids(db, current_user)
    if visible is None or all(d in visible for d in division_ids):
        return
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


def authored_only(current_user: User) -> uuid.UUID | None:
    """Whose group runs the caller reaches: ``None`` - all of them - at the
    admin level, otherwise the caller's own user id.

    A CPA round and a mass exam carry no assessee and no division, only
    their author, so below the admin level each is the author's alone - to
    list, open and change; a mass assessment's own actions are too
    (HRP-640, Vladimir 29.09).
    """
    return None if _is_admin(current_user) else current_user.id


async def assert_authored(
    db: AsyncSession,
    current_user: User,
    author_column: Any,
    row_filter: Any,
) -> None:
    """403 unless ``authored_only`` lets the caller reach the row.

    A row that does not exist is refused the same way, as the assessment
    scope does: telling a caller that someone else's run exists is a leak.
    """
    author = authored_only(current_user)
    if author is None:
        return
    if await db.scalar(select(author_column).where(row_filter)) != author:
        raise AppError(
            "not_the_author",
            status.HTTP_403_FORBIDDEN,
            detail_extra={},
            detail_code_key="error_code",
        )


async def assert_division_heads_in_scope(
    db: AsyncSession, current_user: User, *employee_ids: uuid.UUID | None
) -> None:
    """Raise 403 unless every named head sits in the caller's reach.

    Naming a division's manager or deputy grants the ``manager`` role
    (``sync_role_on_assign``), so below the admin level it is someone of
    the caller's own subtree, or the caller - a person from elsewhere is
    the admin's to appoint (HRP-857, Vladimir 29.09). ``None`` clears the
    seat and needs no check.
    """
    heads = [e for e in employee_ids if e is not None]
    if not heads:
        return
    visible = await get_visible_employee_ids(db, current_user)
    if visible is None or all(e in visible for e in heads):
        return
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def assert_not_replacing_self_as_head(
    db: AsyncSession, current_user: User, *current_head_ids: uuid.UUID | None
) -> None:
    """HRP-819 (QA 09.10): below the admin level a division head does not
    hand off a seat they hold themselves.

    ``current_head_ids`` are the *current* holders of the Manager / Deputy
    Manager fields the caller is changing. When one of them is the caller,
    the change unseats the caller — and with the seat may go their manager
    role and this very permission — so it is the admin's or HR's move.
    """
    heads = {e for e in current_head_ids if e is not None}
    if not heads or _is_admin(current_user):
        return
    emp = await get_current_employee(db, current_user)
    if emp is None or emp.id not in heads:
        return
    raise AppError(
        "cannot_replace_self_as_head",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


def assert_not_self_edit_via_employees(current_user: User, target: Employee) -> None:
    """Block a non-admin-level writer from their own employee record via /employees.

    Admin / hr / platform_admin can edit themselves freely. Anyone else who
    writes here holds ``manage`` on ``employees`` (a manager by default,
    HRP-829) and cannot self-demote (status), reassign their own
    position/division, set their own pay or otherwise mutate their own card
    via this endpoint — profile self-edits are routed through ``/auth/me``
    (EMP1 allowlist).
    """
    if _is_admin(current_user) or target.user_id != current_user.id:
        return
    raise AppError(
        "cannot_edit_self_status",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )
