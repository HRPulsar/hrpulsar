"""HRP-758: nothing of another tenant - its people, its agents, its
containers - leaks into a coverage answer."""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError
from app.modules.company.models import Tenant
from app.modules.work import coverage
from app.modules.work.models import WorkStep
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_coverage_matching import (
    _agent,
    _competence,
    _container,
    _done,
    _employee,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded
from tests.unit.test_work_containers import _user_with_role

# Re-exported under the names the tests below ask for: pytest resolves a
# fixture by the name it is bound to in this module.
no_mapping_enqueue = _quiet
seeded = _seeded


async def _other_tenant(db: AsyncSession) -> Tenant:
    t = Tenant(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
    )
    db.add(t)
    await db.commit()
    return t


async def test_other_tenants_people_and_agents_do_not_cover(
    db,
    tenant,
    user,
    seeded,
):
    c = await _container(db, tenant, user)
    judge = await _step(db, tenant, c, ["P6"])
    mixed = await _step(db, tenant, c, ["P1", "P4", "P5"])
    other = await _other_tenant(db)
    stranger = await _employee(db, other)
    await _done(db, other, stranger, await _competence(db, other.id, ["P6"]), 95)
    # Registered by the other tenant with an override that would match.
    await _agent(db, other, user, "investigation", name="Theirs", add=["P5"])
    result = await coverage.compute(db, tenant.id, c.id)
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id[judge["id"]]["verdict"] == "gap"
    assert by_id[judge["id"]]["human"] is None
    assert by_id[mixed["id"]]["verdict"] == "gap"


async def test_other_tenants_employee_is_not_an_assignee(db, tenant, user, seeded):
    """HRP-809: the service refuses a stranger, and the read does not trust
    the column either - a row written around the service stays a gap."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"], responsibility="formal")
    stranger = await _employee(db, await _other_tenant(db))
    row = await db.get(WorkStep, step["id"])
    row.executor_employee_id = stranger.id
    row.accountable_employee_id = stranger.id
    await db.commit()
    result = await coverage.compute(db, tenant.id, c.id)
    [coverage_row] = result["steps"]
    assert coverage_row["verdict"] == "gap"
    assert coverage_row["human"] is None
    assert coverage_row["accountable"] is None
    assert coverage_row["needs_accountable"] is True


async def test_other_tenants_container_is_404(
    db,
    tenant,
    user,
    seeded,
    auth_client,
):
    other = await _other_tenant(db)
    # HRP-810: the creator becomes the owner, so it is the other tenant's.
    other_admin, _ = await _user_with_role(db, other, "admin")
    c = await _container(db, other, other_admin)
    res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
    assert res.status_code == 404
    res = await auth_client.get(f"/api/work/containers/{c.id}/gaps")
    assert res.status_code == 404
    with pytest.raises(AppError) as exc:
        await coverage.compute(db, tenant.id, c.id)
    assert exc.value.code == "work_container_not_found"


async def test_other_tenants_indicator_on_a_shared_competence_stays_hidden(
    db,
    tenant,
    seeded,
    no_mapping_enqueue,
):
    """Review B5: an origin competence is shared, and every tenant may hang
    its own indicators on it — so a reader filtering on ``competence_id``
    alone put another company's wording into the prompt and the SKILL.md."""
    from app.modules.competence.models import Indicator, SkillLevel
    from app.modules.work import skills

    from tests.unit.test_coverage_matching import _primitive_ids

    shared = await _competence(db, None, ["P2"])
    other = await _other_tenant(db)
    level = SkillLevel(tenant_id=None, title=f"L {uuid.uuid4().hex[:6]}")
    db.add(level)
    await db.flush()
    db.add_all(
        [
            Indicator(
                title="Ours: reconciles every line",
                competence_id=shared.id,
                skill_level_id=level.id,
                tenant_id=tenant.id,
            ),
            Indicator(
                title="Theirs: countersigned by the CFO",
                competence_id=shared.id,
                skill_level_id=level.id,
                tenant_id=other.id,
            ),
            Indicator(
                title="Origin: documented in the ledger",
                competence_id=shared.id,
                skill_level_id=level.id,
                tenant_id=None,
            ),
        ]
    )
    await db.commit()

    ids = await _primitive_ids(db, ["P2"])
    loaded = dict(await skills.load_indicators(db, tenant.id, [ids["P2"]]))
    titles = loaded[shared.title]
    assert "Ours: reconciles every line" in titles
    assert "Origin: documented in the ledger" in titles
    assert "Theirs: countersigned by the CFO" not in titles
