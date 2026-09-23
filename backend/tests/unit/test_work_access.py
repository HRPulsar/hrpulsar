"""HRP-810: who reads and who edits a Coverage container - the section's
managers, the owner, the access rules and the people on the steps; a
stranger gets nothing, not even a 403 that confirms the process exists."""

from __future__ import annotations

import inspect
import uuid
from datetime import date

import pytest
from app.core.errors import AppError
from app.main import app
from app.modules.employee.models import Employee
from app.modules.primitives import catalog_data
from app.modules.primitives.catalog_data import CATALOG_VERSION
from app.modules.work import access
from app.modules.work.models import (
    WorkContainer,
    WorkContainerAccessRule,
    WorkStep,
)
from sqlalchemy import select, update

from tests.unit.test_coverage_matching import _employee
from tests.unit.test_work_containers import _user_with_role


async def _container(db, tenant, *, visibility="restricted", owner_id=None):
    row = WorkContainer(
        tenant_id=tenant.id,
        type="process",
        title=f"Process {uuid.uuid4().hex[:6]}",
        visibility=visibility,
        owner_id=owner_id,
        catalog_version=CATALOG_VERSION,
    )
    db.add(row)
    await db.commit()
    return row


def _actor(
    tenant, *, codes=("employee",), user_id=None, employee_id=None, position_id=None
):
    return access.Actor(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant.id,
        manage=bool(access.MANAGE_ROLES & set(codes)),
        role_codes=tuple(codes),
        employee_id=employee_id,
        position_id=position_id,
    )


async def _visible(db, actor) -> set[uuid.UUID]:
    rows = await db.execute(
        select(WorkContainer.id).where(
            WorkContainer.tenant_id == actor.tenant_id, access.visible(actor)
        )
    )
    return set(rows.scalars())


class TestVisible:
    async def test_stranger_reads_only_company_wide(self, db, tenant):
        open_ = await _container(db, tenant, visibility="company")
        closed = await _container(db, tenant)
        assert await _visible(db, _actor(tenant)) == {open_.id}
        assert closed.id not in await _visible(db, _actor(tenant, codes=("manager",)))

    async def test_manage_roles_read_everything(self, db, tenant):
        closed = await _container(db, tenant)
        for code in ("admin", "hr"):
            assert closed.id in await _visible(db, _actor(tenant, codes=(code,)))

    async def test_owner_reads_and_edits(self, db, tenant, user):
        closed = await _container(db, tenant, owner_id=user.id)
        owner = _actor(tenant, user_id=user.id)
        assert closed.id in await _visible(db, owner)
        assert access.level(owner, closed) == "edit"
        assert access.level(_actor(tenant, codes=("hr",)), closed) == "manage"
        assert access.level(_actor(tenant), closed) == "read"

    async def test_rules_by_role_position_and_employee(self, db, tenant, position):
        emp = await _employee(db, tenant, position=position)
        by_role = await _container(db, tenant)
        by_position = await _container(db, tenant)
        by_employee = await _container(db, tenant)
        db.add_all(
            [
                WorkContainerAccessRule(
                    tenant_id=tenant.id, container_id=by_role.id, role_code="manager"
                ),
                WorkContainerAccessRule(
                    tenant_id=tenant.id,
                    container_id=by_position.id,
                    position_id=position.id,
                ),
                WorkContainerAccessRule(
                    tenant_id=tenant.id, container_id=by_employee.id, employee_id=emp.id
                ),
            ]
        )
        await db.commit()
        assert await _visible(db, _actor(tenant, codes=("manager",))) == {by_role.id}
        assert await _visible(
            db, _actor(tenant, employee_id=emp.id, position_id=position.id)
        ) == {by_position.id, by_employee.id}

    async def test_step_executor_and_accountable_read(self, db, tenant):
        doer = await _employee(db, tenant, last_name="Doer")
        checker = await _employee(db, tenant, last_name="Checker")
        closed = await _container(db, tenant)
        db.add(
            WorkStep(
                tenant_id=tenant.id,
                container_id=closed.id,
                position=1,
                title="Release the payment",
                executor_employee_id=doer.id,
                accountable_employee_id=checker.id,
            )
        )
        await db.commit()
        for emp in (doer, checker):
            assert closed.id in await _visible(db, _actor(tenant, employee_id=emp.id))

    async def test_other_tenant_is_never_visible(self, db, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        foreign = await _container(db, other, visibility="company")
        assert foreign.id not in await _visible(db, _actor(tenant, codes=("admin",)))

    async def test_ensure_hides_then_refuses(self, db, tenant, user):
        closed = await _container(db, tenant, owner_id=user.id)
        with pytest.raises(AppError) as exc:
            await access.ensure(db, _actor(tenant), closed.id, edit=False)
        assert exc.value.status_code == 404
        await db.execute(
            update(WorkContainer)
            .where(WorkContainer.id == closed.id)
            .values(visibility="company")
        )
        await db.commit()
        reader = _actor(tenant)
        assert (await access.ensure(db, reader, closed.id, edit=False)).id == closed.id
        with pytest.raises(AppError) as exc:
            await access.ensure(db, reader, closed.id, edit=True)
        assert exc.value.status_code == 403
        owner = _actor(tenant, user_id=user.id)
        assert (await access.ensure(db, owner, closed.id, edit=True)).id == closed.id


# The guard each route must carry - a read route drifting onto an edit
# guard, or a paid route onto a read one, fails here rather than in review.
EXPECTED_GUARDS = {
    "list_containers": "current_actor",
    "create_container": "manage_actor",
    "get_container": "read_container",
    "update_container": "edit_container",
    "delete_container": "manage_actor",
    "accept_container": "edit_container",
    "get_container_access": "edit_container",
    "set_container_access": "edit_container",
    "list_people": "edit_container",
    "list_steps": "read_container",
    "create_step": "edit_container",
    "reorder_steps": "edit_container",
    "update_step": "edit_step",
    "delete_step": "edit_step",
    "set_step_primitives": "edit_step",
    "remove_step_primitive": "edit_step",
    "confirm_step_primitive": "edit_step",
    "reclassify_step": "edit_step",
    "get_coverage": "read_container",
    "list_gaps": "read_container",
    "create_hire_need": "manage_actor",
    "generate_step_skill": "edit_step",
    "get_step_skill": "read_step",
    "download_step_skill": "read_step",
    "download_agent_bundle": "read_container",
    "create_session": "current_actor",
    "latest_session": "read_container",
    "get_session": "read_session",
    "apply_session": "edit_session",
    "cancel_session": "edit_session",
}
GUARDS = set(EXPECTED_GUARDS.values())
# Guarded in the body: the list filters by the predicate, a new run names its
# container in the payload.
BODY_GUARDED = {
    "list_containers": "access.visible(",
    "create_session": "access.ensure(db, actor, data.container_id, edit=True)",
}


def test_every_work_route_carries_its_access_guard():
    seen, wrong = set(), []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__module__", "") != "app.modules.work.router":
            continue
        name = endpoint.__name__
        seen.add(name)
        guards = {d.call.__name__ for d in route.dependant.dependencies if d.call}
        if guards & GUARDS != {EXPECTED_GUARDS.get(name)}:
            wrong.append(f"{name}: {sorted(guards & GUARDS)}")
        marker = BODY_GUARDED.get(name)
        if marker and marker not in inspect.getsource(endpoint):
            wrong.append(f"{name}: no {marker!r} in the body")
    assert not wrong, f"/api/work routes with the wrong access guard: {wrong}"
    assert seen == set(EXPECTED_GUARDS), seen ^ set(EXPECTED_GUARDS)


async def _person(db, tenant, code, position=None):
    user, token = await _user_with_role(db, tenant, code)
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
        position_id=position.id if position else None,
    )
    db.add(emp)
    await db.commit()
    return user, emp, {"Authorization": f"Bearer {token}"}


class TestHttpMatrix:
    async def test_reader_owner_stranger_and_manager(
        self, client, auth_client, db, tenant
    ):
        await db.execute(catalog_data.seed_insert())
        await db.commit()
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Payroll run"}
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json()["my_access"] == "manage"
        step = await auth_client.post(
            f"/api/work/containers/{cid}/steps", json={"title": "Approve the payroll"}
        )
        sid = step.json()["id"]

        owner, _, owner_h = await _person(db, tenant, "employee")
        _, executor_emp, executor_h = await _person(db, tenant, "employee")
        _, _, manager_h = await _person(db, tenant, "manager")
        _, _, stranger_h = await _person(db, tenant, "employee")
        handed = await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": str(owner.id)}
        )
        assert handed.status_code == 200, handed.text

        # A stranger learns nothing, not even that the process exists.
        listed = await client.get("/api/work/containers", headers=stranger_h)
        assert listed.status_code == 200 and listed.json()["items"] == []
        for path in (
            f"/api/work/containers/{cid}",
            f"/api/work/containers/{cid}/steps",
            f"/api/work/containers/{cid}/coverage",
            f"/api/work/containers/{cid}/gaps",
            f"/api/work/containers/{cid}/decomposition/latest",
            f"/api/work/steps/{sid}/skill",
        ):
            got = await client.get(path, headers=stranger_h)
            assert got.status_code == 404, path
        hidden = await client.patch(
            f"/api/work/steps/{sid}", json={"title": "x"}, headers=stranger_h
        )
        assert hidden.status_code == 404

        # The owner edits, but neither deletes nor hands the process over.
        got = await client.get(f"/api/work/containers/{cid}", headers=owner_h)
        assert got.status_code == 200 and got.json()["my_access"] == "edit"
        edited = await client.patch(
            f"/api/work/steps/{sid}", json={"title": "Approve"}, headers=owner_h
        )
        assert edited.status_code == 200, edited.text
        for refused in (
            client.patch(
                f"/api/work/containers/{cid}", json={"owner_id": None}, headers=owner_h
            ),
            client.delete(f"/api/work/containers/{cid}", headers=owner_h),
            client.post(
                f"/api/work/containers/{cid}/gaps/hire-need",
                json={"step_ids": [sid], "label": "hire"},
                headers=owner_h,
            ),
        ):
            assert (await refused).status_code == 403

        # A rule naming the role gives a manager read, not edit.
        db.add(
            WorkContainerAccessRule(
                tenant_id=tenant.id, container_id=uuid.UUID(cid), role_code="manager"
            )
        )
        await db.commit()
        got = await client.get(f"/api/work/containers/{cid}", headers=manager_h)
        assert got.status_code == 200 and got.json()["my_access"] == "read"
        refused = await client.patch(
            f"/api/work/steps/{sid}", json={"title": "x"}, headers=manager_h
        )
        assert refused.status_code == 403

        # Doing a step is enough to read the process.
        assigned = await auth_client.patch(
            f"/api/work/steps/{sid}",
            json={"executor_employee_id": str(executor_emp.id)},
        )
        assert assigned.status_code == 200, assigned.text
        listed = await client.get("/api/work/containers", headers=executor_h)
        assert [c["id"] for c in listed.json()["items"]] == [cid]
        assert listed.json()["items"][0]["my_access"] == "read"


class TestAccessApi:
    async def test_rules_history_and_owner(
        self, client, auth_client, db, tenant, user, position
    ):
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Severance"}
        )
        body = created.json()
        cid = body["id"]
        assert body["visibility"] == "restricted"
        assert body["owner_id"] == str(user.id)

        emp = await _employee(db, tenant, last_name="Reviewer")
        position_title = position.title
        saved = await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={
                "visibility": "company",
                "rules": [
                    {"role_code": "manager"},
                    {"position_id": str(position.id)},
                    {"employee_id": str(emp.id)},
                    {"role_code": "manager"},
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        state = saved.json()
        assert state["visibility"] == "company"
        labels = {
            (r["role_code"], r["position_id"], r["employee_id"]): r["label"]
            for r in state["rules"]
        }
        assert labels == {
            ("manager", None, None): None,
            (None, str(position.id), None): position_title,
            (None, None, str(emp.id)): "Jane Reviewer",
        }
        # One save writes these in one statement; clock_timestamp() may tie,
        # so compare the set of actions, not their order.
        assert sorted(e["action"] for e in state["history"]) == [
            "rule_added",
            "rule_added",
            "rule_added",
            "visibility_changed",
        ]

        again = await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={"visibility": "company", "rules": [{"role_code": "manager"}]},
        )
        assert again.status_code == 200, again.text
        removed = [e for e in again.json()["history"] if e["action"] == "rule_removed"]
        assert {e["payload"]["label"] for e in removed} == {
            position_title,
            "Jane Reviewer",
        }

        for bad in (
            {
                "visibility": "company",
                "rules": [{"role_code": "manager", "employee_id": str(emp.id)}],
            },
            {"visibility": "company", "rules": [{}]},
            {"visibility": "company", "rules": [{"position_id": str(uuid.uuid4())}]},
            {"visibility": "company", "rules": [{"role_code": "admin"}]},
        ):
            refused = await auth_client.put(
                f"/api/work/containers/{cid}/access", json=bad
            )
            assert refused.status_code == 422, bad
        # The refusals rolled back the shared session and expired the fixtures.
        await db.refresh(tenant)

        new_owner, owner_emp, owner_h = await _person(db, tenant, "employee")
        handed = await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": str(new_owner.id)}
        )
        assert handed.status_code == 200, handed.text
        # The owner configures access; a reader does not see the panel.
        mine = await client.get(f"/api/work/containers/{cid}/access", headers=owner_h)
        assert mine.status_code == 200, mine.text
        assert mine.json()["history"][0]["action"] == "owner_changed"
        assert mine.json()["owner"] == {
            "user_id": str(new_owner.id),
            "name": "Employee User",
            "active": True,
        }
        _, _, reader_h = await _person(db, tenant, "employee")
        panel = await client.get(f"/api/work/containers/{cid}/access", headers=reader_h)
        assert panel.status_code == 403

        owner_emp.status = "terminated"
        await db.commit()
        left = await auth_client.get(f"/api/work/containers/{cid}/access")
        assert left.json()["owner"]["active"] is False

    async def test_access_change_keeps_an_accepted_breakdown(self, auth_client):
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Month end"}
        )
        cid = created.json()["id"]
        step = await auth_client.post(
            f"/api/work/containers/{cid}/steps", json={"title": "Close the books"}
        )
        assert step.status_code == 201, step.text
        accepted = await auth_client.post(f"/api/work/containers/{cid}/accept")
        assert accepted.status_code == 200, accepted.text
        opened = await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={"visibility": "company", "rules": []},
        )
        assert opened.status_code == 200, opened.text
        got = await auth_client.get(f"/api/work/containers/{cid}")
        assert got.json()["status"] == "active"


class TestMeSections:
    async def test_coverage_section_follows_reads(
        self, client, auth_client, db, tenant
    ):
        me = await auth_client.get("/api/auth/me")
        assert me.json()["sections"] == {"coverage": "manage"}
        _, _, employee_h = await _person(db, tenant, "employee")
        me = await client.get("/api/auth/me", headers=employee_h)
        assert me.json()["sections"] == {}
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Onboarding"}
        )
        opened = await auth_client.put(
            f"/api/work/containers/{created.json()['id']}/access",
            json={"visibility": "company", "rules": []},
        )
        assert opened.status_code == 200, opened.text
        me = await client.get("/api/auth/me", headers=employee_h)
        assert me.json()["sections"] == {"coverage": "view"}


class TestReviewFollowUps:
    """Paths the first matrix left open: paid and panel routes per actor,
    runs and downloads of a hidden process, rules and assignments opening
    the section, and what a reader without HR data sees on coverage."""

    async def test_owner_reader_and_stranger_on_the_other_routes(
        self, client, auth_client, db, tenant, position
    ):
        from app.modules.work.models import WorkDecompositionSession

        await db.execute(catalog_data.seed_insert())
        await db.commit()
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Bonus pool"}
        )
        cid = created.json()["id"]
        step = await auth_client.post(
            f"/api/work/containers/{cid}/steps",
            json={"title": "Decide the split", "primitive_codes": ["P6"]},
        )
        sid = step.json()["id"]
        owner, _, owner_h = await _person(db, tenant, "employee")
        _, reader_emp, reader_h = await _person(db, tenant, "employee", position)
        _, doer_emp, doer_h = await _person(db, tenant, "employee")
        _, _, stranger_h = await _person(db, tenant, "employee")
        await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": str(owner.id)}
        )
        run = WorkDecompositionSession(
            tenant_id=tenant.id,
            user_id=owner.id,
            container_id=uuid.UUID(cid),
            prompt_version="test",
            status="error",
        )
        db.add(run)
        await db.commit()
        run_id = run.id

        # A stranger: every door of the hidden process is a 404.
        for method, path, body in (
            ("get", f"/api/work/decomposition/sessions/{run_id}", None),
            ("get", f"/api/work/steps/{sid}/skill/download", None),
            ("post", "/api/work/decomposition/sessions", {"container_id": cid}),
            ("get", f"/api/work/containers/{cid}/people", None),
        ):
            got = await client.request(method, path, json=body, headers=stranger_h)
            assert got.status_code == 404, (method, path, got.text)

        # The owner runs the panel and accepts; the people list is theirs too.
        assert (
            await client.put(
                f"/api/work/containers/{cid}/access",
                json={
                    "visibility": "restricted",
                    "rules": [{"position_id": str(position.id)}],
                },
                headers=owner_h,
            )
        ).status_code == 200
        people = await client.get(f"/api/work/containers/{cid}/people", headers=owner_h)
        assert people.status_code == 200
        assert str(reader_emp.id) in {p["employee_id"] for p in people.json()}
        assert (
            await client.post(f"/api/work/containers/{cid}/accept", headers=owner_h)
        ).status_code == 200

        # The position rule, end to end: the reader reads, the panel stays shut.
        assert (
            await client.get(f"/api/work/containers/{cid}", headers=reader_h)
        ).status_code == 200
        me = await client.get("/api/auth/me", headers=reader_h)
        assert me.json()["sections"] == {"coverage": "view"}
        for method, path, body in (
            (
                "put",
                f"/api/work/containers/{cid}/access",
                {"visibility": "company", "rules": []},
            ),
            ("get", f"/api/work/containers/{cid}/people", None),
            ("post", "/api/work/decomposition/sessions", {"container_id": cid}),
        ):
            got = await client.request(method, path, json=body, headers=reader_h)
            assert got.status_code == 403, (method, path, got.text)

        # An assignment opens the section. The assignee reads their own card
        # (what they lack included, as access_scope has it); a reader with no
        # HR scope sees the assignee but not what they lack.
        assert (await client.get("/api/auth/me", headers=doer_h)).json()[
            "sections"
        ] == {}
        assigned = await auth_client.patch(
            f"/api/work/steps/{sid}", json={"executor_employee_id": str(doer_emp.id)}
        )
        assert assigned.status_code == 200, assigned.text
        assert (await client.get("/api/auth/me", headers=doer_h)).json()[
            "sections"
        ] == {"coverage": "view"}
        full = (await auth_client.get(f"/api/work/containers/{cid}/coverage")).json()
        row = next(r for r in full["steps"] if r["step_id"] == sid)
        assert row["human"]["label"] == "assigned"
        assert row["human"]["missing_codes"] == ["P6"]
        seen = (
            await client.get(f"/api/work/containers/{cid}/coverage", headers=doer_h)
        ).json()
        row = next(r for r in seen["steps"] if r["step_id"] == sid)
        assert row["human"]["employee_id"] == str(doer_emp.id)
        assert row["human"]["missing_codes"] == ["P6"]
        seen = (
            await client.get(f"/api/work/containers/{cid}/coverage", headers=reader_h)
        ).json()
        row = next(r for r in seen["steps"] if r["step_id"] == sid)
        assert row["human"]["employee_id"] == str(doer_emp.id)
        assert row["human"]["missing_codes"] == []

        # An archived process still gets a new owner.
        assert (
            await auth_client.patch(
                f"/api/work/containers/{cid}", json={"status": "archived"}
            )
        ).status_code == 200
        handed = await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": None}
        )
        assert handed.status_code == 200, handed.text

    async def test_on_leave_is_still_with_the_company(self, auth_client, db, tenant):
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Parental leave"}
        )
        cid = created.json()["id"]
        owner, owner_emp, _ = await _person(db, tenant, "employee")
        owner_emp.status = "on_leave"
        await db.commit()
        handed = await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": str(owner.id)}
        )
        assert handed.status_code == 200, handed.text
        saved = await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={
                "visibility": "restricted",
                "rules": [{"employee_id": str(owner_emp.id)}],
            },
        )
        assert saved.status_code == 200, saved.text
        state = saved.json()
        assert state["owner"]["active"] is True
        change = next(e for e in state["history"] if e["action"] == "owner_changed")
        assert change["payload"]["to_name"] == "Employee User"


async def test_history_never_names_a_stranger(db, tenant):
    """The names on the panel are resolved within the tenant: an actor id
    from anywhere else stays unnamed, as an unknown rule target does."""
    from app.modules.company.models import Tenant
    from app.modules.work import service
    from app.modules.work.models import WorkContainerAccessLog

    other = Tenant(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
    )
    db.add(other)
    await db.commit()
    stranger, _ = await _user_with_role(db, other, "employee")
    container = await _container(db, tenant)
    db.add(
        WorkContainerAccessLog(
            tenant_id=tenant.id,
            container_id=container.id,
            actor_id=stranger.id,
            action="visibility_changed",
            payload={},
        )
    )
    await db.commit()
    state = await service.get_container_access(db, tenant.id, container.id)
    assert [e["actor_name"] for e in state["history"]] == [None]


def test_redact_people_keeps_verdicts_and_assignees():
    from app.modules.work import coverage

    assignee = {
        "employee_id": "e1",
        "name": "A",
        "position": None,
        "label": "assigned",
        "missing_codes": ["P6"],
    }
    matched = {
        "employee_id": "e2",
        "name": "B",
        "position": "Controller",
        "label": "assessed",
        "missing_codes": [],
    }
    result = {
        "steps": [
            {"verdict": "human", "human": assignee, "human_backup": False},
            {"verdict": "agent", "human": matched, "human_backup": True},
            {"verdict": "gap", "human": None, "human_backup": False},
        ]
    }
    steps = coverage.redact_people(result)["steps"]
    assert steps[0]["human"] == {**assignee, "missing_codes": []}
    assert steps[1]["human"] is None and steps[1]["human_backup"] is False
    assert [s["verdict"] for s in steps] == ["human", "agent", "gap"]


def test_redact_people_keeps_a_colleague_within_the_reader_scope():
    from app.modules.work import coverage

    matched = {
        "employee_id": "e2",
        "name": "B",
        "position": None,
        "label": "assessed",
        "missing_codes": [],
    }
    assignee = {
        "employee_id": "e1",
        "name": "A",
        "position": None,
        "label": "assigned",
        "missing_codes": ["P6"],
    }

    def payload():
        return {
            "steps": [
                {"verdict": "agent", "human": dict(matched), "human_backup": True},
                {"verdict": "human", "human": dict(assignee), "human_backup": False},
            ]
        }

    # A manager whose subtree holds both reads them as admin / hr would.
    steps = coverage.redact_people(payload(), visible={"e1", "e2"})["steps"]
    assert steps[0]["human"] == matched and steps[0]["human_backup"] is True
    assert steps[1]["human"] == assignee
    # Outside the subtree the match is dropped and the assignee's gaps hidden.
    steps = coverage.redact_people(payload(), visible={"e9"})["steps"]
    assert steps[0]["human"] is None and steps[0]["human_backup"] is False
    assert steps[1]["human"] == {**assignee, "missing_codes": []}


class TestReaderScope:
    async def test_leave_status_is_for_the_managers_only(
        self, client, auth_client, db, tenant
    ):
        """HRP-623: with the terminated already out of the list, ``assignable``
        is the leave status. Admin / hr read it; an owner outside them sees
        everyone as assignable, and the assignment itself refuses."""
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Rota"}
        )
        cid = created.json()["id"]
        owner, _, owner_h = await _person(db, tenant, "employee")
        _, away_emp, _ = await _person(db, tenant, "employee")
        away_emp.status = "on_leave"
        await db.commit()
        await auth_client.patch(
            f"/api/work/containers/{cid}", json={"owner_id": str(owner.id)}
        )
        as_admin = await auth_client.get(f"/api/work/containers/{cid}/people")
        flags = {p["employee_id"]: p["assignable"] for p in as_admin.json()}
        assert flags[str(away_emp.id)] is False
        as_owner = await client.get(
            f"/api/work/containers/{cid}/people", headers=owner_h
        )
        assert as_owner.status_code == 200, as_owner.text
        assert all(p["assignable"] for p in as_owner.json())
        assert str(away_emp.id) in {p["employee_id"] for p in as_owner.json()}

    async def test_only_a_manager_read_starts_a_mapping_run(
        self, client, auth_client, db, tenant
    ):
        """A plain reader's GET must not enqueue a model run over the
        tenant's competences; a manager's does (HRP-810)."""
        from unittest.mock import AsyncMock, patch

        from app.modules.work import coverage

        from tests.unit.test_coverage_matching import _competence

        await db.execute(catalog_data.seed_insert())
        await db.commit()
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Close"}
        )
        cid = created.json()["id"]
        await auth_client.post(
            f"/api/work/containers/{cid}/steps",
            json={"title": "Post the entries", "primitive_codes": ["P1"]},
        )
        await _competence(db, tenant.id, [], mapped=False)
        _, reader_emp, reader_h = await _person(db, tenant, "employee")
        await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={
                "visibility": "restricted",
                "rules": [{"employee_id": str(reader_emp.id)}],
            },
        )
        with patch.object(
            coverage, "_schedule_mapping", new=AsyncMock(return_value=True)
        ) as schedule:
            reader = await client.get(
                f"/api/work/containers/{cid}/coverage", headers=reader_h
            )
            assert reader.status_code == 200, reader.text
            assert reader.json()["mapping_pending"] is False
            schedule.assert_not_awaited()
            manager = await auth_client.get(f"/api/work/containers/{cid}/coverage")
            assert manager.json()["mapping_pending"] is True
            schedule.assert_awaited_once()
