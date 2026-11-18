"""HRP-1197: a step done by people names several executors, picked from a
list ranked by how much of the step each person holds."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app.core.errors import AppError
from app.modules.work import coverage, service
from app.modules.work.schemas import StepUpdate

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _done,
    _employee,
    _row,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded

no_mapping_enqueue = _quiet
seeded = _seeded


async def _executors(db, tenant, step, ids):
    return await service.update_step(
        db, tenant.id, step["id"], StepUpdate(executor_employee_ids=ids)
    )


async def test_several_people_close_the_step(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6", "P8"])
    novak = await _employee(db, tenant, last_name="Novak")
    adams = await _employee(db, tenant, last_name="Adams")
    await _done(db, tenant, novak, await _competence(db, tenant.id, ["P6"]), 90)

    read = await _executors(db, tenant, step, [novak.id, adams.id, novak.id])
    # Deduplicated; named in one save, so in no promised order.
    assert sorted(read["executor_employee_ids"]) == sorted([novak.id, adams.id])

    row, _ = await _row(db, tenant, c, step["id"])
    assert row["verdict"] == "human"
    # By name, each with what they lack; ``human`` is the first of them.
    assert [(e["name"], e["missing_codes"]) for e in row["executors"]] == [
        ("Jane Adams", ["P6", "P8"]),
        ("Jane Novak", ["P8"]),
    ]
    assert {e["label"] for e in row["executors"]} == {"assigned"}
    assert row["human"] == row["executors"][0]

    # The whole set each time: one kept, one dropped, none added.
    read = await _executors(db, tenant, step, [novak.id])
    assert read["executor_employee_ids"] == [novak.id]
    row, _ = await _row(db, tenant, c, step["id"])
    assert [e["employee_id"] for e in row["executors"]] == [novak.id]

    read = await _executors(db, tenant, step, [])
    assert read["executor_employee_ids"] == []
    row, _ = await _row(db, tenant, c, step["id"])
    assert row["executors"] == [] and row["verdict"] == "gap"


async def test_a_person_kept_on_leave_stays_and_a_new_one_must_be_at_work(
    db, tenant, user, seeded
):
    """HRP-959: the company's word stands for someone already named; adding
    someone needs a person at work (HRP-809) - and nothing is half-saved."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    here = await _employee(db, tenant, last_name="Here")
    await _executors(db, tenant, step, [here.id])
    here.status = "on_leave"
    await db.commit()
    away = await _employee(db, tenant, last_name="Away", status="on_leave")
    fresh = await _employee(db, tenant, last_name="Fresh")
    here_id, fresh_id, away_id = here.id, fresh.id, away.id

    tenant_id = tenant.id

    with pytest.raises(AppError) as exc:
        await _executors(db, tenant, step, [here_id, fresh_id, away_id])
    assert exc.value.code == "work_step_employee_invalid"
    await db.rollback()
    assert (await service.step_executor_ids(db, [step["id"]]))[step["id"]] == [here_id]

    read = await service.update_step(
        db, tenant_id, step["id"], StepUpdate(executor_employee_ids=[here_id, fresh_id])
    )
    assert read["executor_employee_ids"] == [here_id, fresh_id]


async def test_null_is_refused(db, tenant, user, seeded, auth_client):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    res = await auth_client.patch(
        f"/api/work/steps/{step['id']}", json={"executor_employee_ids": None}
    )
    assert res.status_code == 422


async def test_the_old_single_executor_field_still_names_the_set(
    db, tenant, user, seeded, auth_client
):
    """One release of the 2.6.1 contract: ``executor_employee_id`` reads as
    the whole set, ``null`` as nobody; the list wins when both come."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    novak = await _employee(db, tenant, last_name="Novak")
    adams = await _employee(db, tenant, last_name="Adams")
    url = f"/api/work/steps/{step['id']}"

    res = await auth_client.patch(url, json={"executor_employee_id": str(novak.id)})
    assert res.status_code == 200, res.text
    assert res.json()["executor_employee_ids"] == [str(novak.id)]
    both = {
        "executor_employee_id": str(novak.id),
        "executor_employee_ids": [str(adams.id)],
    }
    res = await auth_client.patch(url, json=both)
    assert res.json()["executor_employee_ids"] == [str(adams.id)]
    res = await auth_client.patch(url, json={"executor_employee_id": None})
    assert res.json()["executor_employee_ids"] == []
    assert StepUpdate().model_dump(exclude_unset=True) == {}


async def test_people_are_ranked_by_how_much_of_the_step_they_hold(
    db, tenant, user, seeded
):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6", "P8", "B1"])
    both = await _employee(db, tenant, last_name="Zorn")
    half = await _employee(db, tenant, last_name="Berg")
    none_ = await _employee(db, tenant, last_name="Abel")
    await _employee(db, tenant, last_name="Away", status="on_leave")
    await _done(db, tenant, both, await _competence(db, tenant.id, ["P6", "P8"]), 90)
    await _done(db, tenant, half, await _competence(db, tenant.id, ["P8"]), 90)
    # Below the passing score: holds nothing.
    await _done(db, tenant, none_, await _competence(db, tenant.id, ["P6"]), 40)

    people = await coverage.step_people(db, tenant.id, step["id"], visible=None)
    ranked = [(p["name"], p["match_percent"]) for p in people]
    # The boundary code is not a capability anyone holds: two codes count.
    assert ranked[:2] == [("Jane Zorn", 100), ("Jane Berg", 50)]
    assert ("Jane Abel", 0) in ranked
    # Ties by name; nobody on leave is offered.
    zeros = [n for n, percent in ranked if percent == 0 and n.startswith("Jane ")]
    assert zeros == sorted(zeros, key=lambda n: n.split()[-1])
    assert "Jane Away" not in {name for name, _ in ranked}

    # Outside the reader's HR scope the percent is not theirs to see; the
    # person is still offered, after everyone with a percent.
    scoped = await coverage.step_people(db, tenant.id, step["id"], visible={half.id})
    assert scoped[0]["name"] == "Jane Berg" and scoped[0]["match_percent"] == 50
    assert {p["match_percent"] for p in scoped[1:]} == {None}


async def test_the_people_route_is_the_editors_and_the_tenants(
    db, tenant, user, seeded, auth_client
):
    from app.modules.company.models import Tenant

    from tests.unit.test_work_containers import _user_with_role

    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    emp = await _employee(db, tenant, last_name="Novak")
    res = await auth_client.get(f"/api/work/steps/{step['id']}/people")
    assert res.status_code == 200, res.text
    assert str(emp.id) in {p["employee_id"] for p in res.json()}

    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other)
    await db.commit()
    other_admin, _ = await _user_with_role(db, other, "admin")
    foreign = await _step(db, other, await _container(db, other, other_admin), ["P6"])
    res = await auth_client.get(f"/api/work/steps/{foreign['id']}/people")
    assert res.status_code == 404


def test_the_frontend_asks_the_people_route():
    from app.main import app

    work_ts = Path(__file__).resolve().parents[3] / "frontend/src/lib/api/work.ts"
    if not work_ts.exists():
        pytest.skip("frontend tree not present")
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/work/steps/{step_id}/people" in paths
    assert "/work/steps/${stepId}/people" in work_ts.read_text()
