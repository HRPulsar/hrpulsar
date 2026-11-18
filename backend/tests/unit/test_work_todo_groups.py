"""HRP-1198 / HRP-1206: To do in three groups - people with nobody assigned,
an agent still missing something, nobody at all - and the coverage row
says which group it is in, so the tab's count needs no second read."""

from __future__ import annotations

from app.modules.work import coverage, service
from app.modules.work.schemas import StepUpdate

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _done,
    _employee,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded

no_mapping_enqueue = _quiet
seeded = _seeded


async def test_three_groups_and_the_row_says_which(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    nobody = await _step(db, tenant, c, ["P6"], title="Judge")
    agent = await _step(db, tenant, c, ["P1"], title="Extract")
    matched = await _step(db, tenant, c, ["P8"], title="Talk")
    assigned = await _step(db, tenant, c, ["P8", "P6"], title="Sign")
    novak = await _employee(db, tenant, last_name="Novak")
    await _done(db, tenant, novak, await _competence(db, tenant.id, ["P8"]), 90)
    await service.update_step(
        db, tenant.id, assigned["id"], StepUpdate(executor_employee_ids=[novak.id])
    )

    rows = await coverage.gaps(db, tenant.id, c.id)
    kinds = {r["step_id"]: r["kind"] for r in rows}
    # A step with people named to it is closed, whatever they lack.
    assert kinds == {
        nobody["id"]: "no_owner",
        agent["id"]: "not_automated_yet",
        matched["id"]: "unassigned",
    }
    found = next(r for r in rows if r["kind"] == "unassigned")
    assert found["human"]["employee_id"] == novak.id
    assert found["human"]["label"] == "assessed"

    # The coverage row carries the same group: the tab's count is the
    # number of rows with one.
    result = await coverage.compute(db, tenant.id, c.id)
    todo = {r["step_id"]: r["todo"] for r in result["steps"] if r["todo"]}
    assert todo == kinds

    # Confirming the match takes the step off To do.
    await service.update_step(
        db, tenant.id, matched["id"], StepUpdate(executor_employee_ids=[novak.id])
    )
    rows = await coverage.gaps(db, tenant.id, c.id)
    assert matched["id"] not in {r["step_id"] for r in rows}


async def test_a_match_outside_the_scope_is_listed_without_a_name(
    db, tenant, user, seeded
):
    """The match comes from assessments: outside the reader's HR scope the
    step is still listed, with nobody named - as on the coverage."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P8"])
    novak = await _employee(db, tenant, last_name="Novak")
    await _done(db, tenant, novak, await _competence(db, tenant.id, ["P8"]), 90)

    [row] = await coverage.gaps(db, tenant.id, c.id, visible=set())
    assert (row["step_id"], row["kind"], row["human"]) == (
        step["id"],
        "unassigned",
        None,
    )


async def test_the_gaps_route_names_the_match_within_the_scope(
    db, tenant, user, seeded, auth_client
):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P8"])
    novak = await _employee(db, tenant, last_name="Novak")
    await _done(db, tenant, novak, await _competence(db, tenant.id, ["P8"]), 90)

    res = await auth_client.get(f"/api/work/containers/{c.id}/gaps")
    assert res.status_code == 200, res.text
    [row] = res.json()
    assert row["step_id"] == str(step["id"]) and row["kind"] == "unassigned"
    assert row["human"]["name"] == "Jane Novak"
    cov = (await auth_client.get(f"/api/work/containers/{c.id}/coverage")).json()
    assert [s["todo"] for s in cov["steps"]] == ["unassigned"]
