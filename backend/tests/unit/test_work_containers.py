"""HRP-754: work containers and steps — the step lifecycle flips in the
service, accept pins the catalog version, reorder is one statement, and
the role and tenant gates of ``/api/work/*``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.primitives import catalog_data
from app.modules.work import service
from app.modules.work.models import WorkContainer, WorkStep
from app.modules.work.schemas import (
    ContainerCreate,
    ContainerUpdate,
    StepCreate,
    StepUpdate,
)
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_coverage_matching import _employee


@pytest.fixture
async def primitives(db: AsyncSession):
    await db.execute(catalog_data.seed_insert())
    await db.commit()


async def _role(db: AsyncSession, code: str) -> Role:
    role = (await db.execute(select(Role).where(Role.code == code))).scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
    return role


async def _user_with_role(
    db: AsyncSession, tenant: Tenant, code: str
) -> tuple[User, str]:
    role = await _role(db, code)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=code.title(),
        last_name="User",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    return u, create_access_token(str(u.id), str(tenant.id))


async def _container(db: AsyncSession, tenant, user, **overrides):
    data = ContainerCreate(
        type="process",
        title="Contract review",
        description="Legal reviews contracts",
        **overrides,
    )
    return await service.create_container(db, tenant.id, data, user_id=user.id)


async def _suggested_step(
    db: AsyncSession, container, position: int, title: str
) -> WorkStep:
    """A step the way apply_session writes it — straight from the model."""
    step = WorkStep(
        tenant_id=container.tenant_id,
        container_id=container.id,
        position=position,
        title=title,
        state="system_suggested",
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


class TestSteps:
    async def test_step_without_primitives_is_valid(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db,
            tenant.id,
            c.id,
            StepCreate(
                title="Signature by the authorised signatory",
                responsibility="regulatory",
                output_type="external_change",
            ),
        )
        assert step["primitive_codes"] == []
        assert step["position"] == 1
        # A step the tenant typed in is already the tenant's own.
        assert step["state"] == "tenant_edited"

    async def test_patch_flips_state_in_the_service(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "Intake with a structured form")
        updated = await service.update_step(
            db, tenant.id, step.id, StepUpdate(responsibility="formal")
        )
        assert updated["responsibility"] == "formal"
        assert updated["state"] == "tenant_edited"

    async def test_set_primitives_flips_state_and_rejects_unknown_codes(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "Check against the playbook")
        updated = await service.set_step_primitives(
            db, tenant.id, step.id, ["P2", "P1"]
        )
        # Catalog order, whatever order the caller sent.
        assert updated["primitive_codes"] == ["P1", "P2"]
        assert updated["state"] == "tenant_edited"

        with pytest.raises(HTTPException) as exc:
            await service.set_step_primitives(db, tenant.id, step.id, ["P1", "P99"])
        assert exc.value.status_code == 404

        # The unknown codes came from the request: the message names a few,
        # cut to a code's length, rather than mirroring what was sent.
        with pytest.raises(HTTPException) as exc:
            await service.set_step_primitives(
                db, tenant.id, step.id, [f"{i}{'x' * 500}" for i in range(20)]
            )
        assert exc.value.status_code == 404
        assert len(exc.value.params["codes"]) <= (
            service.UNKNOWN_CODES_ECHOED * (service.CODE_ECHO_MAX + 2)
        )

        cleared = await service.set_step_primitives(db, tenant.id, step.id, [])
        assert cleared["primitive_codes"] == []

    async def test_accept_flips_every_step_and_pins_catalog_version(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        await _suggested_step(db, c, 1, "Intake")
        edited = await _suggested_step(db, c, 2, "Triage")
        await service.update_step(
            db, tenant.id, edited.id, StepUpdate(title="Triage by risk")
        )
        c.catalog_version = "v0"
        await db.commit()

        accepted = await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        assert accepted.status == "active"
        assert accepted.catalog_version == catalog_data.CATALOG_VERSION
        states = {s["state"] for s in await service.list_steps(db, tenant.id, c.id)}
        assert states == {"accepted"}

    async def test_accept_needs_owner_or_manage_role(
        self, db, tenant, user, primitives
    ):
        owner, _ = await _user_with_role(db, tenant, "manager")
        c = await _container(db, tenant, user, owner_id=owner.id)
        await _suggested_step(db, c, 1, "one")
        with pytest.raises(HTTPException) as exc:
            await service.accept_container(
                db, tenant.id, c.id, user_id=uuid.uuid4(), can_manage=False
            )
        assert exc.value.status_code == 403
        accepted = await service.accept_container(
            db, tenant.id, c.id, user_id=owner.id, can_manage=False
        )
        assert accepted.status == "active"

    async def test_accept_refuses_an_empty_breakdown(
        self, db, tenant, user, primitives
    ):
        """``active`` means every step is accepted, so a container with no
        steps has nothing to say it about - and the last step leaving an
        active one takes the status with it."""
        c = await _container(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.accept_container(
                db, tenant.id, c.id, user_id=user.id, can_manage=True
            )
        assert exc.value.status_code == 422
        assert exc.value.code == "work_container_accept_empty"

        step = await _suggested_step(db, c, 1, "one")
        accepted = await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        assert accepted.status == "active"
        await service.delete_step(db, tenant.id, step.id)
        await db.refresh(c)
        assert c.status == "draft"

    async def test_reorder_renumbers_every_step(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        s1 = await _suggested_step(db, c, 1, "one")
        s2 = await _suggested_step(db, c, 2, "two")
        s3 = await _suggested_step(db, c, 3, "three")

        ordered = await service.reorder_steps(
            db, tenant.id, c.id, [s3.id, s1.id, s2.id]
        )

        assert [s["id"] for s in ordered] == [s3.id, s1.id, s2.id]
        assert [s["position"] for s in ordered] == [1, 2, 3]
        # Order is not content: the steps stay as the model suggested them.
        assert {s["state"] for s in ordered} == {"system_suggested"}

        with pytest.raises(HTTPException) as exc:
            await service.reorder_steps(db, tenant.id, c.id, [s1.id, s2.id])
        assert exc.value.status_code == 422

    async def test_parallel_appends_do_not_share_a_position(
        self, db, tenant, user, primitives, session_factory
    ):
        """Appending reads ``max(position)`` and the step count, so the two
        writers take the container's row lock first. Without it both read
        the same maximum, two steps land on one position, and every later
        reorder is refused for good - it must name each position once."""
        import asyncio

        c = await _container(db, tenant, user)
        tenant_id, container_id = tenant.id, c.id

        async def _append(title: str) -> dict:
            async with session_factory() as other:
                return await service.create_step(
                    other, tenant_id, container_id, StepCreate(title=title)
                )

        first, second = await asyncio.gather(_append("one"), _append("two"))
        assert sorted([first["position"], second["position"]]) == [1, 2]

    async def test_put_primitives_keeps_provenance_of_kept_codes(
        self, db, tenant, user, primitives
    ):
        from app.modules.work.models import WorkStepPrimitive

        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "Screen against sanctions lists")
        await service.set_step_primitives(db, tenant.id, step.id, ["P2"])
        await db.execute(
            WorkStepPrimitive.__table__.update()
            .where(WorkStepPrimitive.step_id == step.id)
            .values(source="system_suggested")
        )
        await db.commit()
        await service.set_step_primitives(db, tenant.id, step.id, ["P2", "P3"])
        rows = await db.execute(
            select(WorkStepPrimitive.source).where(WorkStepPrimitive.step_id == step.id)
        )
        assert sorted(rows.scalars().all()) == ["system_suggested", "tenant_edited"]

    async def test_archived_container_is_read_only(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "one")
        c.status = "archived"
        await db.commit()
        for call in (
            service.create_step(db, tenant.id, c.id, StepCreate(title="two")),
            service.update_step(db, tenant.id, step.id, StepUpdate(title="x")),
            service.set_step_primitives(db, tenant.id, step.id, ["P1"]),
            service.reorder_steps(db, tenant.id, c.id, [step.id]),
            service.accept_container(
                db, tenant.id, c.id, user_id=user.id, can_manage=True
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 409
        # The container's own fields are content too - only un-archiving passes.
        with pytest.raises(HTTPException) as exc:
            await service.update_container(
                db, tenant.id, c.id, ContainerUpdate(title="renamed")
            )
        assert exc.value.status_code == 409
        await service.update_container(
            db, tenant.id, c.id, ContainerUpdate(status="draft")
        )
        assert c.status == "draft"

    async def test_content_change_reopens_an_accepted_breakdown(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "one")
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        # Same links again: nothing changed, nothing flips.
        await service.set_step_primitives(db, tenant.id, step.id, [])
        await db.refresh(c)
        assert c.status == "active"
        await service.set_step_primitives(db, tenant.id, step.id, ["P1"])
        await db.refresh(c)
        assert c.status == "draft"
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        await service.update_step(db, tenant.id, step.id, StepUpdate(title="two"))
        await db.refresh(c)
        assert c.status == "draft"

    async def test_assign_and_clear_executor_and_accountable(
        self, db, tenant, user, primitives
    ):
        """HRP-809: an assignment names people, not content - the step keeps
        its state and an accepted breakdown stays accepted."""
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "Sign off the report")
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        doer = await _employee(db, tenant, last_name="Doer")
        checker = await _employee(db, tenant, last_name="Checker")
        updated = await service.update_step(
            db,
            tenant.id,
            step.id,
            StepUpdate(
                executor_employee_id=doer.id, accountable_employee_id=checker.id
            ),
        )
        assert updated["executor_employee_id"] == doer.id
        assert updated["accountable_employee_id"] == checker.id
        assert updated["state"] == "accepted"
        await db.refresh(c)
        assert c.status == "active"

        cleared = await service.update_step(
            db, tenant.id, step.id, StepUpdate(executor_employee_id=None)
        )
        assert cleared["executor_employee_id"] is None
        assert cleared["accountable_employee_id"] == checker.id
        assert cleared["state"] == "accepted"

    async def test_assignee_must_be_an_active_employee_of_the_tenant(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "Approve")
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        stranger = await _employee(db, other)
        gone = await _employee(db, tenant, status="terminated")
        for field in ("executor_employee_id", "accountable_employee_id"):
            for employee_id in (stranger.id, gone.id, uuid.uuid4()):
                with pytest.raises(AppError) as exc:
                    await service.update_step(
                        db, tenant.id, step.id, StepUpdate(**{field: employee_id})
                    )
                assert exc.value.status_code == 422
                assert exc.value.code == "work_step_employee_invalid"
        await db.refresh(step)
        assert step.executor_employee_id is None
        assert step.accountable_employee_id is None

    async def test_deleting_the_added_step_restores_active(
        self, db, tenant, user, primitives
    ):
        """A step added to an accepted breakdown reopens it; removing that
        step again leaves every remaining step accepted, so the container is
        active again rather than a draft with nothing left to accept."""
        c = await _container(db, tenant, user)
        await _suggested_step(db, c, 1, "one")
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        added = await service.create_step(db, tenant.id, c.id, StepCreate(title="two"))
        await db.refresh(c)
        assert c.status == "draft"
        await service.delete_step(db, tenant.id, added["id"])
        await db.refresh(c)
        assert c.status == "active"

    async def test_delete_container_takes_its_steps(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        step = await _suggested_step(db, c, 1, "one")
        await service.set_step_primitives(db, tenant.id, step.id, ["P1"])
        await service.delete_container(db, tenant.id, c.id)
        gone = await db.execute(select(WorkStep.id).where(WorkStep.id == step.id))
        assert gone.first() is None


class TestRouter:
    async def test_roles_and_tenants(self, client, auth_client, db, tenant, primitives):
        admin_headers = dict(client.headers)
        created = await auth_client.post(
            "/api/work/containers",
            json={
                "type": "process",
                "title": "Goods receipt",
                "description": "Inbound",
            },
        )
        assert created.status_code == 201, created.text
        container_id = created.json()["id"]
        assert created.json()["catalog_version"] == catalog_data.CATALOG_VERSION

        step = await auth_client.post(
            f"/api/work/containers/{container_id}/steps",
            json={"title": "Count and scan against the PO", "primitive_codes": ["P2"]},
        )
        assert step.status_code == 201, step.text
        step_id = step.json()["id"]
        assert step.json()["primitive_codes"] == ["P2"]

        bad_enum = await auth_client.post(
            f"/api/work/containers/{container_id}/steps",
            json={"title": "x", "responsibility": "total"},
        )
        assert bad_enum.status_code == 422

        _, employee_token = await _user_with_role(db, tenant, "employee")
        _, manager_token = await _user_with_role(db, tenant, "manager")
        _, hr_token = await _user_with_role(db, tenant, "hr")

        # HRP-810: a new process is restricted - neither an employee nor a
        # manager sees it, and its steps are as absent as it is.
        for token in (employee_token, manager_token):
            client.headers["Authorization"] = f"Bearer {token}"
            listed = await client.get("/api/work/containers")
            assert listed.status_code == 200 and listed.json()["items"] == []
            assert (
                await client.get(f"/api/work/containers/{container_id}/steps")
            ).status_code == 404

        # Opened to the company, a manager reads it and still cannot write.
        await db.execute(
            update(WorkContainer)
            .where(WorkContainer.id == uuid.UUID(container_id))
            .values(visibility="company")
        )
        await db.commit()
        client.headers["Authorization"] = f"Bearer {manager_token}"
        assert (await client.get("/api/work/containers")).status_code == 200
        assert (
            await client.get(f"/api/work/containers/{container_id}/steps")
        ).status_code == 200
        for refused in (
            client.patch(f"/api/work/steps/{step_id}", json={"title": "x"}),
            client.patch(f"/api/work/containers/{container_id}", json={"title": "x"}),
            client.post(
                f"/api/work/containers/{container_id}/steps", json={"title": "x"}
            ),
            client.post(f"/api/work/containers/{container_id}/accept"),
            client.post("/api/work/containers", json={"type": "process", "title": "x"}),
            client.delete(f"/api/work/containers/{container_id}"),
            client.delete(f"/api/work/steps/{step_id}"),
            client.put(
                f"/api/work/containers/{container_id}/steps/order",
                json={"step_ids": [step_id]},
            ),
            client.put(f"/api/work/steps/{step_id}/primitives", json={"codes": []}),
        ):
            assert (await refused).status_code == 403

        client.headers["Authorization"] = f"Bearer {hr_token}"
        patched = await client.patch(
            f"/api/work/steps/{step_id}", json={"hours_per_run": 2.5}
        )
        assert patched.status_code == 200
        assert patched.json()["state"] == "tenant_edited"
        assert patched.json()["hours_per_run"] == 2.5
        # W6: the CHECK bounds are validated before the flush.
        for body in (
            {"hours_per_run": 0},
            # Numeric(6, 2) would round this to 0.00 and fail the CHECK
            # with a 500; the schema floor turns it into a 422.
            {"hours_per_run": 0.004},
            {"hours_per_run": 201},
            {"runs_per_year": 0},
        ):
            assert (
                await client.patch(f"/api/work/steps/{step_id}", json=body)
            ).status_code == 422, body
        # An explicit null on a NOT NULL column is a validation error, not a
        # 500 - and the error names the field.
        null_title = await client.patch(
            f"/api/work/steps/{step_id}", json={"title": None}
        )
        assert null_title.status_code == 422
        assert "title" in str(null_title.json())
        assert (
            await client.patch(
                f"/api/work/containers/{container_id}", json={"status": "active"}
            )
        ).status_code == 422
        # ...while clearing a nullable one is fine.
        cleared = await client.patch(
            f"/api/work/steps/{step_id}", json={"hours_per_run": None}
        )
        assert cleared.status_code == 200
        # HRP-809: a null assignee is how the screen takes the assignment off.
        unassigned = await client.patch(
            f"/api/work/steps/{step_id}",
            json={"executor_employee_id": None, "accountable_employee_id": None},
        )
        assert unassigned.status_code == 200, unassigned.text
        assert unassigned.json()["executor_employee_id"] is None
        assert cleared.json()["hours_per_run"] is None
        put = await client.put(
            f"/api/work/steps/{step_id}/primitives", json={"codes": ["B1", "P2"]}
        )
        assert put.status_code == 200
        assert put.json()["primitive_codes"] == ["P2", "B1"]

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        _, other_admin = await _user_with_role(db, other, "admin")
        client.headers["Authorization"] = f"Bearer {other_admin}"
        assert (
            await client.get(f"/api/work/containers/{container_id}")
        ).status_code == 404
        assert (
            await client.patch(f"/api/work/steps/{step_id}", json={"title": "x"})
        ).status_code == 404
        assert (
            await client.put(
                f"/api/work/containers/{container_id}/steps/order",
                json={"step_ids": [step_id]},
            )
        ).status_code == 404
        assert (
            await client.put(
                f"/api/work/steps/{step_id}/primitives", json={"codes": ["P1"]}
            )
        ).status_code == 404
        assert (await client.get("/api/work/containers")).json()["total"] == 0

        client.headers.clear()
        client.headers.update(admin_headers)
        listed = await client.get("/api/work/containers", params={"type": "process"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        deleted = await client.delete(f"/api/work/containers/{container_id}")
        assert deleted.status_code == 204
        assert (
            await client.get(f"/api/work/containers/{container_id}")
        ).status_code == 404

    async def test_owner_manager_accepts(
        self, client, auth_client, db, tenant, primitives
    ):
        owner, owner_token = await _user_with_role(db, tenant, "manager")
        created = await auth_client.post(
            "/api/work/containers",
            json={"type": "initiative", "title": "Launch", "owner_id": str(owner.id)},
        )
        assert created.status_code == 201, created.text
        container_id = created.json()["id"]
        step = await auth_client.post(
            f"/api/work/containers/{container_id}/steps", json={"title": "Kick off"}
        )
        assert step.status_code == 201, step.text
        unknown_owner = await auth_client.patch(
            f"/api/work/containers/{container_id}", json={"owner_id": str(uuid.uuid4())}
        )
        assert unknown_owner.status_code == 404

        client.headers["Authorization"] = f"Bearer {owner_token}"
        accepted = await client.post(f"/api/work/containers/{container_id}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
