"""HRP-759: a gap of one or more steps becomes one draft vacancy in
Recruitment - cognitive codes only, the tenant's competences that overlap
the gap pre-filled, the link kept on the work side."""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError
from app.modules.company.models import Tenant
from app.modules.recruitment.models import Vacancy, VacancyCompetence
from app.modules.work import coverage, service
from app.modules.work.models import WorkHireNeed
from app.modules.work.schemas import ContainerUpdate, HireNeedCreate, StepUpdate
from sqlalchemy import select

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _employee,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded
from tests.unit.test_work_containers import _user_with_role

no_mapping_enqueue = _quiet
seeded = _seeded


async def _vacancy(db, vacancy_id) -> Vacancy:
    return (
        await db.execute(select(Vacancy).where(Vacancy.id == vacancy_id))
    ).scalar_one()


async def test_gap_of_several_steps_becomes_one_draft_vacancy(db, tenant, user, seeded):
    c = await _container(db, tenant, user, owner_id=user.id)
    judge = await _step(
        db,
        tenant,
        c,
        ["P6", "B1"],
        title="Approve the write-off",
        description="On site",
    )
    covered = await _step(db, tenant, c, ["P1"])
    talk = await _step(db, tenant, c, ["P8"], title="Settle the priorities")
    both = await _competence(db, tenant.id, ["P6", "P8"])
    one = await _competence(db, tenant.id, ["P6"])
    await _competence(db, tenant.id, ["P1"])  # no overlap with the gap
    await _competence(db, tenant.id, ["B1"])  # a boundary code is not hired for
    await _competence(db, tenant.id, ["P6", "P8"], applicable_to="agent")

    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(
            step_ids=[judge["id"], covered["id"], talk["id"]], label="agency"
        ),
        user_id=user.id,
    )
    # The covered step is skipped, the two gaps are kept in breakdown order.
    assert [uuid.UUID(s) for s in need.step_ids] == [judge["id"], talk["id"]]
    assert need.label == "agency"
    assert need.created_by_id == user.id

    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.status == "draft"
    assert vacancy.title == "Month-end close"
    assert vacancy.owner_id == user.id
    assert vacancy.hiring_manager_id == user.id
    assert (
        vacancy.description == "Approve the write-off\nOn site\n\nSettle the priorities"
    )

    rows = (
        (
            await db.execute(
                select(VacancyCompetence)
                .where(VacancyCompetence.vacancy_id == vacancy.id)
                .order_by(VacancyCompetence.created_at, VacancyCompetence.id)
            )
        )
        .scalars()
        .all()
    )
    # The agent-only, the unrelated and the physical ones stay out.
    assert {r.competence_id for r in rows} == {both.id, one.id}
    assert {r.source for r in rows} == {"ai"}


async def test_top_five_by_overlap(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6", "P8"])
    for _ in range(7):
        await _competence(db, tenant.id, ["P6"])
    # Created last, ranked first: it overlaps the gap on two codes.
    best = await _competence(db, tenant.id, ["P6", "P8"])
    need = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
    )
    rows = (
        (
            await db.execute(
                select(VacancyCompetence).where(
                    VacancyCompetence.vacancy_id == need.vacancy_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == service.HIRE_NEED_COMPETENCES
    assert best.id in {r.competence_id for r in rows}


async def test_cold_tenant_still_gets_the_vacancy(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[step["id"]], title="Risk owner"),
        user_id=user.id,
    )
    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.title == "Risk owner"
    assert vacancy.description == "P6"
    assert (
        await db.execute(
            select(VacancyCompetence).where(VacancyCompetence.vacancy_id == vacancy.id)
        )
    ).first() is None


async def test_a_step_is_handed_over_once(db, tenant, user, seeded):
    """A double click (or a retry on a slow create) would otherwise open a
    second draft vacancy nobody sees: the screen shows the newest need."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    other = await _step(db, tenant, c, ["P8"])
    await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db,
            tenant.id,
            c.id,
            HireNeedCreate(step_ids=[step["id"], other["id"]]),
            user_id=user.id,
        )
    assert exc.value.code == "work_hire_need_exists"
    assert exc.value.status_code == 409
    needs = (
        (
            await db.execute(
                select(WorkHireNeed).where(WorkHireNeed.container_id == c.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(needs) == 1
    # The step nobody handed over yet still opens a vacancy of its own.
    second = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[other["id"]]), user_id=user.id
    )
    assert second.step_ids == [str(other["id"])]


async def test_selection_without_a_gap_is_refused(db, tenant, user, seeded):
    # ``covered`` is a step an agent type takes: it is on the To do list as
    # ``not_automated_yet``, and one does not hire for it (W6, §5.10).
    c = await _container(db, tenant, user)
    covered = await _step(db, tenant, c, ["P1"])
    signature = await _step(db, tenant, c, [], responsibility="regulatory")
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db,
            tenant.id,
            c.id,
            HireNeedCreate(step_ids=[covered["id"], signature["id"], uuid.uuid4()]),
            user_id=user.id,
        )
    assert exc.value.code == "work_hire_need_no_gaps"
    assert (
        await db.execute(
            select(WorkHireNeed).where(WorkHireNeed.tenant_id == tenant.id)
        )
    ).first() is None


async def test_assigned_step_is_not_hired_for(db, tenant, user, seeded):
    """HRP-809: an assignment closes the gap, skills or not - the hire guard
    reads the verdict, so the step is refused like any covered one."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    emp = await _employee(db, tenant)
    await service.update_step(
        db, tenant.id, step["id"], StepUpdate(executor_employee_id=emp.id)
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "work_hire_need_no_gaps"


async def test_internal_search_switch_reaches_the_vacancy(db, tenant, user, seeded):
    """W6 (§5.9): hiring from a Coverage row offers "inside first" or
    "straight outside"; the switch belongs to the vacancy, not to us."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[step["id"]], internal_search_allowed=False),
        user_id=user.id,
    )
    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.internal_search_allowed is False
    # The default keeps the internal search on.
    other = await _step(db, tenant, c, ["P7"])
    need = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[other["id"]]), user_id=user.id
    )
    assert (await _vacancy(db, need.vacancy_id)).internal_search_allowed is True


async def test_hire_need_skips_the_not_automated_kind(db, tenant, user, seeded):
    """W6: the guard is on the server, not in the checkboxes - a stale
    screen must not open a vacancy for work an agent is about to do."""
    c = await _container(db, tenant, user)
    automatable = await _step(db, tenant, c, ["P1"])
    real_gap = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[automatable["id"], real_gap["id"]]),
        user_id=user.id,
    )
    assert need.step_ids == [str(real_gap["id"])]


async def test_gaps_carry_the_link_and_routes(db, tenant, user, seeded, auth_client):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    res = await auth_client.post(
        f"/api/work/containers/{c.id}/gaps/hire-need",
        json={"step_ids": [str(step["id"])], "label": "hire"},
    )
    assert res.status_code == 201, res.text
    need = res.json()
    res = await auth_client.get(f"/api/work/containers/{c.id}/gaps")
    assert res.json()[0]["hire_need"] == {
        "id": need["id"],
        "vacancy_id": need["vacancy_id"],
        "label": "hire",
    }
    # Deleting the vacancy drops the link (ON DELETE SET NULL), not the need.
    await db.delete(await _vacancy(db, uuid.UUID(need["vacancy_id"])))
    await db.commit()
    gaps = await coverage.gaps(db, tenant.id, c.id)
    assert gaps[0]["hire_need"] is None
    res = await auth_client.post(
        f"/api/work/containers/{uuid.uuid4()}/gaps/hire-need",
        json={"step_ids": [str(step["id"])]},
    )
    assert res.status_code == 404


async def test_archived_container_refuses_and_label_does_not_reopen(
    db, tenant, user, seeded
):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await service.accept_container(
        db, tenant.id, c.id, user_id=user.id, can_manage=True
    )
    # The gap label and the hours are not content: the breakdown stays
    # accepted through the Gaps tab and the hours editor alike.
    updated = await service.update_step(
        db,
        tenant.id,
        step["id"],
        StepUpdate(gap_label="agency", hours_per_run=0.5, runs_per_year=250),
    )
    assert updated["gap_label"] == "agency"
    assert updated["runs_per_year"] == 250
    assert updated["state"] == "accepted"
    assert (await service.get_container(db, tenant.id, c.id)).status == "active"
    await service.update_container(
        db, tenant.id, c.id, ContainerUpdate(status="archived")
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
        )
    assert exc.value.code == "work_container_archived"


async def test_deleting_a_step_prunes_its_hire_need(db, tenant, user, seeded):
    """A need naming a deleted step would offer the same handoff on every
    coverage read; the need goes with its last step, the vacancy stays."""
    c = await _container(db, tenant, user, owner_id=user.id)
    first = await _step(db, tenant, c, ["P6"], title="Approve the write-off")
    second = await _step(db, tenant, c, ["P8"], title="Settle the priorities")
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[first["id"], second["id"]], label="hire"),
        user_id=user.id,
    )
    need_id, vacancy_id = need.id, need.vacancy_id

    await service.delete_step(db, tenant.id, first["id"])
    kept = await db.get(WorkHireNeed, need_id, populate_existing=True)
    assert kept is not None and kept.step_ids == [str(second["id"])]

    await service.delete_step(db, tenant.id, second["id"])
    assert await db.get(WorkHireNeed, need_id) is None
    assert await _vacancy(db, vacancy_id) is not None


async def test_draft_vacancy_description_is_bounded(db, tenant, user, seeded):
    """A 500-step container must not hand Recruitment a multi-megabyte
    description: it is prose for a person and later a prompt for a model."""
    c = await _container(db, tenant, user, owner_id=user.id)
    steps = [
        await _step(db, tenant, c, ["P6"], title=f"Judge {i}", description="x" * 800)
        for i in range(60)
    ]
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[s["id"] for s in steps], label="hire"),
        user_id=user.id,
    )
    # Every gap is still recorded; only the text is capped.
    assert len(need.step_ids) == 60
    description = (await _vacancy(db, need.vacancy_id)).description
    assert description.endswith(service.HIRE_NEED_TRUNCATED)
    assert len(description) <= service.HIRE_NEED_MAX_DESCRIPTION + 16
    assert description.count("Judge ") <= service.HIRE_NEED_MAX_STEPS


async def test_other_tenants_container_is_404(db, tenant, user, seeded, auth_client):
    other = Tenant(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
    )
    db.add(other)
    await db.commit()
    # HRP-810: the creator becomes the owner, so it is the other tenant's.
    other_admin, _ = await _user_with_role(db, other, "admin")
    c = await _container(db, other, other_admin)
    step = await _step(db, other, c, ["P6"])
    res = await auth_client.post(
        f"/api/work/containers/{c.id}/gaps/hire-need",
        json={"step_ids": [str(step["id"])]},
    )
    assert res.status_code == 404
